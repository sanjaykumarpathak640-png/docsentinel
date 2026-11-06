# DocSentinel — Technical documentation

## 1. Pipeline

```
Document Submission → Classification → OCR & Extraction → Structural Understanding →
Visual Forensic Analysis → Contextual Verification → Cross-Document Correlation →
Anomaly Investigation → Evidence Generation → Investigation Dossier
```

`docsentinel/pipeline.py::Investigation.run()` executes the ten stages in order. It reports progress to the UI or CLI and writes an audit entry at every step. A file that fails to load is recorded (`document_failed`) and skipped; the rest of the investigation continues (**safe failure**).

## 2. Technologies and their roles

| Technology | Role in DocSentinel |
|---|---|
| **Tesseract 5 (LSTM)** via pytesseract | OCR of scanned pages: words, bounding boxes, per-word confidence |
| **PyMuPDF** | PDF page rendering, exact text-layer extraction with font per span, metadata, incremental-save detection |
| **OpenCV / NumPy** | Noise-residual analysis, ELA maps, morphology for box detection, connected components for signatures |
| **Pillow** | Image I/O, JPEG recompression for ELA, crops and annotations |
| **RapidFuzz** | Fuzzy label matching (robust to OCR noise) and entity matching across documents |
| **ReportLab** | Investigation dossier PDF |
| **Streamlit** | Investigation console (upload, progress, evidence exploration, analyst review) |
| **Claude API (optional)** | Narrative summary written strictly from the structured findings |

No models are trained in this prototype. All detectors are deterministic and explainable, so every number in the dossier can be reproduced.

## 3. Data model (`models.py`)

- `Word(text, bbox, conf, font, size)` → `Segment` (a run of words separated by wide gaps) → rows on a `Page`
- `ExtractedField(name, value, raw, conf, page, bbox, label_bbox)`: normalised value plus the text as read, with location
- `Document`: hash, type and confidence, fields, tables, metadata, structure report, artefacts
- `Evidence(doc_id, page, bbox, field, value, note, kind, crop_path)`
- `Finding(id, title, category, status, severity, confidence, explanation, evidence[], verification, rule, related[], signals, review)`

Coordinates are page pixels at 150 dpi. PDF text-layer coordinates are scaled from points (×150/72), so every finding uses one coordinate system.

## 4. Methods

### 4.1 Classification
For each supported type, the classifier computes the fraction of distinctive phrases present. Confidence combines the best score with the margin over the runner-up. Below 0.34 the document is `unknown`, a structural observation is raised, and type-specific rules are skipped.

### 4.2 Layout and extraction
1. Words are clustered into visual rows by vertical overlap.
2. Each row is split into **segments** where the horizontal gap exceeds max(28 px, 1.25 × median word height). Labels, values and table cells become separate segments.
3. For each schema field, a segment matching a label alias (RapidFuzz ratio ≥ 88) is paired with the text after its colon, or with the next segment.
4. Values are normalised (amounts, dd/mm/yyyy dates, names, IDs). Invalid dates are kept as `INVALID:` for the contextual check.
5. Bank tables: the header row (`Debit / Credit / Balance`) defines column centres, and each amount is assigned to the nearest column.

### 4.3 Structural understanding
Expected-field schema per type → **missing** fields; same field found twice → **duplicates**; OCR confidence < 60 → **low confidence**; values sharing a left edge → **value columns** (used by the glyph-size check).

