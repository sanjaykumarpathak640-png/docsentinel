"""Stages 6-8 - Turn detector output and extracted data into findings.

  * structural  : missing / duplicated / low-confidence fields
  * visual      : noise-inconsistent regions, glyph-size outliers, signatures
  * digital     : PDF font and metadata anomalies
  * contextual  : arithmetic and logic rules inside one document
  * cross_document : entity matching across the whole submission
"""
from __future__ import annotations

from datetime import date

from rapidfuzz import fuzz

from .extract import FIELD_LABEL, TYPE_LABEL
from .forensics import signature_similarity
from .models import (INCONSISTENCY, OBSERVATION, Evidence, Finding)

TOL = 1.0  # currency tolerance (rupees)


class FindingBuilder:
    def __init__(self):
        self.items: list[Finding] = []

    def add(self, **kw) -> Finding:
        f = Finding(id=f"F-{len(self.items) + 1:03d}", **kw)
        self.items.append(f)
        return f


def _fev(doc, fname, note="") -> Evidence:
    f = doc.fields[fname]
    return Evidence(doc_id=doc.doc_id, page=f.page, bbox=f.bbox, field=fname, value=f.raw,
                    note=note or f"{FIELD_LABEL.get(fname, fname)} as read (OCR conf {f.conf:.0f}%)", kind="field")


def _money(v):
    return "-" if v is None else f"{v:,.2f}".rstrip("0").rstrip(".")


def _conf_factor(*fields) -> float:
    """Data-driven findings inherit uncertainty from the OCR of the fields used."""
    cs = [f.conf for f in fields if f is not None]
    return min(cs) / 100 if cs else 0.8


# =================================================================== structural
def structural_findings(fb: FindingBuilder, doc):
    st = doc.structure
    tl = TYPE_LABEL.get(doc.doc_type, doc.doc_type)
    if doc.doc_type == "unknown":
        fb.add(title=f"{doc.filename}: document type could not be determined", category="structural",
               status=OBSERVATION, severity="medium", confidence=0.6,
               explanation="Keyword-based classification did not reach the minimum score for any supported type. "
                           "Field extraction and type-specific rules were skipped for this file.",
               evidence=[Evidence(doc.doc_id, 0, None, note=f"type scores: {doc.type_scores}", kind="computed")],
               verification="Confirm the document type manually; it may be unsupported.", rule="S0-classification")
        return
    if st.get("missing"):
        fb.add(title=f"{tl}: expected field(s) missing - " + ", ".join(FIELD_LABEL.get(m, m) for m in st["missing"]),
               category="structural", status=OBSERVATION, severity="medium" if len(st["missing"]) > 1 else "low",
               confidence=0.7,
               explanation=f"The layout for a {tl} normally contains these fields, but no matching label/value pair "
                           f"was found. This may be an OCR miss, a different template, or information that was removed.",
               evidence=[Evidence(doc.doc_id, 0, None, note="expected: " + ", ".join(st["expected_fields"]), kind="computed")],
               verification="Inspect the original document for the missing fields.", rule="S1-missing-fields")
    for fname, raws in st.get("duplicates", {}).items():
        fb.add(title=f"{tl}: field '{FIELD_LABEL.get(fname, fname)}' appears more than once",
               category="structural", status=INCONSISTENCY if len(set(raws)) > 1 else OBSERVATION,
               severity="medium", confidence=0.75,
               explanation=f"Values found: {', '.join(raws)}. Duplicated fields with different values are a common "
                           f"sign of an inserted or edited section.",
               evidence=[_fev(doc, fname)], verification="Check which occurrence is original.", rule="S2-duplicate")
    for fname in st.get("low_confidence", []):
        f = doc.fields[fname]
        fb.add(title=f"{tl}: low OCR confidence on '{FIELD_LABEL.get(fname, fname)}'", category="structural",
               status=OBSERVATION, severity="low", confidence=0.6,
               explanation=f"The value '{f.raw}' was read with {f.conf:.0f}% confidence. Downstream checks using "
                           f"this field are less reliable. OCR output is never treated as ground truth.",
               evidence=[_fev(doc, fname)], verification="Read the field manually.", rule="S3-low-confidence")


