"""DocSentinel - Streamlit investigation console.

Run:  streamlit run app.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import ImageDraw

from docsentinel.extract import FIELD_LABEL, TYPE_LABEL
from docsentinel.models import INCONSISTENCY, OBSERVATION, POTENTIAL_MANIPULATION, STATUS_LABEL
from docsentinel.pipeline import STAGES, Investigation

ROOT = Path(__file__).parent
SAMPLES = ROOT / "samples"
OUTPUT = ROOT / "output"

st.set_page_config(page_title="DocSentinel - Document Forensics", page_icon="🛡️", layout="wide")

COL = {POTENTIAL_MANIPULATION: "#C81E1E", INCONSISTENCY: "#D97706", OBSERVATION: "#1D6FD8"}
LVL = {"HIGH": "#C81E1E", "MEDIUM": "#D97706", "LOW": "#15803D"}

st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
.ds-badge {display:inline-block;padding:2px 10px;border-radius:12px;color:#fff;font-size:0.78rem;font-weight:600;}
.ds-kpi {border:1px solid #e4e7ec;border-radius:10px;padding:12px 14px;background:#fafbfc;}
.ds-kpi .v {font-size:1.9rem;font-weight:700;line-height:1.1;}
.ds-kpi .l {font-size:0.78rem;color:#5c6370;}
.ds-stage {font-size:0.85rem;padding:2px 0;}
</style>""", unsafe_allow_html=True)


def badge(text, color):
    return f'<span class="ds-badge" style="background:{color}">{text}</span>'


def kpi(col, value, label, color="#14213D"):
    col.markdown(f'<div class="ds-kpi"><div class="v" style="color:{color}">{value}</div><div class="l">{label}</div></div>',
                 unsafe_allow_html=True)


def highlight(doc, page, bbox, color=(220, 30, 40), zoom=True):
    img = doc.pages[page].image.copy()
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = [int(v) for v in bbox]
    d.rectangle([x0 - 5, y0 - 5, x1 + 5, y1 + 5], outline=color, width=6)
    if zoom:
        pad = 220
        img = img.crop((max(0, x0 - pad * 2), max(0, y0 - pad), min(img.width, x1 + pad * 2), min(img.height, y1 + pad)))
    return img


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("## 🛡️ DocSentinel")
    st.caption("AI-powered document forensics & contextual intelligence")
    analyst = st.text_input("Analyst name", value="analyst")
    source = st.radio("Documents", ["Demo case: tampered", "Demo case: genuine", "Upload my own"], index=0)
    files = []
    if source == "Upload my own":
        ups = st.file_uploader("Upload scanned images or PDFs (one investigation = all related documents)",
                               type=["jpg", "jpeg", "png", "pdf", "tif", "tiff", "bmp", "webp"], accept_multiple_files=True)
        if ups:
            tmp = Path(tempfile.mkdtemp(prefix="ds_upload_"))
            for u in ups:
                p = tmp / u.name
                p.write_bytes(u.getbuffer())
                files.append(p)
    else:
        case_dir = SAMPLES / ("case_tampered" if "tampered" in source else "case_genuine")
        files = sorted(p for p in case_dir.iterdir() if p.suffix.lower() in (".jpg", ".png", ".pdf"))
        st.caption("Synthetic sample documents: " + ", ".join(f.name for f in files))
    run = st.button("▶ Run investigation", type="primary", width="stretch", disabled=not files)
    st.divider()
    st.caption("All findings are indicators for human review - never a determination of fraud. "
               "Use only authorised documents.")

if run:
    inv = Investigation(files, OUTPUT, analyst=analyst)
    with st.status("Running investigation…", expanded=True) as status:
        lines = st.empty()
        done = []

        def progress(i, name, msg=""):
            done.append(name)
            lines.markdown("".join(f'<div class="ds-stage">✅ {n}</div>' for n in done[:-1]) +
                           f'<div class="ds-stage">⏳ <b>{name}</b></div>', unsafe_allow_html=True)
        inv.run(progress=progress)
        lines.markdown("".join(f'<div class="ds-stage">✅ {n}</div>' for n in STAGES), unsafe_allow_html=True)
        status.update(label=f"Investigation {inv.case_id} complete", state="complete", expanded=False)
    st.session_state["inv"] = inv

inv: Investigation | None = st.session_state.get("inv")

