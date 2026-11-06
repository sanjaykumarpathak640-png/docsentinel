"""Stages 2 and 4 - Document classification, structured extraction and
structural understanding (missing / duplicated / misplaced information)."""
from __future__ import annotations

import re
from datetime import date

from rapidfuzz import fuzz

from .models import Document, ExtractedField

# --------------------------------------------------------------- classification
TYPE_KEYWORDS = {
    "identity_card": ["identity card", "date of birth", "id number", "gender", "issued by", "holder signature"],
    "salary_slip": ["salary slip", "payslip", "earnings", "deductions", "net pay", "gross earnings", "employee id"],
    "loan_application": ["application form", "applicant name", "loan amount", "loan tenure", "declaration", "applicant signature"],
    "bank_statement": ["account statement", "account holder", "opening balance", "closing balance", "debit", "credit"],
}
TYPE_LABEL = {
    "identity_card": "Identity Card",
    "salary_slip": "Salary Slip",
    "loan_application": "Loan Application Form",
    "bank_statement": "Bank Statement",
    "unknown": "Unknown",
}

# field -> (label aliases, kind)
SCHEMA = {
    "identity_card": {
        "name": (["name"], "name"),
        "dob": (["date of birth", "dob"], "date"),
        "id_no": (["id number", "id no"], "id"),
        "gender": (["gender", "sex"], "text"),
        "address": (["address"], "text"),
    },
    "salary_slip": {
        "name": (["employee name"], "name"),
        "emp_id": (["employee id"], "id"),
        "pay_period": (["pay period"], "text"),
        "pay_date": (["pay date"], "date"),
        "basic": (["basic"], "money"),
        "hra": (["hra"], "money"),
        "special": (["special allowance"], "money"),
        "pf": (["provident fund"], "money"),
        "ptax": (["professional tax"], "money"),
        "tds": (["income tax"], "money"),
        "gross": (["gross earnings", "gross salary", "gross"], "money"),
        "total_deductions": (["total deductions"], "money"),
        "net_pay": (["net pay", "net salary"], "money"),
    },
    "loan_application": {
        "name": (["applicant name"], "name"),
        "dob": (["date of birth"], "date"),
        "id_no": (["id number"], "id"),
        "address": (["address"], "text"),
        "employer": (["employer"], "text"),
        "income": (["monthly net income", "monthly income"], "money"),
        "loan_amount": (["loan amount"], "money"),
        "tenure": (["loan tenure"], "text"),
        "app_date": (["application date"], "date"),
    },
    "bank_statement": {
        "name": (["account holder"], "name"),
        "account_no": (["account number"], "id"),
        "address": (["address"], "text"),
        "period": (["statement period"], "text"),
        "closing": (["closing balance"], "money"),
    },
}

FIELD_LABEL = {
    "name": "Name", "dob": "Date of birth", "id_no": "ID number", "gender": "Gender", "address": "Address",
    "emp_id": "Employee ID", "pay_period": "Pay period", "pay_date": "Pay date", "basic": "Basic",
    "hra": "HRA", "special": "Special allowance", "pf": "Provident fund", "ptax": "Professional tax",
    "tds": "Income tax", "gross": "Gross earnings", "total_deductions": "Total deductions",
    "net_pay": "Net pay", "employer": "Employer", "income": "Monthly net income",
    "loan_amount": "Loan amount", "tenure": "Loan tenure", "app_date": "Application date",
    "account_no": "Account number", "period": "Statement period", "closing": "Closing balance",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace(":", " ")).strip()


def classify(doc: Document) -> None:
    text = _norm(" ".join(s.text for p in doc.pages for row in p.rows for s in row))
    scores = {}
    for t, kws in TYPE_KEYWORDS.items():
        hits = sum(1 for k in kws if _norm(k) in text)
        scores[t] = hits / len(kws)
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    margin = ranked[0] - (ranked[1] if len(ranked) > 1 else 0)
    if ranked[0] < 0.34:
        doc.doc_type, doc.type_conf = "unknown", ranked[0]
    else:
        doc.doc_type = best
        doc.type_conf = min(0.99, 0.5 * ranked[0] + 0.5 * min(1.0, margin * 1.6) + 0.15)
    doc.type_scores = {k: round(v, 2) for k, v in scores.items()}