# ======================================================================= visual
def visual_findings(fb: FindingBuilder, doc, fx: dict):
    tl = TYPE_LABEL.get(doc.doc_type, doc.doc_type)
    nz = fx.get("noise", {})
    for r in nz.get("regions", []):
        fields = r.get("fields", [])
        what = ("the value of " + ", ".join(f"'{FIELD_LABEL.get(f, f)}'" for f in fields)) if fields else \
               ("an embedded image / photograph area" if r.get("kind") == "image" else "a text area")
        ev = [Evidence(doc.doc_id, 0, r["bbox"], note=f"noise level {r['region_noise']} vs page {r['page_noise']} "
                                                    f"(x{r['ratio']}); ELA response x{r.get('ela_ratio')}", kind="region")]
        for f in fields:
            ev.append(_fev(doc, f, "field adjacent to the clean region"))
        ela_note = ""
        er = r.get("ela_ratio", 1)
        if er < 0.5 or er > 2:
            ela_note = f" Error Level Analysis also responds differently here (x{er} of the page average), " \
                       f"suggesting a different compression history."
        fb.add(title=f"{tl}: region lacks scanner noise near {what}", category="visual", status=OBSERVATION,
               severity="high" if (fields or r.get("kind") == "image") else "medium",
               confidence=round(min(0.9, 0.55 + 0.02 * r["blocks"] + (0.1 if ela_note else 0)), 2),
               explanation=f"Scanned paper carries roughly uniform sensor noise (page median {r['page_noise']}). "
                           f"A {r['bbox'][2] - r['bbox'][0]}x{r['bbox'][3] - r['bbox'][1]} px area near {what} is "
                           f"almost noise-free (x{r['ratio']}). Areas added digitally after scanning, such as a "
                           f"pasted patch or replaced photo, typically look like this.{ela_note}",
               evidence=ev, verification="Compare with the physical original or an independently obtained copy.",
               rule="V1-noise-consistency", signals={"fields": fields, "kind": r.get("kind")})
    for g in fx.get("glyph", []):
        fname = g["field"]
        fb.add(title=f"{tl}: character size of '{FIELD_LABEL.get(fname, fname)}' differs from aligned values",
               category="visual", status=OBSERVATION, severity="medium",
               confidence=round(min(0.85, 0.5 + abs(g["deviation"]) * 2), 2),
               explanation=f"Values in the same column ({', '.join(FIELD_LABEL.get(p, p) for p in g['peers'])}) have a "
                           f"median character height of {g['column_median']:.0f}px; this value measures "
                           f"{g['height']:.0f}px ({g['deviation']:+.0%}). Documents generated by one system usually use "
                           f"one font size per column, so a single outlier suggests the value was typed separately.",
               evidence=[_fev(doc, fname, f"glyph height {g['height']:.0f}px vs column {g['column_median']:.0f}px")],
               verification="Check the typeface and size of this value against the original.",
               rule="V3-glyph-size", signals={"fields": [fname]})
    sig = fx.get("signature", {})
    if sig.get("available") and sig.get("label_bbox"):
        if sig.get("placement") == "outside":
            b = sig["outside"][0]
            fb.add(title=f"{tl}: signature placed outside the designated signature area", category="visual",
                   status=OBSERVATION, severity="medium", confidence=0.8,
                   explanation=f"A signature-like ink stroke was found at {tuple(b)}, but the designated "
                               f"{sig['designated_kind']} at {tuple(sig['designated_area'])} is empty. A signature "
                               f"outside its box can indicate it was transplanted from another document.",
                   evidence=[Evidence(doc.doc_id, 0, b, note="detected signature", kind="region"),
                             Evidence(doc.doc_id, 0, tuple(sig["designated_area"]), note="designated signature area (empty)", kind="region")],
                   verification="Ask for a freshly signed copy; compare with the signature on file.",
                   rule="V4-signature-placement", signals={"fields": ["signature"]})
        elif sig.get("placement") == "missing":
            fb.add(title=f"{tl}: signature field present but no signature detected", category="visual",
                   status=OBSERVATION, severity="low", confidence=0.55,
                   explanation="A signature label was found but no ink stroke was detected nearby. Black-ink "
                               "signatures are not detected by this prototype, so treat this as low confidence.",
                   evidence=[Evidence(doc.doc_id, 0, tuple(sig["designated_area"]), note="designated area", kind="region")],
                   verification="Check the original for a signature.", rule="V4-signature-missing")