if not inv:
    st.title("DocSentinel")
    st.markdown("#### Beyond OCR: investigate whether document information is *authentic, consistent and reliable*.")
    st.markdown("""
**Pipeline:** Document submission → Classification → OCR & extraction → Structural understanding → Visual forensic
analysis → Contextual verification → Cross-document correlation → Anomaly investigation → Evidence generation →
Investigation dossier

Choose a demo case in the sidebar (or upload your own documents) and press **Run investigation**.
""")
    c1, c2 = st.columns(2)
    c1.info("**Demo case: tampered** - identity card, salary slip, loan application and bank statement with six "
            "documented manipulations (see `samples/case_tampered/MANIFEST.md`).")
    c2.success("**Demo case: genuine** - the same four documents without manipulation. Use it to show the "
               "false-positive behaviour.")
    st.stop()

case = inv.case
docs, findings, pr = case["docs"], case["findings"], case["priority"]
doc_by_id = {d.doc_id: d for d in docs}

# ------------------------------------------------------------------ header
st.markdown(f"### Investigation `{inv.case_id}`  {badge('Review priority: ' + pr['case_level'], LVL[pr['case_level']])}",
            unsafe_allow_html=True)
n = {s: sum(1 for f in findings if f.status == s) for s in (POTENTIAL_MANIPULATION, INCONSISTENCY, OBSERVATION)}
c = st.columns(5)
kpi(c[0], len(docs), "documents")
kpi(c[1], n[POTENTIAL_MANIPULATION], "potential manipulation", COL[POTENTIAL_MANIPULATION])
kpi(c[2], n[INCONSISTENCY], "detected inconsistencies", COL[INCONSISTENCY])
kpi(c[3], n[OBSERVATION], "observations", COL[OBSERVATION])
kpi(c[4], f"{pr['case_score']:.0%}", "review-priority score", LVL[pr["case_level"]])

VIEWS = ["📋 Overview", "🔤 Extraction", "🔬 Visual forensics", "🔗 Cross-document", "🧭 Findings & evidence",
         "📄 Dossier & audit"]
# segmented navigation keeps the selected view across reruns (st.tabs resets to the first tab)
view = st.segmented_control("View", VIEWS, default=VIEWS[0], key="view", label_visibility="collapsed") or VIEWS[0]
st.divider()

# ------------------------------------------------------------------ overview
if view == VIEWS[0]:
    st.markdown("#### Investigation summary")
    st.write(case["summary"])
    if case.get("llm_summary"):
        st.markdown("**AI-generated narrative** (grounded on findings; verify against evidence)")
        st.info(case["llm_summary"])
    if case.get("errors"):
        st.error("Some files could not be processed (recorded in audit trail): " +
                 "; ".join(f"{e['file']}: {e['error']}" for e in case["errors"]))
    st.markdown("#### Documents")
    st.dataframe(pd.DataFrame([{
        "ID": d.doc_id, "File": d.filename, "Type": TYPE_LABEL.get(d.doc_type), "Type conf.": f"{d.type_conf:.0%}",
        "Source": "scanned → OCR" if d.pages[0].source == "ocr" else "digital PDF text layer",
        "Fields": len(d.fields), "Completeness": f"{d.structure.get('completeness', 0):.0%}",
        "Priority": f"{pr['documents'][d.doc_id]['level']} ({pr['documents'][d.doc_id]['score']})",
        "SHA-256": d.sha256[:20] + "…"} for d in docs]), hide_index=True, width="stretch")
    st.markdown("#### Annotated documents")
    cols = st.columns(len(docs))
    for col, d in zip(cols, docs):
        ann = d.artefacts.get("annotated", {}).get(0)
        if ann:
            col.image(ann, caption=f"{d.doc_id} · {TYPE_LABEL.get(d.doc_type)}", width="stretch")
    st.caption("Box colours: red = potential manipulation, orange = inconsistency, blue = observation. Labels are finding IDs.")

