"""End-to-end investigation pipeline.

Document Submission -> Classification -> OCR & Extraction -> Structural
Understanding -> Visual Forensic Analysis -> Contextual Verification ->
Cross-Document Correlation -> Anomaly Investigation -> Evidence Generation ->
Investigation Dossier
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime
from pathlib import Path

from . import extract, findings as fnd, forensics, reasoning
from .audit import AuditLog
from .evidence import annotate_pages, make_crops
from .ingest import SUPPORTED, load_document

STAGES = [
    "Document submission", "Document classification", "OCR & information extraction",
    "Structural understanding", "Visual forensic analysis", "Contextual verification",
    "Cross-document correlation", "Anomaly investigation", "Evidence generation", "Investigation dossier",
]


def _jsonable(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if isinstance(o, tuple):
        return list(o)
    if isinstance(o, set):
        return sorted(o)
    return str(o)


class Investigation:
    def __init__(self, files, output_root="output", case_id=None, analyst="analyst"):
        self.files = [Path(f) for f in files if Path(f).suffix.lower() in SUPPORTED]
        self.case_id = case_id or f"CASE-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4].upper()}"
        self.outdir = Path(output_root) / self.case_id
        self.outdir.mkdir(parents=True, exist_ok=True)
        (self.outdir / "artefacts").mkdir(exist_ok=True)
        self.audit = AuditLog(self.outdir / "audit_log.jsonl")
        self.analyst = analyst
        self.docs, self.fx, self.findings, self.matrix = [], {}, [], []
        self.case = {}
        self.timings = {}
        self.errors = []

    def run(self, progress=None, generate_dossier=True) -> dict:
        def step(i, msg=""):
            if progress:
                progress(i, STAGES[i], msg)

        self.audit.log("case_opened", case_id=self.case_id, files=[f.name for f in self.files], analyst=self.analyst)
        t0 = time.time()

        # 1 submission + 3 OCR (OCR happens on load for images)
        step(0)
        for i, f in enumerate(sorted(self.files)):
            doc_id = f"DOC-{i + 1:02d}"
            try:
                d = load_document(f, doc_id)
                self.docs.append(d)
                self.audit.log("document_ingested", doc_id=doc_id, filename=f.name, sha256=d.sha256,
                               media_type=d.media_type, pages=len(d.pages), source=d.pages[0].source)
            except Exception as e:  # safe failure: record and continue with the rest
                self.errors.append({"file": f.name, "error": f"{type(e).__name__}: {e}"})
                self.audit.log("document_failed", filename=f.name, error=str(e))
        self.timings["ingest"] = time.time() - t0

        step(1)
        for d in self.docs:
            extract.classify(d)
            self.audit.log("document_classified", doc_id=d.doc_id, doc_type=d.doc_type, confidence=round(d.type_conf, 2))
        step(2)
        for d in self.docs:
            extract.extract_fields(d)
            d.status = "extracted"
            self.audit.log("fields_extracted", doc_id=d.doc_id, n_fields=len(d.fields),
                           mean_conf=round(sum(f.conf for f in d.fields.values()) / max(1, len(d.fields)), 1))
        step(3)
        for d in self.docs:
            extract.analyse_structure(d)
        fb = fnd.FindingBuilder()
        for d in self.docs:
            fnd.structural_findings(fb, d)

        step(4)
        for d in self.docs:
            self.fx[d.doc_id] = forensics.analyse(d, self.outdir / "artefacts")
            fnd.visual_findings(fb, d, self.fx[d.doc_id])
            fnd.digital_findings(fb, d, self.fx[d.doc_id])
            d.status = "analysed"
        fnd.signature_cross_findings(fb, self.docs, self.fx)

        step(5)
        for d in self.docs:
            fnd.contextual_findings(fb, d)
        step(6)
        self.matrix = fnd.crossdoc_findings(fb, self.docs)

        step(7)
        notes = reasoning.correlate(fb, self.docs)
        self.findings = fb.items
        for f in self.findings:
            self.audit.log("finding_recorded", finding_id=f.id, status=f.status, severity=f.severity,
                           confidence=f.confidence, rule=f.rule, title=f.title)

        step(8)
        make_crops(self.findings, self.docs, self.outdir / "evidence")
        annotate_pages(self.findings, self.docs, self.outdir / "annotated")
        pr = reasoning.priority(self.findings, self.docs)
        self.case = {"case_id": self.case_id, "docs": self.docs, "findings": self.findings, "matrix": self.matrix,
                     "priority": pr, "reasoning_notes": notes, "errors": self.errors, "fx": self.fx,
                     "opened": datetime.now().isoformat(timespec="seconds"), "analyst": self.analyst,
                     "outdir": str(self.outdir)}
        self.case["summary"] = reasoning.summary_text(self.case)
        self.case["llm_summary"] = reasoning.llm_narrative(self.case)
        for d in self.docs:
            d.status = "investigated"
        self.save_json()

        step(9)
        if generate_dossier:
            self.make_dossier()
        self.audit.log("investigation_completed", case_level=pr["case_level"], n_findings=len(self.findings),
                       seconds=round(time.time() - t0, 1))
        return self.case

    # --------------------------------------------------------------- review
    def record_review(self, finding_id: str, decision: str, note: str = "", reviewer: str | None = None):
        f = next(x for x in self.findings if x.id == finding_id)
        f.review = {"decision": decision, "note": note, "reviewer": reviewer or self.analyst,
                    "at": datetime.now().isoformat(timespec="seconds")}
        self.audit.log("analyst_review", actor=reviewer or self.analyst, finding_id=finding_id,
                       decision=decision, note=note)
        self.save_json()

    def make_dossier(self) -> Path:
        from .dossier import build_dossier
        path = build_dossier(self.case, self.outdir / f"{self.case_id}_investigation_dossier.pdf", self.audit)
        import hashlib
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        self.audit.log("dossier_generated", path=path.name, sha256=h)
        self.case["dossier"] = str(path)
        return path

    def save_json(self) -> Path:
        out = {
            "case_id": self.case_id, "generated": datetime.now().isoformat(timespec="seconds"),
            "priority": self.case.get("priority"), "summary": self.case.get("summary"),
            "llm_summary": self.case.get("llm_summary"), "reasoning_notes": self.case.get("reasoning_notes"),
            "errors": self.errors,
            "documents": [{**d.summary(),
                           "fields": {k: {"value": v.value, "raw": v.raw, "conf": v.conf, "page": v.page,
                                          "bbox": v.bbox, "label_bbox": v.label_bbox} for k, v in d.fields.items()},
                           "tables": {k: [{kk: vv for kk, vv in r.items() if kk != "cells"} for r in rows]
                                      for k, rows in d.tables.items()},
                           "structure": {k: v for k, v in d.structure.items() if k != "hierarchy"},
                           "metadata": d.metadata, "artefacts": d.artefacts} for d in self.docs],
            "cross_document_matrix": self.matrix,
            "findings": [f.to_dict() for f in self.findings],
        }
        p = self.outdir / "investigation.json"
        p.write_text(json.dumps(out, indent=2, default=_jsonable))
        return p