def signature_cross_findings(fb: FindingBuilder, docs, fxs):
    have = [(d, fxs[d.doc_id]["signature"]) for d in docs
            if fxs[d.doc_id].get("signature", {}).get("signatures") and d.doc_type in ("identity_card", "loan_application")]
    if len(have) < 2:
        return
    (da, sa), (db, sb) = have[0], have[1]
    ba, bb = sa["signatures"][0], sb["signatures"][0]
    sim = signature_similarity(sa["mask_crops"][ba], sb["mask_crops"][bb])
    verdict = "visually consistent" if sim >= 0.9 else ("inconclusive" if sim >= 0.8 else "visually different")
    fb.add(title=f"Signature comparison {TYPE_LABEL[da.doc_type]} vs {TYPE_LABEL[db.doc_type]}: {verdict} (score {sim})",
           category="visual", status=OBSERVATION if sim >= 0.8 else INCONSISTENCY,
           severity="low" if sim >= 0.9 else "medium", confidence=0.5,
           explanation=f"Shape correlation of the two signature ink masks is {sim} (1.0 = identical shape). This is a "
                       f"coarse shape heuristic, not handwriting verification: it cannot authenticate a signer and a "
                       f"high score can also mean a signature was copied.",
           evidence=[Evidence(da.doc_id, 0, ba, note="signature A", kind="region"),
                     Evidence(db.doc_id, 0, bb, note="signature B", kind="region")],
           verification="Forensic handwriting examination if the signature matters to the decision.",
           rule="V4-signature-compare", signals={"similarity": sim})


# ====================================================================== digital
def digital_findings(fb: FindingBuilder, doc, fx: dict):
    tl = TYPE_LABEL.get(doc.doc_type, doc.doc_type)
    for item in fx.get("pdf_fonts", []):
        fields = item.get("fields", [])
        what = ", ".join(f"'{FIELD_LABEL.get(f, f)}'" for f in fields) or f"text '{item['text']}'"
        ev = [Evidence(doc.doc_id, 0, item["bbox"], value=item["text"],
                       note=f"font {item['font']} (rest of document: {item['dominant']})", kind="region")]
        fb.add(title=f"{tl}: {what} uses a font foreign to the rest of the PDF", category="digital",
               status=OBSERVATION, severity="high" if fields else "medium", confidence=0.85,
               explanation=f"The PDF text layer shows '{item['text']}' rendered in {item['font']}, while the rest of "
                           f"the document uses {item['dominant']} ({item['share']:.1%} of words use this font). "
                           f"Statement generators use a fixed font set; a single foreign-font value is typical of "
                           f"an edit made in a PDF editor.",
               evidence=ev, verification="Obtain the statement directly from the issuing bank.",
               rule="D1-pdf-font", signals={"fields": fields})
    meta = fx.get("pdf_meta", [])
    if meta:
        fb.add(title=f"{tl}: PDF metadata indicates editing after creation", category="digital",
               status=OBSERVATION, severity="medium", confidence=0.8,
               explanation="; ".join(m["detail"] for m in meta) + ". Metadata alone is weak evidence (it can be "
                           "changed legitimately or forged), but it supports other signals on this file.",
               evidence=[Evidence(doc.doc_id, 0, None, note=m["detail"], kind="metadata") for m in meta],
               verification="Request the original file from the issuer.", rule="D2-pdf-metadata",
               signals={"doc_level": True})