# ----------------------------------------------------------------- extraction
if view == VIEWS[1]:
    sel = st.selectbox("Document", [d.doc_id for d in docs], format_func=lambda i: f"{i} · {TYPE_LABEL.get(doc_by_id[i].doc_type)} · {doc_by_id[i].filename}")
    d = doc_by_id[sel]
    l, r = st.columns([1.1, 1])
    with l:
        st.markdown("**Structured representation**")
        rows = [{"Field": FIELD_LABEL.get(k, k), "Value": str(v.value), "As read": v.raw, "Conf. %": v.conf,
                 "Page": v.page + 1, "BBox (x0,y0,x1,y1)": tuple(int(x) for x in v.bbox), "key": k} for k, v in d.fields.items()]
        df = pd.DataFrame(rows)
        st.dataframe(df.drop(columns=["key"]), hide_index=True, width="stretch")
        stc = d.structure
        st.caption(f"Classification scores: {d.type_scores} · Completeness {stc.get('completeness', 0):.0%} · "
                   f"Missing: {', '.join(stc.get('missing', [])) or 'none'} · Duplicates: {', '.join(stc.get('duplicates', {})) or 'none'} · "
                   f"Value columns at x = {stc.get('value_columns')}")
        if d.tables.get("transactions"):
            st.markdown("**Transactions table**")
            st.dataframe(pd.DataFrame([{k: r[k] for k in ("date_raw", "description", "debit", "credit", "balance")}
                                       for r in d.tables["transactions"]]), hide_index=True, width="stretch")
        if d.metadata.get("pdf"):
            with st.expander("PDF metadata"):
                st.json(d.metadata["pdf"])
    with r:
        pick = st.selectbox("Trace a field to its source location", list(d.fields.keys()),
                            format_func=lambda k: f"{FIELD_LABEL.get(k, k)}: {d.fields[k].raw}")
        f = d.fields[pick]
        st.image(highlight(d, f.page, f.bbox, (30, 110, 220), zoom=False), width="stretch",
                 caption=f"{FIELD_LABEL.get(pick, pick)} · page {f.page + 1} · bbox {tuple(int(x) for x in f.bbox)}")

# ----------------------------------------------------------- visual forensics
if view == VIEWS[2]:
    sel = st.selectbox("Document ", [d.doc_id for d in docs], format_func=lambda i: f"{i} · {TYPE_LABEL.get(doc_by_id[i].doc_type)}")
    d = doc_by_id[sel]
    fx = inv.fx[sel]
    c1, c2, c3 = st.columns(3)
    c1.image(d.artefacts.get("annotated", {}).get(0), caption="Findings on page", width="stretch")
    if d.artefacts.get("noise_map"):
        c2.image(d.artefacts["noise_map"], caption=f"Noise-consistency map (page noise {fx['noise'].get('page_noise')}) - bright = abnormally clean", width="stretch")
        c3.image(d.artefacts["ela_map"], caption="Error Level Analysis", width="stretch")
    else:
        c2.info("Digital PDF: pixel-noise analysis does not apply. Text-layer font census and metadata analysis are used instead.")
        if fx.get("pdf_fonts"):
            c2.dataframe(pd.DataFrame([{"text": x["text"], "font": x["font"], "document font": x["dominant"]} for x in fx["pdf_fonts"]]), hide_index=True)
        if d.metadata.get("pdf"):
            c3.json(d.metadata["pdf"])
    vf = [f for f in findings if f.category in ("visual", "digital", "correlated") and any(e.doc_id == sel for e in f.evidence)]
    st.markdown("**Visual / digital findings on this document**")
    for f in vf:
        st.markdown(f"{badge(f.id, COL[f.status])} {f.title} - *{STATUS_LABEL[f.status]}, confidence {f.confidence:.0%}*",
                    unsafe_allow_html=True)
    if not vf:
        st.success("No visual or digital anomalies above threshold.")
    sig = fx.get("signature", {})
    if sig.get("available"):
        st.caption(f"Signature analysis: {len(sig.get('signatures', []))} signature(s) found; placement = {sig.get('placement')} "
                   f"({sig.get('designated_kind', '-')}).")

# -------------------------------------------------------------- cross-doc
if view == VIEWS[3]:
    st.markdown("#### Entity correlation matrix")
    st.caption("Each attribute is compared with a reference source: identity card for identity attributes, bank statement "
               "(independent third-party record) for income.")
    rows = []
    for m in case["matrix"]:
        row = {"Attribute": m["attribute"], "Reference": m["reference"]}
        for v in m["values"]:
            mark = "REF" if v["match"] is None else ("✅" if v["match"] else f"❌ ({v['score']})")
            row[v["doc_type"]] = f"{v['raw']}  {mark}"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows).fillna("-"), hide_index=True, width="stretch")
    for note in case.get("reasoning_notes", []):
        st.warning("🧠 Reasoning: " + note)
    cf = [f for f in findings if f.category == "cross_document"]
    for f in cf:
        with st.expander(f"{f.id} · {f.title}"):
            st.write(f.explanation)
            cols = st.columns(len(f.evidence))
            for col, e in zip(cols, f.evidence):
                dd = doc_by_id[e.doc_id]
                col.image(highlight(dd, e.page, e.bbox, (220, 30, 40) if e.note == "conflicting value" else (21, 128, 61)),
                          caption=f"{e.doc_id} {TYPE_LABEL.get(dd.doc_type)} - {e.note}: {e.value}", width="stretch")

