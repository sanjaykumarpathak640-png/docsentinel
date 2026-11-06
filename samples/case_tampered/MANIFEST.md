# Tampered case - ground truth (for judges)

All documents are synthetic. These manipulations were introduced on purpose so
the system's detections can be checked against a known answer.

| # | Document | Manipulation | Expected detection |
|---|----------|--------------|--------------------|
| T1 | 01_identity_card.jpg | Photograph region replaced after scanning | Visual: noise/ELA anomaly in photo region |
| T2 | 02_salary_slip.jpg | Net Pay overwritten 45,200 -> 95,200 with a clean patch in a serif font | Visual: overwritten region + font/height outlier; Contextual: Gross - Deductions != Net |
| T3 | 03_loan_application.jpg | Monthly Net Income overwritten 45,200 -> 95,000 | Visual: overwritten region; Cross-doc: income conflicts with bank salary credit |
| T4 | 03_loan_application.jpg | Date of Birth 14/03/1994 (ID card says 14/03/1996) | Cross-doc: DOB mismatch |
| T5 | 03_loan_application.jpg | Signature placed outside the signature box | Visual: signature placement |
| T6 | 04_bank_statement.pdf | Closing balance edited 50,220.00 -> 99,220.00 with a PDF editor | Contextual: running balance mismatch; Visual/digital: font inconsistency + metadata modified after creation |

The genuine case (samples/case_genuine) contains the same documents with none of the above.