# =================================================================== contextual
def contextual_findings(fb: FindingBuilder, doc):
    F = doc.fields
    tl = TYPE_LABEL.get(doc.doc_type, doc.doc_type)
    g = lambda k: F[k].value if k in F else None

    def arith(title, parts, total_key, expect, rule, explain):
        got = g(total_key)
        if got is None or expect is None or abs(got - expect) <= TOL:
            return
        fb.add(title=title, category="contextual", status=INCONSISTENCY, severity="high",
               confidence=round(0.95 * _conf_factor(*(F.get(p) for p in parts), F.get(total_key)), 2),
               explanation=explain.format(expect=_money(expect), got=_money(got), diff=_money(got - expect)),
               evidence=[_fev(doc, p) for p in parts if p in F] + [_fev(doc, total_key, "stated total")] +
                        [Evidence(doc.doc_id, 0, None, value=_money(expect), note="recomputed from components", kind="computed")],
               verification="Recompute from the source system; ask the issuer which figure is correct.",
               rule=rule, signals={"fields": [total_key], "expected": expect, "stated": got})

    if doc.doc_type == "salary_slip":
        earn = [k for k in ("basic", "hra", "special") if k in F]
        ded = [k for k in ("pf", "ptax", "tds") if k in F]
        if len(earn) == 3:
            arith(f"{tl}: earnings components do not add up to Gross", earn, "gross", sum(g(k) for k in earn),
                  "C1-salary-gross", "Basic + HRA + Special = {expect}, but Gross Earnings reads {got} (difference {diff}).")
        if len(ded) == 3:
            arith(f"{tl}: deduction components do not add up to Total Deductions", ded, "total_deductions",
                  sum(g(k) for k in ded), "C2-salary-deductions",
                  "PF + Professional Tax + Income Tax = {expect}, but Total Deductions reads {got}.")
        if g("gross") is not None and g("total_deductions") is not None:
            arith(f"{tl}: Net Pay does not equal Gross minus Deductions", ["gross", "total_deductions"], "net_pay",
                  g("gross") - g("total_deductions"), "C3-salary-net",
                  "Gross Earnings - Total Deductions = {expect}, but Net Pay reads {got} (difference {diff}). "
                  "Payroll systems compute Net Pay automatically, so an arithmetic break points to the stated figure "
                  "having been changed - or an OCR misread.")
    if doc.doc_type == "bank_statement":
        tx = doc.tables.get("transactions", [])
        prev = None
        for r in tx:
            if prev is not None and r["balance"] is not None:
                exp = prev - (r["debit"] or 0) + (r["credit"] or 0)
                if abs(exp - r["balance"]) > TOL:
                    fb.add(title=f"{tl}: running balance breaks on {r['date_raw']}", category="contextual",
                           status=INCONSISTENCY, severity="high", confidence=0.9,
                           explanation=f"Previous balance {_money(prev)} - debit {_money(r['debit'] or 0)} + credit "
                                       f"{_money(r['credit'] or 0)} = {_money(exp)}, but the row shows {_money(r['balance'])}.",
                           evidence=[Evidence(doc.doc_id, r["page"], r["bbox"], value=_money(r["balance"]), note="transaction row", kind="field")],
                           verification="Request the statement from the bank.", rule="C4-bank-running-balance")
            if r["balance"] is not None:
                prev = r["balance"]
        if prev is not None and g("closing") is not None and abs(prev - g("closing")) > TOL:
            last = tx[-1]
            fb.add(title=f"{tl}: Closing Balance does not match the last running balance", category="contextual",
                   status=INCONSISTENCY, severity="high", confidence=round(0.95 * _conf_factor(F["closing"]), 2),
                   explanation=f"The transaction table ends at {_money(prev)} but the Closing Balance line reads "
                               f"{_money(g('closing'))} (difference {_money(g('closing') - prev)}). Every transaction "
                               f"was re-added; the table itself is internally consistent, so the summary line is the outlier.",
                   evidence=[_fev(doc, "closing", "stated closing balance"),
                             Evidence(doc.doc_id, last["page"], last["cells"].get("balance", last["bbox"]),
                                      value=_money(prev), note="last running balance in table", kind="field")],
                   verification="Request the statement from the bank.", rule="C5-bank-closing",
                   signals={"fields": ["closing"], "expected": prev, "stated": g("closing")})
    # generic date logic
    ref = g("app_date") or g("pay_date") or date(2026, 11, 1)
    dob = g("dob")
    if isinstance(dob, str) and dob.startswith("INVALID"):
        fb.add(title=f"{tl}: Date of birth is not a valid calendar date", category="contextual", status=INCONSISTENCY,
               severity="medium", confidence=0.8, explanation=f"'{F['dob'].raw}' cannot be a real date.",
               evidence=[_fev(doc, "dob")], verification="Check the original.", rule="C6-date-valid")
    elif isinstance(dob, date) and isinstance(ref, date):
        age = (ref - dob).days / 365.25
        if age < 18 or age > 85:
            fb.add(title=f"{tl}: age implied by date of birth is implausible ({age:.0f} years)", category="contextual",
                   status=INCONSISTENCY, severity="medium", confidence=0.8,
                   explanation=f"Date of birth {dob:%d/%m/%Y} gives an age of {age:.1f} on {ref:%d/%m/%Y}.",
                   evidence=[_fev(doc, "dob")], verification="Check eligibility rules.", rule="C7-age")