### 4.4 Visual forensics
| ID | Detector | Principle |
|---|---|---|
| V1 | **Noise-residual consistency** | Residual = image − Gaussian blur (σ = 1.2). The standard deviation of the residual is measured in 16×16 blocks, only on flat (non-text) pixels. Scanned paper carries uniform sensor noise, so blocks below 0.42 × the page median are flagged and grouped into regions (≥ 6 blocks). Each region is classified as *image* or *text-area* and linked to the field on the same row. |
| V2 | **Error Level Analysis** | Re-save at JPEG q = 90 and compare. Areas with a different compression history respond differently. Used as a supporting signal and a heat-map. |
| V3 | **Glyph-size outlier** | For numeric values sharing a value column (≥ 3), the "core" character height is measured from the horizontal ink projection (rows ≥ 30 % of peak, ignoring commas and slashes). A deviation of ≥ 7 % from the column median suggests the value was typed separately. |
| V4 | **Signature analysis** | Coloured-ink mask → dilated connected components with stroke density < 0.22 (handwriting, not filled shapes). The designated area is a ruled box near the "Signature" label (morphological line detection) or the area below the label. Placement = inside / outside / missing. Signatures on two documents are compared by normalised shape correlation. |
| D1 | **PDF font census** | Words in a font family used by < 10 % of the text and different from the dominant family are flagged and linked to the field they overlap. |
| D2 | **PDF metadata** | Producer is editing software while creator is not; modification date after creation date; more than one `%%EOF` marker (incremental save). |

### 4.5 Contextual verification (within one document)
- C1 Basic + HRA + Special = Gross · C2 PF + PT + TDS = Total deductions · **C3 Gross − Deductions = Net pay**
- C4 Bank running balance per row · **C5 Closing balance = last running balance**
- C6 Valid calendar dates · C7 Plausible age (18–85) at application / pay date

Confidence of a data finding = 0.95 × (lowest OCR confidence of the fields involved / 100), so OCR uncertainty propagates.

### 4.6 Cross-document correlation
The entity matrix compares each attribute against a reference source:

| Attribute | Sources | Reference | Match rule |
|---|---|---|---|
| Name | ID, payslip, application, bank | ID card | token-sort ratio ≥ 95 |
| Date of birth | ID, application | ID card | exact |
| ID number | ID, application | ID card | exact |
| Address | ID, application, bank | ID card | token-sort ratio ≥ 90 |
| Employer | payslip letterhead, application, bank salary narration | payslip | token overlap ≥ 60 % (stop-words removed) |
| Monthly income | application, payslip net, bank salary credit | bank statement | within 2 % |
| Pay date | payslip vs bank salary credit date | — | within 5 days |

### 4.7 Reasoning engine (`reasoning.py`)
1. **Evidence graph.** Each finding is keyed to the (document, field) pairs it concerns. Document-level signals such as PDF metadata attach to every suspicious field of that document.
2. **Relations.** Findings on the same key are cross-linked (`related`).
3. **Convergence.** When a key has both visual/digital and data-consistency findings (or ≥ 3 findings), a **Potential manipulation** hypothesis is raised. Combined confidence = 1 − Π(1 − 0.8·cᵢ), capped at 0.97.
4. **Likely original value.** Candidate values from recomputation (e.g. Gross − Deductions) and from reference documents are grouped. The value most independent sources agree on is reported.
5. **Corroboration discount.** If a claim is "supported" only by a value that is itself under suspicion, the engine says so explicitly and does not treat it as corroboration.
6. **Review priority.** Per document: 1 − Π(1 − 0.6·w), where w = status weight × severity weight × confidence. HIGH ≥ 0.6, MEDIUM ≥ 0.3. The case is HIGH if any potential-manipulation hypothesis exists.
7. **Optional LLM narrative.** Finding titles and explanations only; the prompt forbids new facts and fraud verdicts.

### 4.8 Evidence, dossier and audit
- Every evidence item with a bounding box gets a crop with a coloured outline. Each page gets an annotated image with finding IDs.
- The dossier contains the required sections 7.1–7.6 plus Appendix A (methodology) and Appendix B (audit trail with chain verification).
- The audit log is JSON-lines. Each entry holds `prev_hash` and its own SHA-256, so editing or deleting an entry breaks `verify()`. Logged events: case opened, document ingested (with file hash), classified, extracted, finding recorded, analyst review, dossier generated (with PDF hash), investigation completed.

## 5. Adding a new document type
1. Add keywords in `extract.TYPE_KEYWORDS` and a field schema in `extract.SCHEMA`.
2. Add arithmetic or logic rules in `findings.contextual_findings`.
3. Add cross-document attributes in `findings.ATTRS`.

Visual and digital forensics are template-independent and apply automatically.
