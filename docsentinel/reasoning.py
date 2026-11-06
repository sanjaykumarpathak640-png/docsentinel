"""Stage 8 - Anomaly investigation / contextual reasoning.

The reasoning engine works on the evidence graph produced by the detectors:

1. Every finding is attached to the (document, field) it concerns.
2. Findings that concern the same field are linked as related.
3. When *independent* kinds of signal converge on the same field (e.g. a
   visual overwrite trace + an arithmetic break + a cross-document conflict),
   a correlated POTENTIAL_MANIPULATION hypothesis is raised, with a combined
   confidence and an explanation that lists each supporting signal.
4. The engine estimates which value is most likely original by looking for
   values that independent sources agree on, and discounts corroboration that
   comes from a source which is itself under suspicion.
5. A review priority is computed per document and for the case. The engine
   never labels anything as fraud; it ranks what a human should look at.

An optional LLM (Claude, via ANTHROPIC_API_KEY) can rewrite the deterministic
summary into a narrative. It receives only the structured findings, is told
not to add facts, and its output is labelled as AI-generated.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .extract import FIELD_LABEL, TYPE_LABEL
from .models import INCONSISTENCY, OBSERVATION, POTENTIAL_MANIPULATION, Evidence

KIND_OF = {"visual": "visual", "digital": "visual", "contextual": "data", "cross_document": "data",
           "structural": "structure"}
STATUS_W = {POTENTIAL_MANIPULATION: 1.0, INCONSISTENCY: 0.75, OBSERVATION: 0.45}
SEV_W = {"high": 1.0, "medium": 0.7, "low": 0.4}


def _keys(f):
    """(doc_id, field) keys a finding refers to."""
    fields = f.signals.get("fields") or []
    if f.category == "cross_document":
        return [(f.signals.get("doc"), x) for x in fields]
    doc = f.evidence[0].doc_id if f.evidence else None
    return [(doc, x) for x in fields]


def correlate(fb, docs) -> list:
    findings = list(fb.items)
    doc_by_id = {d.doc_id: d for d in docs}
    by_key = {}
    for f in findings:
        for k in _keys(f):
            by_key.setdefault(k, []).append(f)
    # doc-level digital signals (metadata) support fields of that doc
    doc_level = {}
    for f in findings:
        if f.signals.get("doc_level") and f.evidence:
            doc_level.setdefault(f.evidence[0].doc_id, []).append(f)

    # link related findings
    for k, fs in by_key.items():
        for f in fs:
            for g in fs + doc_level.get(k[0], []):
                if g is not f and g.id not in f.related:
                    f.related.append(g.id)

    suspicious_keys = set()
    hypotheses = []
    for (doc_id, fname), fs in sorted(by_key.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        kinds = {KIND_OF.get(f.category) for f in fs}
        support = fs + doc_level.get(doc_id, [])
        if not ({"visual", "data"} <= kinds or len(fs) >= 3):
            continue
        doc = doc_by_id.get(doc_id)
        if not doc:
            continue
        suspicious_keys.add((doc_id, fname))
        p_clean = 1.0
        for f in support:
            p_clean *= (1 - 0.8 * f.confidence)
        conf = round(min(0.97, 1 - p_clean), 2)
        stated = doc.fields[fname].raw if fname in doc.fields else "?"
        lines = [f"- [{f.id}] {f.title}" for f in support]
        hypotheses.append({
            "doc": doc, "field": fname, "stated": stated, "support": support, "conf": conf, "lines": lines,
        })

    # likely-original value estimation, discounting suspicious corroboration
    for h in hypotheses:
        candidates = []
        for f in h["support"]:
            s = f.signals
            if "expected" in s:
                candidates.append((s["expected"], f"recomputed from components ({f.id})"))
            if f.category == "cross_document" and "ref_value" in s:
                candidates.append((s["ref_value"], f"{TYPE_LABEL.get(doc_by_id[s['ref_doc']].doc_type)} ({f.id})"))
        h["candidates"] = candidates
        vals = {}
        for v, src in candidates:
            if isinstance(v, (int, float)):
                vals.setdefault(round(v, -1), []).append(src)
        h["likely_original"] = None
        if vals:
            best = max(vals.items(), key=lambda kv: len(kv[1]))
            h["likely_original"] = (best[0], best[1])

    notes = []
    hyp_findings = []
    for h in hypotheses:
        doc, fname = h["doc"], h["field"]
        tl = TYPE_LABEL.get(doc.doc_type, doc.doc_type)
        fl = FIELD_LABEL.get(fname, fname)
        lo = h["likely_original"]
        orig_txt = ""
        if lo:
            orig_txt = (f" Independent sources point to {lo[0]:,.0f} as the consistent value "
                        f"({'; '.join(lo[1])}), whereas the document states {h['stated']}.")
        n_vis = sum(1 for f in h["support"] if KIND_OF.get(f.category) == "visual")
        n_dat = sum(1 for f in h["support"] if KIND_OF.get(f.category) == "data")
        expl = (f"{len(h['support'])} findings from {'independent ' if n_vis and n_dat else ''}visual/digital "
                f"({n_vis}) and data-consistency ({n_dat}) checks all concern the same field. Visual traces show "
                f"how it may have been changed; data conflicts show that the value disagrees with the rest of "
                f"the submission. Converging, independent signals are much stronger than any single one.{orig_txt}\n"
                + "\n".join(h["lines"]))
        ev = [Evidence(doc.doc_id, doc.fields[fname].page, doc.fields[fname].bbox, fname, h["stated"],
                       "field under investigation", "field")] if fname in doc.fields else []
        for f in h["support"]:
            ev.extend(e for e in f.evidence if e.kind in ("region", "metadata") and e.doc_id == doc.doc_id)
        hf = fb.add(title=f"{tl}: '{fl}' shows converging signs of alteration (stated value {h['stated']})",
                    category="correlated", status=POTENTIAL_MANIPULATION, severity="high", confidence=h["conf"],
                    explanation=expl, evidence=ev,
                    verification=f"Treat '{fl}' as unverified. Obtain the original from the issuer"
                                 f"{' and confirm whether ' + format(lo[0], ',.0f') + ' is correct' if lo else ''}. "
                                 f"This is a hypothesis for human review, not a determination of fraud.",
                    rule="R1-convergence", related=[f.id for f in h["support"]],
                    signals={"fields": [fname], "doc": doc.doc_id,
                             "likely_original": lo[0] if lo else None})
        for f in h["support"]:
            if hf.id not in f.related:
                f.related.append(hf.id)
        hyp_findings.append(hf)

    # discount corroboration that comes from a suspicious source
    income_rows = [f for f in fb.items if f.category == "cross_document" and f.signals.get("attr") == "income"]
    if income_rows:
        app = next((d for d in docs if d.doc_type == "loan_application"), None)
        slip = next((d for d in docs if d.doc_type == "salary_slip"), None)
        if app and slip and "income" in app.fields and "net_pay" in slip.fields:
            a, s = app.fields["income"].value, slip.fields["net_pay"].value
            if a and s and abs(a - s) / max(a, s) <= 0.02 and (slip.doc_id, "net_pay") in suspicious_keys:
                notes.append(f"The applicant's stated income ({app.fields['income'].raw}) agrees with the payslip Net Pay "
                             f"({slip.fields['net_pay'].raw}), but that payslip value is itself under suspicion, so this "
                             f"agreement is not treated as independent corroboration.")
    return notes


def priority(findings, docs) -> dict:
    per_doc = {d.doc_id: 1.0 for d in docs}
    for f in findings:
        w = STATUS_W[f.status] * SEV_W[f.severity] * f.confidence
        ids = {e.doc_id for e in f.evidence if e.doc_id in per_doc}
        for i in ids:
            per_doc[i] *= (1 - 0.6 * w)
    out = {}
    for d, p in per_doc.items():
        s = round(1 - p, 2)
        out[d] = {"score": s, "level": "HIGH" if s >= 0.6 else ("MEDIUM" if s >= 0.3 else "LOW")}
    case = max([v["score"] for v in out.values()] + [0])
    n_pm = sum(1 for f in findings if f.status == POTENTIAL_MANIPULATION)
    level = "HIGH" if (case >= 0.6 or n_pm) else ("MEDIUM" if case >= 0.3 else "LOW")
    return {"documents": out, "case_score": case, "case_level": level}


def summary_text(case) -> str:
    docs, findings, pr = case["docs"], case["findings"], case["priority"]
    n = {s: sum(1 for f in findings if f.status == s) for s in (POTENTIAL_MANIPULATION, INCONSISTENCY, OBSERVATION)}
    parts = [f"{len(docs)} documents were examined ({', '.join(TYPE_LABEL.get(d.doc_type, d.doc_type) for d in docs)}). "
             f"The system recorded {n[POTENTIAL_MANIPULATION]} potential manipulation hypotheses, {n[INCONSISTENCY]} "
             f"detected inconsistencies and {n[OBSERVATION]} observations. Review priority: {pr['case_level']}."]
    pm = [f for f in findings if f.status == POTENTIAL_MANIPULATION]
    if pm:
        parts.append("Fields with converging evidence of alteration: " +
                     "; ".join(f.title.split(":")[0] + " - " + f.title.split("'")[1] for f in pm) + ".")
    inc = [f for f in findings if f.status == INCONSISTENCY and f.category == "cross_document"]
    if inc:
        parts.append("Cross-document conflicts: " + "; ".join(f.title for f in inc[:5]) + ".")
    parts.extend(case.get("reasoning_notes", []))
    if not pm and not inc:
        parts.append("No converging signs of alteration and no cross-document conflicts were found. This does not "
                     "prove authenticity; it means the checks implemented here found nothing to escalate.")
    parts.append("All findings are indicators for human review. None of them is a determination of fraud.")
    return " ".join(parts)


def llm_narrative(case) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.environ.get("DOCSENTINEL_LLM_MODEL", "claude-sonnet-5-5")
    payload = [{"id": f.id, "title": f.title, "status": f.status, "severity": f.severity,
                "confidence": f.confidence, "explanation": f.explanation[:600]} for f in case["findings"]]
    prompt = ("You are assisting a document-fraud investigator. Using ONLY the structured findings below, write a "
              "concise investigation summary (max 180 words) for the dossier. Do not add facts, numbers or "
              "conclusions that are not in the findings. Never say fraud is confirmed; describe items as "
              "requiring verification. Cite finding IDs in brackets.\n\n" + json.dumps(payload, default=str))
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": model, "max_tokens": 500,
                         "messages": [{"role": "user", "content": prompt}]}).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read())
        return "".join(b.get("text", "") for b in data.get("content", [])).strip() or None
    except Exception as e:  # network / auth failure must never break the investigation
        return f"[LLM narrative unavailable: {type(e).__name__}] "