# =============================================================== cross-document
ATTRS = [
    # attribute, label, [(doc_type, field)], reference doc_type, kind
    ("name", "Name", [("identity_card", "name"), ("salary_slip", "name"), ("loan_application", "name"), ("bank_statement", "name")], "identity_card", "name"),
    ("dob", "Date of birth", [("identity_card", "dob"), ("loan_application", "dob")], "identity_card", "exact"),
    ("id_no", "ID number", [("identity_card", "id_no"), ("loan_application", "id_no")], "identity_card", "exact"),
    ("address", "Address", [("identity_card", "address"), ("loan_application", "address"), ("bank_statement", "address")], "identity_card", "text"),
    ("employer", "Employer", [("salary_slip", "employer"), ("loan_application", "employer"), ("bank_statement", "salary_desc")], "salary_slip", "org"),
    ("income", "Monthly net income", [("loan_application", "income"), ("salary_slip", "net_pay"), ("bank_statement", "salary_credit")], "bank_statement", "money"),
]


def _bank_salary(doc):
    for r in doc.tables.get("transactions", []):
        if r["credit"] and "salary" in r["description"].lower():
            return r
    return None


def build_entity_table(docs) -> list:
    by_type = {}
    for d in docs:
        by_type.setdefault(d.doc_type, d)
    table = []
    for attr, label, sources, ref_type, kind in ATTRS:
        vals = []
        for dt, fname in sources:
            d = by_type.get(dt)
            if not d:
                continue
            if fname in ("salary_credit", "salary_desc"):
                r = _bank_salary(d)
                if not r:
                    continue
                if fname == "salary_credit":
                    vals.append({"doc": d, "field": "salary_credit", "value": r["credit"], "raw": _money(r["credit"]),
                                 "bbox": r["cells"].get("credit", r["bbox"]), "page": r["page"], "conf": 99})
                else:
                    vals.append({"doc": d, "field": "salary_desc", "value": r["description"], "raw": r["description"],
                                 "bbox": r["bbox"], "page": r["page"], "conf": 99})
                continue
            if fname in d.fields:
                f = d.fields[fname]
                vals.append({"doc": d, "field": fname, "value": f.value, "raw": f.raw, "bbox": f.bbox, "page": f.page, "conf": f.conf})
        if len(vals) >= 2:
            table.append({"attr": attr, "label": label, "kind": kind, "ref_type": ref_type, "values": vals})
    return table


def _compare(kind, a, b):
    """Return (match: bool, score 0-100, note)."""
    if a is None or b is None:
        return None, 0, "missing"
    if kind == "money":
        diff = abs(a - b) / max(abs(a), abs(b), 1)
        return diff <= 0.02, round(100 * (1 - min(1, diff)), 1), f"diff {diff:.0%}"
    if kind == "exact":
        sa, sb = (a.isoformat() if isinstance(a, date) else str(a)), (b.isoformat() if isinstance(b, date) else str(b))
        return sa == sb, 100.0 if sa == sb else round(fuzz.ratio(sa, sb), 1), ""
    if kind == "org":
        sa, sb = str(a).lower(), str(b).lower()
        stop = {"pvt", "ltd", "private", "limited", "salary", "neft", "imps", "credit"}
        ta = {t for t in sa.replace(".", " ").split() if t not in stop}
        tb = {t for t in sb.replace(".", " ").split() if t not in stop}
        score = 100 * len(ta & tb) / max(1, min(len(ta), len(tb)))
        return score >= 60, round(score, 1), "token overlap"
    sa, sb = str(a).lower(), str(b).lower()
    score = fuzz.token_sort_ratio(sa, sb)
    if kind == "name":
        return score >= 95, round(score, 1), ""
    return score >= 90, round(score, 1), ""