# ------------------------------------------------------------------ normalisers
def parse_money(s: str):
    m = re.search(r"-?[\d,]+(?:\.\d{1,2})?", s.replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_date(s: str):
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return "INVALID:" + m.group(0)


def normalise(kind: str, raw: str):
    raw = raw.strip()
    if kind == "money":
        return parse_money(raw)
    if kind == "date":
        return parse_date(raw)
    if kind == "name":
        return " ".join(w.capitalize() for w in re.sub(r"[^A-Za-z .'-]", "", raw).split())
    if kind == "id":
        return re.sub(r"\s", "", raw).upper()
    return re.sub(r"\s+", " ", raw)


# ------------------------------------------------------------------- extraction
def _label_match(seg_text: str, alias: str) -> float:
    a, b = _norm(seg_text), _norm(alias)
    if not a:
        return 0
    if a == b:
        return 100
    return fuzz.ratio(a, b)


def extract_fields(doc: Document) -> None:
    schema = SCHEMA.get(doc.doc_type, {})
    found = {}
    dupes = {}
    for p in doc.pages:
        for row in p.rows:
            for si, seg in enumerate(row):
                txt = seg.text
                for fname, (aliases, kind) in schema.items():
                    score = max(_label_match(txt.split(":")[0] if ":" in txt else txt, al) for al in aliases)
                    if score < 88:
                        continue
                    # value: text after the colon in the same segment, else next segment
                    value_words, label_bbox = None, seg.bbox
                    if ":" in txt and txt.split(":", 1)[1].strip():
                        idx = next(i for i, w in enumerate(seg.words) if ":" in w.text)
                        value_words = seg.words[idx + 1:] or None
                    if value_words is None and si + 1 < len(row):
                        value_words = row[si + 1].words
                    if not value_words:
                        continue
                    raw = " ".join(w.text for w in value_words)
                    bbox = (min(w.bbox[0] for w in value_words), min(w.bbox[1] for w in value_words),
                            max(w.bbox[2] for w in value_words), max(w.bbox[3] for w in value_words))
                    conf = sum(w.conf for w in value_words) / len(value_words)
                    ef = ExtractedField(name=fname, value=normalise(kind, raw), raw=raw, conf=round(conf, 1),
                                        page=p.index, bbox=tuple(round(v, 1) for v in bbox),
                                        label_bbox=tuple(round(v, 1) for v in label_bbox))
                    if fname in found:
                        dupes.setdefault(fname, [found[fname]]).append(ef)
                    else:
                        found[fname] = ef
    # salary slips: employer is the letterhead (first, largest row)
    if doc.doc_type == "salary_slip" and doc.pages and doc.pages[0].rows:
        first = doc.pages[0].rows[0][0]
        found["employer"] = ExtractedField("employer", normalise("text", first.text), first.text,
                                           round(first.conf, 1), 0, first.bbox, None, "letterhead")
    doc.fields = found
    doc.structure["duplicates"] = {k: [f.raw for f in v] for k, v in dupes.items()}
    if doc.doc_type == "bank_statement":
        _extract_transactions(doc)


def _extract_transactions(doc: Document) -> None:
    rows_out = []
    for p in doc.pages:
        cols = None
        for row in p.rows:
            texts = [s.text.lower() for s in row]
            if cols is None and {"debit", "credit", "balance"} <= set(texts):
                cols = {s.text.lower(): (s.bbox[0] + s.bbox[2]) / 2 for s in row}
                continue
            if cols is None:
                continue
            if not re.match(r"\d{2}/\d{2}/\d{4}", row[0].text):
                if row[0].text.lower().startswith("closing"):
                    break
                continue
            rec = {"date": parse_date(row[0].text), "date_raw": row[0].text, "page": p.index,
                   "description": "", "debit": None, "credit": None, "balance": None,
                   "bbox": row[0].bbox, "cells": {}}
            for seg in row[1:]:
                amt = parse_money(seg.text) if re.fullmatch(r"-?[\d,]+\.\d{2}", seg.text.strip()) else None
                if amt is None:
                    rec["description"] = (rec["description"] + " " + seg.text).strip()
                    continue
                cx = (seg.bbox[0] + seg.bbox[2]) / 2
                col = min(("debit", "credit", "balance"), key=lambda c: abs(cols[c] - cx))
                rec[col] = amt
                rec["cells"][col] = seg.bbox
            x0 = min(s.bbox[0] for s in row); x1 = max(s.bbox[2] for s in row)
            rec["bbox"] = (x0, min(s.bbox[1] for s in row), x1, max(s.bbox[3] for s in row))
            rows_out.append(rec)
    doc.tables["transactions"] = rows_out


def analyse_structure(doc: Document) -> None:
    schema = SCHEMA.get(doc.doc_type, {})
    missing = [f for f in schema if f not in doc.fields]
    low_conf = [f for f, v in doc.fields.items() if v.conf < 60]
    # hierarchy: label -> value pairs, ordered top-to-bottom
    hierarchy = sorted(({"field": k, "label_bbox": v.label_bbox, "value_bbox": v.bbox} for k, v in doc.fields.items()),
                       key=lambda r: r["value_bbox"][1])
    # alignment groups: values that share a left edge form a column
    lefts = sorted(round(v.bbox[0]) for v in doc.fields.values())
    columns = []
    for x in lefts:
        if columns and abs(columns[-1][-1] - x) <= 12:
            columns[-1].append(x)
        else:
            columns.append([x])
    doc.structure.update({
        "expected_fields": list(schema.keys()),
        "missing": missing,
        "low_confidence": low_conf,
        "hierarchy": hierarchy,
        "value_columns": [round(sum(c) / len(c)) for c in columns if len(c) >= 2],
        "completeness": round(1 - len(missing) / max(1, len(schema)), 2),
    })
