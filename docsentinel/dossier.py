"""Stage 10 - Investigation Dossier (PDF) with the sections required by the
problem statement (7.1 - 7.6), plus methodology, limitations and audit trail."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from .extract import FIELD_LABEL, TYPE_LABEL
from .models import INCONSISTENCY, OBSERVATION, POTENTIAL_MANIPULATION, STATUS_LABEL

NAVY = colors.HexColor("#14213D")
ACCENT = colors.HexColor("#E85D04")
GREY = colors.HexColor("#5C6370")
LIGHT = colors.HexColor("#F1F3F6")
STATUS_COL = {POTENTIAL_MANIPULATION: colors.HexColor("#C81E1E"), INCONSISTENCY: colors.HexColor("#D97706"),
              OBSERVATION: colors.HexColor("#1D6FD8")}
LEVEL_COL = {"HIGH": colors.HexColor("#C81E1E"), "MEDIUM": colors.HexColor("#D97706"), "LOW": colors.HexColor("#15803D")}

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=24, textColor=NAVY, alignment=TA_LEFT, leading=28),
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=15, textColor=NAVY, spaceBefore=10, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, textColor=NAVY, spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9, leading=12.5),
    "small": ParagraphStyle("s", parent=ss["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=GREY),
    "cell": ParagraphStyle("c", parent=ss["BodyText"], fontName="Helvetica", fontSize=7.8, leading=9.6),
    "cellb": ParagraphStyle("cb", parent=ss["BodyText"], fontName="Helvetica-Bold", fontSize=7.8, leading=9.6),
}


def P(t, st="body"):
    return Paragraph(str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                     .replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>").replace("\n", "<br/>"), S[st])


def _fmt(v):
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return "-" if v is None else str(v)


def _bbox(b):
    return "-" if not b else "(" + ", ".join(str(int(v)) for v in b) + ")"


def _table(rows, widths, header=True, zebra=True):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 7.8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCD1D9")),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                  ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.8)]
    if zebra:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


def _img(path, max_w, max_h):
    """Embed a down-sampled JPEG copy (keeps the dossier small)."""
    try:
        im = PILImage.open(path).convert("RGB")
    except Exception:
        return P("[image unavailable]", "small")
    w, h = im.size
    s = min(max_w / w, max_h / h)
    target = (max(1, int(w * s * 2.8)), max(1, int(h * s * 2.8)))  # ~200 dpi at print size
    if target[0] < w:
        im = im.resize(target, PILImage.LANCZOS)
    small = Path(path).with_name(Path(path).stem + "_dossier.jpg")
    im.save(small, "JPEG", quality=82)
    return Image(str(small), width=w * s, height=h * s)


def _badge(text, col):
    t = Table([[text]], colWidths=[None])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), col), ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                           ("FONT", (0, 0), (-1, -1), "Helvetica-Bold", 10), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def build_dossier(case, path: Path, audit) -> Path:
    docs, findings, matrix, pr = case["docs"], case["findings"], case["matrix"], case["priority"]
    doc_by_id = {d.doc_id: d for d in docs}
    order = {POTENTIAL_MANIPULATION: 0, INCONSISTENCY: 1, OBSERVATION: 2}
    sev = {"high": 0, "medium": 1, "low": 2}
    fs_sorted = sorted(findings, key=lambda f: (order[f.status], sev[f.severity], -f.confidence))
    W = A4[0] - 30 * mm

    def on_page(c, d):
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(15 * mm, A4[1] - 7.5 * mm, "DocSentinel  |  Investigation Dossier")
        c.setFont("Helvetica", 8)
        c.drawRightString(A4[0] - 15 * mm, A4[1] - 7.5 * mm, f"{case['case_id']}  |  CONFIDENTIAL - for human review")
        c.setFillColor(GREY)
        c.setFont("Helvetica", 7)
        c.drawString(15 * mm, 8 * mm, "Findings are indicators requiring verification, not determinations of fraud. "
                                      "OCR output is not treated as ground truth.")
        c.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {d.page}")
        c.restoreState()

    story = []
    # ------------------------------------------------------------ cover
    story += [Spacer(1, 10 * mm), P("Document Investigation Dossier", "title"),
              P(f"Case <b>{case['case_id']}</b>  ·  generated {datetime.now():%d %b %Y, %H:%M}  ·  analyst: {case.get('analyst', '-')}", "body"),
              Spacer(1, 5 * mm)]
    n = {s: sum(1 for f in findings if f.status == s) for s in order}
    kpi = Table([[f"{len(docs)}", f"{n[POTENTIAL_MANIPULATION]}", f"{n[INCONSISTENCY]}", f"{n[OBSERVATION]}", pr["case_level"]],
                 ["documents", "potential manipulation", "inconsistencies", "observations", "review priority"]],
                colWidths=[W / 5] * 5)
    kpi.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 20), ("FONT", (0, 1), (-1, 1), "Helvetica", 7.5),
                             ("TEXTCOLOR", (0, 1), (-1, 1), GREY), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                             ("TEXTCOLOR", (1, 0), (1, 0), STATUS_COL[POTENTIAL_MANIPULATION]),
                             ("TEXTCOLOR", (2, 0), (2, 0), STATUS_COL[INCONSISTENCY]),
                             ("TEXTCOLOR", (3, 0), (3, 0), STATUS_COL[OBSERVATION]),
                             ("TEXTCOLOR", (4, 0), (4, 0), LEVEL_COL[pr["case_level"]]),
                             ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCD1D9")),
                             ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 6)]))
    story += [kpi, Spacer(1, 5 * mm), P("Executive summary", "h1"), P(case["summary"])]
    if case.get("llm_summary"):
        story += [Spacer(1, 3 * mm), P("<b>AI-generated narrative</b> (LLM, grounded on the findings above; verify against evidence)", "small"),
                  P(case["llm_summary"])]
    story += [Spacer(1, 3 * mm), P("<b>Status definitions.</b> <b>Observation</b>: a visual or technical characteristic was "
                                   "observed; on its own it is not a problem. <b>Detected inconsistency</b>: a verifiable "
                                   "conflict in the data (arithmetic or between documents). <b>Potential manipulation</b>: "
                                   "several independent signals converge on the same field. None of these is a finding of fraud; "
                                   "consequential decisions remain with a human reviewer.", "small")]

    # ------------------------------------------------------ 7.1 overview
    story += [PageBreak(), P("7.1  Document overview", "h1")]
    rows = [["ID", "File", "Type (confidence)", "Source", "Pages", "Status", "Review priority", "SHA-256 (first 16)"]]
    for d in docs:
        p = pr["documents"].get(d.doc_id, {})
        rows.append([d.doc_id, P(d.filename, "cell"), f"{TYPE_LABEL.get(d.doc_type)} ({d.type_conf:.0%})",
                     "scanned (OCR)" if d.pages[0].source == "ocr" else "digital PDF", str(len(d.pages)), d.status,
                     f"{p.get('level')} ({p.get('score')})", d.sha256[:16]])
    story.append(_table(rows, [14 * mm, 34 * mm, 32 * mm, 20 * mm, 10 * mm, 18 * mm, 22 * mm, 30 * mm]))
    if case.get("errors"):
        story += [P("Files that could not be processed (safe failure):", "h2")] + [P(f"{e['file']}: {e['error']}", "small") for e in case["errors"]]
    story.append(P("Full SHA-256 hashes are recorded in the audit trail at ingestion so the analysed files can be "
                   "matched to the originals (ISO/IEC 27037 practice).", "small"))

    # ----------------------------------------------- 7.2 extracted info
    story += [P("7.2  Extracted information", "h1"),
              P("Every value keeps its page and bounding box (x0, y0, x1, y1 in 150-dpi pixels) so it can be traced "
                "to its location in the original document. Confidence is the OCR engine's word confidence; for digital "
                "PDFs the text layer is exact (99).", "small")]
    for d in docs:
        rows = [["Field", "Value (normalised)", "As read", "Conf.", "Page", "Location"]]
        for k, f in d.fields.items():
            rows.append([FIELD_LABEL.get(k, k), P(_fmt(f.value), "cell"), P(f.raw, "cell"), f"{f.conf:.0f}",
                         str(f.page + 1), _bbox(f.bbox)])
        st = d.structure
        block = [P(f"{d.doc_id} · {TYPE_LABEL.get(d.doc_type)} · {d.filename}", "h2"),
                 _table(rows, [34 * mm, 42 * mm, 42 * mm, 12 * mm, 10 * mm, 40 * mm]),
                 P(f"Structure: completeness {st.get('completeness', 0):.0%}; missing: {', '.join(st.get('missing', [])) or 'none'}; "
                   f"duplicated: {', '.join(st.get('duplicates', {})) or 'none'}; value columns at x = {st.get('value_columns')}.", "small")]
        tx = d.tables.get("transactions")
        if tx:
            trows = [["Date", "Description", "Debit", "Credit", "Balance"]] + \
                    [[r["date_raw"], P(r["description"], "cell"), _fmt(r["debit"]), _fmt(r["credit"]), _fmt(r["balance"])] for r in tx]
            block += [Spacer(1, 2 * mm), P("Transactions table (structured)", "small"),
                      _table(trows, [24 * mm, 70 * mm, 28 * mm, 28 * mm, 30 * mm])]
        story += block

    # --------------------------------------------- 7.3 contextual analysis
    story += [PageBreak(), P("7.3  Contextual analysis", "h1"), P("Cross-document entity matrix", "h2"),
              P("Each attribute is compared with a reference source (identity attributes: identity card; income: bank "
                "statement, as an independent third-party record). ✓ = consistent, ✗ = conflict, REF = reference.", "small")]
    rows = [["Attribute", "Reference", "Values found (document: value  → result)"]]
    for m in matrix:
        cells = []
        for v in m["values"]:
            res = "REF" if v["match"] is None else ("OK" if v["match"] else f"CONFLICT (score {v['score']})")
            cells.append(f"{v['doc_id']} {v['doc_type']}: <b>{v['raw']}</b> → {res}")
        rows.append([m["attribute"], m["reference"], Paragraph("<br/>".join(cells), S["cell"])])
    story.append(_table(rows, [30 * mm, 28 * mm, W - 58 * mm]))
    ctx = [f for f in fs_sorted if f.category in ("contextual", "cross_document", "structural")]
    story.append(P("Inconsistencies within and across documents", "h2"))
    story.append(_findings_table(ctx, W) if ctx else P("None detected.", "body"))
    for note in case.get("reasoning_notes", []):
        story.append(P("<b>Reasoning note:</b> " + note, "body"))

    # --------------------------------------------- 7.4 visual forensic
    story += [PageBreak(), P("7.4  Visual forensic findings", "h1")]
    vis = [f for f in fs_sorted if f.category in ("visual", "digital")]
    story.append(_findings_table(vis, W) if vis else P("No visual anomalies above threshold.", "body"))
    story.append(P("Annotated pages and forensic maps", "h2"))
    story.append(P("Left: findings drawn on the page (red = potential manipulation, orange = inconsistency, blue = "
                   "observation). Middle: noise-consistency map (bright = abnormally clean). Right: Error Level Analysis.", "small"))
    for d in docs:
        ann = d.artefacts.get("annotated", {}).get(0)
        cells = [_img(ann, W / 3 - 4, 95 * mm) if ann else P("-")]
        cells.append(_img(d.artefacts["noise_map"], W / 3 - 4, 95 * mm) if d.artefacts.get("noise_map") else P("digital PDF: noise analysis not applicable; text-layer font and metadata analysis used instead", "small"))
        cells.append(_img(d.artefacts["ela_map"], W / 3 - 4, 95 * mm) if d.artefacts.get("ela_map") else P("", "small"))
        t = Table([[P(f"{d.doc_id} · {TYPE_LABEL.get(d.doc_type)}", "cellb"), "", ""], cells], colWidths=[W / 3] * 3)
        t.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [KeepTogether([t, Spacer(1, 3 * mm)])]

    # ------------------------------------------ 7.5 evidence & traceability
    story += [PageBreak(), P("7.5  Evidence and traceability", "h1"),
              P("For each finding: the evidence items, their source document, page and bounding box, and an image "
                "crop of the original region. Related findings are cross-referenced.", "small")]
    for f in fs_sorted:
        head = Table([[f"{f.id}", P(f"<b>{f.title}</b>", "cell"), STATUS_LABEL[f.status],
                       f"{f.severity.upper()} · {f.confidence:.0%}"]],
                     colWidths=[14 * mm, W - 14 * mm - 62 * mm - 26 * mm, 62 * mm, 26 * mm])
        head.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), STATUS_COL[f.status]),
                                  ("TEXTCOLOR", (0, 0), (0, 0), colors.white), ("FONT", (0, 0), (0, 0), "Helvetica-Bold", 8),
                                  ("TEXTCOLOR", (2, 0), (2, 0), STATUS_COL[f.status]), ("FONT", (2, 0), (-1, 0), "Helvetica-Bold", 7.5),
                                  ("BACKGROUND", (1, 0), (-1, 0), LIGHT), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        block = [head, Spacer(1, 1.5 * mm), P(f.explanation, "cell"), Spacer(1, 1.5 * mm)]
        erows = [["Doc", "Page", "Location", "Field / value", "Note", "Crop"]]
        for e in f.evidence[:6]:
            d = doc_by_id.get(e.doc_id)
            erows.append([e.doc_id, str(e.page + 1) if e.bbox else "-", _bbox(e.bbox),
                          P(f"{FIELD_LABEL.get(e.field, e.field)}: {e.value or '-'}" if e.field else
                            (f"value: {e.value}" if e.value else e.kind), "cell"),
                          P(e.note, "cell"), _img(e.crop_path, 48 * mm, 16 * mm) if e.crop_path else "-"])
        block.append(_table(erows, [14 * mm, 10 * mm, 30 * mm, 36 * mm, W - 140 * mm, 50 * mm]))
        extra = f"<b>Verify:</b> {f.verification}  ·  <b>Rule:</b> {f.rule}"
        if f.related:
            extra += f"  ·  <b>Related:</b> {', '.join(f.related)}"
        if f.review:
            extra += f"  ·  <b>Analyst review:</b> {f.review['decision']} by {f.review['reviewer']} ({f.review.get('note') or 'no note'})"
        block += [P(extra, "small"), Spacer(1, 4 * mm)]
        story.append(KeepTogether(block))

    # ------------------------------------------ 7.6 investigation summary
    story += [PageBreak(), P("7.6  Investigation summary", "h1"), P("Identified anomalies (ranked)", "h2")]
    rows = [["ID", "Anomaly", "Status", "Conf."]] + [[f.id, P(f.title, "cell"), STATUS_LABEL[f.status], f"{f.confidence:.0%}"]
                                                    for f in fs_sorted if f.status != OBSERVATION or f.severity != "low"]
    story.append(_table(rows, [14 * mm, W - 14 * mm - 60 * mm - 14 * mm, 60 * mm, 14 * mm]))
    story.append(P("Potential explanations", "h2"))
    pm = [f for f in fs_sorted if f.status == POTENTIAL_MANIPULATION]
    if pm:
        for f in pm:
            lo = f.signals.get("likely_original")
            story.append(P(f"<b>{f.id}</b> - {f.title}. Possible explanations, in the order to rule out: (1) OCR misread "
                           f"of the value (check the crop); (2) a legitimate correction or re-issue by the issuer; (3) "
                           f"alteration after issue. " + (f"Independent sources agree on {lo:,.0f}." if lo else "")))
    else:
        story.append(P("No converging manipulation hypotheses were raised."))
    story.append(P("Areas requiring additional verification", "h2"))
    seen = set()
    for f in fs_sorted:
        if f.status == OBSERVATION and f.severity == "low":
            continue
        if f.verification not in seen:
            seen.add(f.verification)
            story.append(P(f"• {f.verification}  ({f.id})"))
    story.append(P("Investigation limitations", "h2"))
    for l in LIMITATIONS:
        story.append(P("• " + l, "small"))

    # --------------------------------------------- methodology & audit
    story += [PageBreak(), P("Appendix A  Methodology and technologies", "h1")]
    story.append(_table([["Stage", "Technique", "Implementation"]] + [[a, P(b, "cell"), P(c, "cell")] for a, b, c in METHODS],
                        [38 * mm, 70 * mm, W - 108 * mm]))
    story.append(P("Reference frameworks used as guidance (no formal compliance claimed): ISO/IEC 27037, 27041, 27042; "
                   "NIST SP 800-86; OWASP ML Security Top 10.", "small"))
    story += [P("Appendix B  Audit trail", "h1")]
    ok, msg = audit.verify()
    story.append(P(f"Hash-chain integrity: <b>{'VERIFIED' if ok else 'BROKEN'}</b> - {msg}. Each entry stores the SHA-256 of "
                   f"the previous entry; editing any entry breaks the chain.", "body"))
    rows = [["#", "Time (UTC)", "Actor", "Event", "Details", "Hash"]]
    for e in audit.entries():
        det = ", ".join(f"{k}={str(v)[:40]}" for k, v in e["details"].items() if k not in ("title",))
        rows.append([str(e["seq"]), e["ts"][11:23], e["actor"], e["event"], P(det[:160], "cell"), e["hash"][:10]])
    story.append(_table(rows, [8 * mm, 22 * mm, 18 * mm, 30 * mm, W - 98 * mm, 20 * mm]))

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=18 * mm, bottomMargin=15 * mm, title=f"Investigation Dossier {case['case_id']}",
                            author="DocSentinel")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return path


def _findings_table(fs, W):
    rows = [["ID", "Finding", "Status", "Sev.", "Conf.", "Related"]]
    for f in fs:
        rows.append([f.id, P(f.title, "cell"), P(STATUS_LABEL[f.status], "cell"), f.severity, f"{f.confidence:.0%}",
                     P(", ".join(f.related) or "-", "cell")])
    t = _table(rows, [13 * mm, W - 13 * mm - 38 * mm - 12 * mm - 12 * mm - 26 * mm, 38 * mm, 12 * mm, 12 * mm, 26 * mm])
    for i, f in enumerate(fs, start=1):
        t.setStyle(TableStyle([("TEXTCOLOR", (0, i), (0, i), STATUS_COL[f.status]), ("FONT", (0, i), (0, i), "Helvetica-Bold", 7.8)]))
    return t


METHODS = [
    ("Ingestion", "SHA-256 hashing, page rendering at 150 dpi", "Pillow, PyMuPDF"),
    ("Classification", "Keyword-evidence scoring with confidence margin", "Python"),
    ("OCR & extraction", "Tesseract LSTM OCR; row/segment layout grouping; label→value pairing with fuzzy label matching; table parsing by column geometry", "Tesseract 5, pytesseract, RapidFuzz"),
    ("Structure", "Expected-field schema per document type; missing / duplicate / low-confidence detection; value-column alignment", "Python"),
    ("Visual forensics", "Noise-residual consistency (block-wise), Error Level Analysis, glyph-height outliers per value column, coloured-ink signature detection, box detection, signature shape correlation", "OpenCV, NumPy"),
    ("Digital forensics", "PDF text-layer font census; metadata (producer vs creator, modification date, incremental saves)", "PyMuPDF"),
    ("Contextual verification", "Arithmetic rules (payslip totals, bank running balance), date and age logic", "Python rules"),
    ("Cross-document", "Entity matrix with reference sources; fuzzy name/address matching; tolerance-based amount matching; temporal checks", "RapidFuzz"),
    ("Reasoning", "Evidence graph keyed by (document, field); convergence of independent signal types; Bayesian-style confidence combination; likely-original estimation; discounting of suspicious corroboration", "Python"),
    ("Narrative (optional)", "LLM rewrites the deterministic summary using only structured findings", "Claude API (optional)"),
    ("Evidence & audit", "Region crops, annotated pages, hash-chained JSONL audit log, analyst review decisions", "Pillow, hashlib"),
]

LIMITATIONS = [
    "Prototype rules and layouts were developed on the synthetic demonstration dataset; new document templates need schema entries.",
    "Noise-consistency analysis assumes the page was scanned or photographed. Born-digital images have little noise and are analysed with lower sensitivity; a forger who adds matching noise can evade it.",
    "Glyph-size checks need at least three aligned numeric values in a column.",
    "Signature detection currently finds coloured (blue) ink only; black-ink signatures may be missed. Signature comparison is a coarse shape heuristic, not handwriting verification.",
    "Handwritten field recognition is not supported in this version; multilingual OCR is possible through Tesseract language packs but not tested.",
    "Cross-document reference choices (ID card for identity, bank statement for income) are assumptions; a manipulated reference document weakens the comparison, which is why visual and digital checks run on every document.",
    "OCR errors can create false inconsistencies; every data finding is scaled by the OCR confidence of the fields it uses, and crops are provided so a reviewer can read the value directly.",
    "PDF metadata can be altered or legitimately changed; it is used only as supporting evidence.",
]