def crossdoc_findings(fb: FindingBuilder, docs) -> list:
    table = build_entity_table(docs)
    matrix = []
    for row in table:
        vals = row["values"]
        ref = next((v for v in vals if v["doc"].doc_type == row["ref_type"]), vals[0])
        row["reference"] = ref["doc"].doc_id
        for v in vals:
            if v is ref:
                v["match"], v["score"] = None, 100.0
                continue
            m, s, note = _compare(row["kind"], ref["value"], v["value"])
            v["match"], v["score"] = m, s
            if m is False:
                ref_name, oth_name = TYPE_LABEL[ref["doc"].doc_type], TYPE_LABEL[v["doc"].doc_type]
                minor = row["kind"] in ("name", "text") and s >= 80
                why = {
                    "income": "Income stated on an application should be supported by payslip and bank credit. A "
                              "mismatch is one of the strongest indicators of an inflated income claim.",
                    "dob": "Date of birth is a stable identity attribute; documents for the same person must agree.",
                    "id_no": "The identity number must match the identity document exactly.",
                    "name": "Small spelling variations can be OCR or transliteration differences; larger ones may "
                            "indicate documents belonging to different people.",
                    "address": "Address differences may be legitimate (relocation) but should be explained.",
                    "employer": "The employer on the application should match the payslip issuer and salary credits.",
                }[row["attr"]]
                fb.add(title=f"{row['label']} mismatch: {oth_name} says '{v['raw']}', {ref_name} says '{ref['raw']}'",
                       category="cross_document", status=INCONSISTENCY,
                       severity="medium" if minor else "high",
                       confidence=round(0.92 * min(ref["conf"], v["conf"]) / 100, 2),
                       explanation=f"{why} Similarity score {s} (reference document: {ref_name}).",
                       evidence=[Evidence(ref["doc"].doc_id, ref["page"], ref["bbox"], ref["field"], ref["raw"], "reference value", "field"),
                                 Evidence(v["doc"].doc_id, v["page"], v["bbox"], v["field"], v["raw"], "conflicting value", "field")],
                       verification="Ask the applicant to explain the difference; verify with the issuer of the reference document.",
                       rule=f"X-{row['attr']}",
                       signals={"attr": row["attr"], "fields": [v["field"]], "doc": v["doc"].doc_id,
                                "ref_doc": ref["doc"].doc_id, "ref_value": ref["value"], "value": v["value"]})
        matrix.append({
            "attribute": row["label"], "kind": row["kind"], "reference": TYPE_LABEL[ref["doc"].doc_type],
            "values": [{"doc_id": v["doc"].doc_id, "doc_type": TYPE_LABEL[v["doc"].doc_type], "raw": v["raw"],
                        "match": v["match"], "score": v["score"], "bbox": v["bbox"], "page": v["page"]} for v in vals],
        })
    # temporal consistency: payslip month vs bank salary credit month
    by_type = {d.doc_type: d for d in docs}
    sl, bk = by_type.get("salary_slip"), by_type.get("bank_statement")
    if sl and bk and "pay_date" in sl.fields:
        r = _bank_salary(bk)
        pd = sl.fields["pay_date"].value
        if r and isinstance(pd, date) and isinstance(r["date"], date) and abs((r["date"] - pd).days) > 5:
            fb.add(title="Salary credit date does not match payslip pay date", category="cross_document",
                   status=INCONSISTENCY, severity="medium", confidence=0.8,
                   explanation=f"Payslip pay date {pd:%d/%m/%Y}; bank salary credit on {r['date']:%d/%m/%Y}.",
                   evidence=[_fev(sl, "pay_date"), Evidence(bk.doc_id, r["page"], r["bbox"], None, r["date_raw"], "salary credit row", "field")],
                   verification="Confirm with employer payroll.", rule="X-paydate")
    return matrix