# --------------------------------------------------------------- findings
if view == VIEWS[4]:
    order = {POTENTIAL_MANIPULATION: 0, INCONSISTENCY: 1, OBSERVATION: 2}
    flt = st.multiselect("Status", list(order), default=list(order), format_func=lambda s: STATUS_LABEL[s])
    for f in sorted(findings, key=lambda f: (order[f.status], -f.confidence)):
        if f.status not in flt:
            continue
        reviewed = f" · 👤 {f.review['decision']}" if f.review else ""
        with st.expander(f"{f.id} · {f.title}{reviewed}", expanded=(f.status == POTENTIAL_MANIPULATION)):
            st.markdown(f"{badge(STATUS_LABEL[f.status], COL[f.status])} &nbsp; severity **{f.severity}** · "
                        f"confidence **{f.confidence:.0%}** · category `{f.category}` · rule `{f.rule}`"
                        + (f" · related: {', '.join(f.related)}" if f.related else ""), unsafe_allow_html=True)
            st.markdown(f.explanation.replace("\n", "  \n"))
            ev = [e for e in f.evidence if e.bbox]
            if ev:
                cols = st.columns(min(3, len(ev)))
                for i, e in enumerate(ev[:3]):
                    dd = doc_by_id[e.doc_id]
                    cols[i].image(highlight(dd, e.page, e.bbox, (220, 30, 40)), width="stretch",
                                  caption=f"{e.doc_id} · p{e.page + 1} · {tuple(int(x) for x in e.bbox)} · {e.note}")
            other = [e for e in f.evidence if not e.bbox]
            for e in other:
                st.caption(f"Evidence ({e.kind}): {e.note} {('= ' + str(e.value)) if e.value else ''}")
            st.markdown(f"**What to verify:** {f.verification}")
            st.markdown("**Analyst review** (human oversight - recorded in the audit trail)")
            a, b, c = st.columns([1, 2, 1])
            dec = a.selectbox("Decision", ["Needs more information", "Confirmed by analyst", "Dismissed (false positive)"],
                              key=f"dec_{f.id}")
            note = b.text_input("Note", key=f"note_{f.id}")
            if c.button("Record decision", key=f"btn_{f.id}"):
                inv.record_review(f.id, dec, note, reviewer=analyst)
                st.success("Decision recorded in audit trail.")
                st.rerun()

# ---------------------------------------------------------- dossier & audit
if view == VIEWS[5]:
    l, r = st.columns([1, 1.3])
    with l:
        st.markdown("#### Investigation dossier")
        if st.button("🔄 Regenerate dossier (includes analyst decisions)"):
            inv.make_dossier()
        dossier = Path(case.get("dossier", ""))
        if dossier.exists():
            st.download_button("⬇ Download dossier (PDF)", dossier.read_bytes(), file_name=dossier.name,
                               mime="application/pdf", type="primary", width="stretch")
        js = inv.save_json()
        st.download_button("⬇ Download findings (JSON)", js.read_bytes(), file_name=f"{inv.case_id}.json",
                           mime="application/json", width="stretch")
        st.caption("Dossier sections: 7.1 Document overview · 7.2 Extracted information · 7.3 Contextual analysis · "
                   "7.4 Visual forensic findings · 7.5 Evidence & traceability · 7.6 Investigation summary · "
                   "Appendix: methodology, audit trail.")
    with r:
        st.markdown("#### Audit trail")
        ok, msg = inv.audit.verify()
        (st.success if ok else st.error)(f"Hash chain {'verified' if ok else 'BROKEN'} - {msg}")
        ent = inv.audit.entries()
        st.dataframe(pd.DataFrame([{"#": e["seq"], "time (UTC)": e["ts"][11:23], "actor": e["actor"], "event": e["event"],
                                    "details": json.dumps(e["details"], default=str)[:120], "hash": e["hash"][:12]}
                                   for e in ent]), hide_index=True, width="stretch", height=420)
