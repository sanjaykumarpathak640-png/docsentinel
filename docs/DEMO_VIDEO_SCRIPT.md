# DocSentinel: demo video script (about 4 minutes)

**Recording setup:** Run `streamlit run app.py` and open it in the browser at full screen. Use OBS Studio or Windows Game Bar (Win + Alt + R) to record the screen with your voice. Speak in English, slowly. The judges' checklist items are shown in [brackets] so each one is covered on screen.

---

### 0:00 – 0:20 · Introduction (show PPT slide 1)
> "Hi, I'm Ayush Kumar. This is DocSentinel, an AI-powered document forensics and contextual intelligence system for the DataOps Innovation Hackathon. OCR can read a document, but it cannot tell you whether the information is authentic, consistent or reliable. DocSentinel investigates that."

### 0:20 – 0:45 · Upload documents [ingestion]
In the sidebar, select **Demo case: tampered**.
> "This investigation has four related documents: an identity card, a salary slip, a loan application, all scanned, and a digital bank statement PDF. All of them are synthetic. I'll click Run investigation."

Click **Run investigation**. Let the ten stages tick off on screen.
> "You can see the ten stages: submission, classification, OCR, structure, visual forensics, contextual checks, cross-document correlation, investigation, evidence and dossier."

### 0:45 – 1:05 · Overview
> "Review priority is HIGH: three potential manipulations, five inconsistencies and nine observations. Every document is hashed with SHA-256 at ingestion."

### 1:05 – 1:35 · Extraction tab [classification, OCR, structured representation, traceability]
Open **Extraction**. Show the salary slip table, then choose *Net pay* in "Trace a field".
> "Each document is classified with a confidence score. OCR output becomes structured fields, each with its confidence and a bounding box. Selecting a field highlights exactly where it came from. The bank statement's transaction table is parsed too."

### 1:35 – 2:10 · Visual forensics tab [suspicious regions]
Open **Visual forensics** and choose the salary slip.
> "A scanned page has uniform sensor noise. In the noise map, only one patch lights up: right next to Net Pay. Something was pasted there after scanning. The Net Pay digits are also 15% taller than the other values in the column."

Switch to the **bank statement**.
> "For a digital PDF, pixel noise doesn't apply, so we check the text layer instead. The closing balance is in Times-Roman while the rest is Helvetica, and the metadata shows a PDF editor modified it after creation."

### 2:10 – 2:40 · Cross-document tab [inconsistencies within and across documents]
Open **Cross-document**.
> "The entity matrix compares each attribute against a reference source. The application's date of birth doesn't match the ID card. The claimed income of 95,000 conflicts with the bank's salary credit of 45,200. And notice the reasoning note: the application agrees with the payslip's 95,200, but the payslip value is itself suspect, so the system does not count that agreement as support."

### 2:40 – 3:20 · Findings & evidence tab [relationships, evidence, observation vs manipulation]
Open **Findings & evidence**, expand **F-015**.
> "This is where the findings connect. Four independent signals all point at the same field: the noise patch, the glyph size, the arithmetic break where gross minus deductions is 45,200, and the bank credit. Together they raise a potential-manipulation hypothesis at 97%, with 45,200 as the likely original value. Each piece of evidence links back to its document, page and box."

Scroll to an **Observation** (e.g. the signature outside its box).
> "There are three statuses: observation, detected inconsistency, and potential manipulation. The system never calls anything fraud."

Record a decision on F-015: choose *Confirmed by analyst*, type a short note, click **Record decision**.
> "A human analyst makes the decision, and it is written to the audit trail."

### 3:20 – 3:45 · Dossier & audit tab [dossier, audit trail]
Open **Dossier & audit**. Click **Regenerate dossier**, then **Download dossier**, and open the PDF briefly (cover page → 7.5 evidence page).
> "The investigation dossier has every required section: overview, extracted information, contextual analysis, visual findings, evidence with crops, and the summary with limitations. The audit trail is hash-chained, so editing any entry is detectable."

### 3:45 – 4:05 · Genuine case [false positives, honest limits]
Switch the sidebar to **Demo case: genuine** and run it.
> "Here are the same documents without manipulation. There are zero inconsistencies and the priority is LOW. Known limitations, such as black-ink signatures and handwriting, are documented honestly in the repository."

### 4:05 – 4:15 · Close
> "DocSentinel turns document processing from extraction into evidence-driven investigation. The code, setup instructions and sample dossiers are on GitHub. Thank you."

---
**Tips:** Before recording, run each case once so it loads fast. Use browser zoom at 90% so tables fit on screen. If the video goes over 5 minutes, shorten the Extraction section.
