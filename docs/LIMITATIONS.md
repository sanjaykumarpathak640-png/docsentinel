# Capabilities, limitations and assumptions

## Capability matrix

| Capability (problem statement) | Status | Notes |
|---|---|---|
| Document ingestion: images, digital PDFs, multiple documents per investigation | ✅ Implemented | JPG, PNG, TIFF, BMP, WebP, PDF. SHA-256 per file |
| Scanned PDFs (no text layer) | ✅ Implemented | Falls back to OCR automatically |
| Document classification | ✅ Implemented | 4 types: identity card, salary slip, loan application, bank statement |
| OCR of printed text, field-level confidence and location | ✅ Implemented | Tesseract 5 |
| Structured representation (fields, tables) | ✅ Implemented | JSON + UI + dossier |
| Missing / duplicated / misplaced information | ✅ Implemented | Misplacement covered via signature placement and column alignment |
| Overwritten fields / pasted patches | ✅ Implemented | Noise residual + ELA |
| Font / size inconsistency | ✅ Implemented | Glyph-size outliers (scans); font census (digital PDFs) |
| Image replacement (photo) | ✅ Implemented | Noise residual on image regions |
| Signature detection and placement | ✅ Implemented | Coloured ink only |
| Signature comparison across documents | 🟡 Partial | Coarse shape correlation; not handwriting verification |
| Within-document contextual checks | ✅ Implemented | Payslip arithmetic, bank balances, dates, age |
| Cross-document correlation | ✅ Implemented | Name, DOB, ID, address, employer, income, pay date |
| Evidence mapping with original locations | ✅ Implemented | bbox on every evidence item, crops, click-to-trace |
| Distinguish observation / inconsistency / potential manipulation | ✅ Implemented | 3-level status taxonomy |
| Investigation dossier (7.1–7.6) | ✅ Implemented | PDF + JSON |
| Audit trail, investigation history | ✅ Implemented | Hash-chained JSONL per case |
| Human oversight | ✅ Implemented | Analyst decisions recorded and included in dossier |
| Optional LLM explanation | 🟡 Partial | Works with an API key; offline deterministic summary otherwise |
| Handwritten text recognition | ⏳ Planned | e.g. TrOCR for handwritten fields |
| Multilingual documents | ⏳ Planned | Tesseract language packs are installed (e.g. `hin`) but layouts are not tested |
| Learned manipulation localisation (deep models) | ⏳ Planned | e.g. TruFor / CAT-Net style models |
| Copy-move detection inside one page | ⏳ Planned | |
| Multi-page documents | 🟡 Partial | All pages are ingested and OCR'd; forensic detectors currently analyse page 1 |
| Video / camera-captured documents with perspective | ❌ Unsupported | Needs dewarping |

## Assumptions
- Documents in one investigation belong to the same person and the same application.
- The identity card is the reference for identity attributes and the bank statement for income. If a reference document is itself manipulated, the comparison is weaker. This is why visual and digital checks run on every document.
- Scanned documents carry sensor noise. Noise analysis is the main overwrite detector for scans.
- Amounts are in one currency; dates are dd/mm/yyyy.

## Known limitations and potential false positives
| Situation | Effect | Mitigation |
|---|---|---|
| OCR misreads a digit | False arithmetic or cross-doc inconsistency | Confidence scaled by OCR conf; crop shown for manual reading |
| Born-digital images (no noise) or heavily denoised scans | Noise detector less sensitive, or flags large areas | Region-size threshold; ELA and data checks still apply |
| Legitimate stamps, stickers, or white-out by the issuer | Flagged as clean region | Reported as **Observation** only unless data checks also fail |
| Different but legitimate font sizes in a column | Glyph-size observation | Observation only; needs ≥ 3 values in the column |
| Address changed legitimately | Address inconsistency | Severity reduced for high-similarity text; verification step suggests explanation |
| PDF re-saved by a legitimate tool | Metadata observation | Metadata is supporting evidence only |
| Forger adds matching noise and uses the exact font | V1/V3 may miss it | Contextual and cross-document checks remain |
| Black-ink signatures | Not detected | Planned: stroke-texture detector |

## Dataset
All demonstration documents are synthetic (`scripts/generate_samples.py`): a fictional person, employer, bank and lender, with every page marked *SYNTHETIC SAMPLE*. Ground truth for the tampered case is in `samples/case_tampered/MANIFEST.md`.

## Not a fraud detector
DocSentinel ranks what a human reviewer should look at and explains why. It never confirms fraud, and a LOW priority result does not prove a document is authentic.
