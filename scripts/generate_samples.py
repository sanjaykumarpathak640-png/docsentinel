"""
Generate the DocSentinel demonstration dataset.

All documents are SYNTHETIC. The person, employer, ID numbers and account
numbers are fictional and every page carries a "SYNTHETIC SAMPLE" marker.

Two investigation cases are produced:
  samples/case_genuine/   - four consistent documents (no manipulation)
  samples/case_tampered/  - the same four documents with deliberate,
                            documented manipulations (see MANIFEST.md)

Run:  python scripts/generate_samples.py
"""
from __future__ import annotations

import io
import math
import os
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"

W, H = 1240, 1754  # A4 at 150 dpi
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"


def font(size, bold=False, serif=False):
    candidates = []
    if serif:
        candidates.append("DejaVuSerif-Bold.ttf" if bold else "DejaVuSerif.ttf")
    candidates.append("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    for c in candidates:
        for d in (FONT_DIR, ""):
            try:
                return ImageFont.truetype(os.path.join(d, c), size)
            except OSError:
                continue
    return ImageFont.load_default()


RNG = random.Random(7)

PERSON = {
    "name": "Rohan Verma",
    "dob": "14/03/1996",
    "id_no": "DEMO-4821-7730-15",
    "address": "21 Lake View Road, Bhopal 462001",
    "employer": "Nimbus Softworks Pvt Ltd",
    "emp_id": "NSW-2291",
}
SALARY = {"basic": 30000, "hra": 12000, "special": 10000, "pf": 3600, "ptax": 200, "tds": 3000}
SALARY["gross"] = SALARY["basic"] + SALARY["hra"] + SALARY["special"]          # 52,000
SALARY["ded"] = SALARY["pf"] + SALARY["ptax"] + SALARY["tds"]                  # 6,800
SALARY["net"] = SALARY["gross"] - SALARY["ded"]                                # 45,200


def inr(v, dec=False):
    """Indian digit grouping."""
    s = f"{v:.2f}" if dec else str(int(v))
    if dec:
        whole, frac = s.split(".")
    else:
        whole, frac = s, None
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = ("-" if neg else "") + whole
    return out + ("." + frac if frac else "")


# ----------------------------------------------------------------- helpers
def new_page():
    img = Image.new("RGB", (W, H), (255, 255, 255))
    return img, ImageDraw.Draw(img)


def watermark(img):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((W // 2 - 360, H - 70), "SYNTHETIC SAMPLE - FOR DEMONSTRATION ONLY", font=font(22), fill=(150, 150, 150, 255))
    img.paste(Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB"))


def field(d, x, y, label, value, lw=330, size=28):
    d.text((x, y), f"{label}:", font=font(size, bold=True), fill=(20, 20, 20))
    d.text((x + lw, y), value, font=font(size), fill=(20, 20, 20))


def signature(d, x, y, w=260, h=70, seed=3):
    r = random.Random(seed)
    pts = []
    for i in range(60):
        t = i / 59
        px = x + t * w
        py = y + h / 2 + math.sin(t * 9 + r.random()) * h * 0.35 + r.uniform(-4, 4)
        pts.append((px, py))
    d.line(pts, fill=(15, 30, 110), width=4, joint="curve")
    d.line([(x + 20, y + h - 8), (x + w * 0.8, y + h - 14)], fill=(15, 30, 110), width=3)


def scan(img, seed=1, quality=88):
    """Simulate a scanner: slight blur, sensor noise, paper tone, JPEG."""
    rng = np.random.default_rng(seed)
    a = np.asarray(img.filter(ImageFilter.GaussianBlur(0.6))).astype(np.float32)
    a = a * 0.975 + 2  # paper tone
    a += rng.normal(0, 4.0, a.shape)
    a = np.clip(a, 0, 255).astype(np.uint8)
    out = Image.fromarray(a)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def paste_patch(scanned, box, text, fnt, text_xy_offset=(4, 2), fill=(10, 10, 10)):
    """Tampering primitive: cover a region with a clean patch and re-type text.
    The patch has no scanner noise and uses a different typeface."""
    x0, y0, x1, y1 = box
    patch = Image.new("RGB", (x1 - x0, y1 - y0), (250, 250, 250))
    pd = ImageDraw.Draw(patch)
    pd.text(text_xy_offset, text, font=fnt, fill=fill)
    scanned.paste(patch, (x0, y0))
    return scanned


def save_jpeg(img, path, quality=88):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=quality)


def avatar(size=(220, 270), tone=(205, 170, 140), shirt=(60, 90, 140)):
    img = Image.new("RGB", size, (225, 232, 240))
    d = ImageDraw.Draw(img)
    w, h = size
    d.ellipse([w * 0.3, h * 0.15, w * 0.7, h * 0.55], fill=tone)
    d.ellipse([w * 0.08, h * 0.6, w * 0.92, h * 1.3], fill=shirt)
    return img


# ----------------------------------------------------------- documents
def id_card(person, photo_tone=(205, 170, 140)):
    img, d = new_page()
    d.rectangle([60, 60, W - 60, 760], outline=(30, 60, 120), width=5)
    d.rectangle([60, 60, W - 60, 170], fill=(30, 60, 120))
    d.text((100, 88), "DEMO IDENTITY CARD", font=font(44, bold=True), fill=(255, 255, 255))
    d.text((100, 190), "Issued by: Demo Registration Authority (fictional)", font=font(22), fill=(60, 60, 60))
    img.paste(avatar(tone=photo_tone), (900, 250))
    d.rectangle([898, 248, 1122, 522], outline=(30, 60, 120), width=3)
    y = 260
    for lab, val in [("Name", person["name"]), ("Date of Birth", person["dob"]),
                     ("ID Number", person["id_no"]), ("Gender", "Male")]:
        field(d, 100, y, lab, val, lw=270)
        y += 70
    d.text((100, y), "Address:", font=font(28, bold=True), fill=(20, 20, 20))
    d.text((370, y), person["address"], font=font(28), fill=(20, 20, 20))
    y += 90
    d.text((100, y), "Holder Signature", font=font(22), fill=(80, 80, 80))
    signature(d, 100, y + 30, w=240, h=60, seed=11)
    watermark(img)
    return img


def salary_slip(person, net_override=None):
    img, d = new_page()
    d.text((80, 70), person["employer"], font=font(40, bold=True), fill=(15, 15, 15))
    d.text((80, 125), "4th Floor, Arera Hills, Bhopal (fictional)", font=font(22), fill=(70, 70, 70))
    d.text((80, 190), "SALARY SLIP - SEPTEMBER 2026", font=font(32, bold=True), fill=(15, 15, 15))
    d.line([(80, 245), (W - 80, 245)], fill=(0, 0, 0), width=3)
    y = 280
    for lab, val in [("Employee Name", person["name"]), ("Employee ID", person["emp_id"]),
                     ("Pay Period", "September 2026"), ("Pay Date", "30/09/2026")]:
        field(d, 80, y, lab, val, lw=330)
        y += 60
    y += 30
    d.text((80, y), "EARNINGS", font=font(28, bold=True), fill=(0, 0, 0))
    d.text((680, y), "DEDUCTIONS", font=font(28, bold=True), fill=(0, 0, 0))
    y += 55
    earn = [("Basic", SALARY["basic"]), ("HRA", SALARY["hra"]), ("Special Allowance", SALARY["special"])]
    ded = [("Provident Fund", SALARY["pf"]), ("Professional Tax", SALARY["ptax"]), ("Income Tax", SALARY["tds"])]
    for (el, ev), (dl, dv) in zip(earn, ded):
        d.text((80, y), el, font=font(26), fill=(20, 20, 20))
        d.text((470, y), inr(ev), font=font(26), fill=(20, 20, 20))
        d.text((680, y), dl, font=font(26), fill=(20, 20, 20))
        d.text((1040, y), inr(dv), font=font(26), fill=(20, 20, 20))
        y += 50
    d.line([(80, y + 5), (W - 80, y + 5)], fill=(0, 0, 0), width=2)
    y += 25
    field(d, 80, y, "Gross Earnings", inr(SALARY["gross"]), lw=330)
    y += 60
    field(d, 80, y, "Total Deductions", inr(SALARY["ded"]), lw=330)
    y += 70
    net_y = y
    field(d, 80, y, "Net Pay", inr(SALARY["net"]), lw=330)
    y += 120
    d.text((80, y), "This is a computer generated payslip.", font=font(22), fill=(80, 80, 80))
    d.text((800, y), "Authorised Signatory", font=font(22), fill=(80, 80, 80))
    signature(d, 820, y + 30, w=220, h=60, seed=21)
    watermark(img)
    return img, net_y


def application_form(person, dob=None, income=None, signature_inside=True):
    img, d = new_page()
    d.text((80, 70), "PERSONAL LOAN APPLICATION FORM", font=font(40, bold=True), fill=(15, 15, 15))
    d.text((80, 125), "Demo Finance Ltd (fictional lender)", font=font(22), fill=(70, 70, 70))
    d.line([(80, 170), (W - 80, 170)], fill=(0, 0, 0), width=3)
    y = 210
    rows = [
        ("Applicant Name", person["name"]),
        ("Date of Birth", dob or person["dob"]),
        ("ID Number", person["id_no"]),
        ("Address", person["address"]),
        ("Employer", person["employer"]),
        ("Monthly Net Income", inr(income or SALARY["net"])),
        ("Loan Amount", "3,00,000"),
        ("Loan Tenure", "36 months"),
        ("Application Date", "05/10/2026"),
    ]
    positions = {}
    for lab, val in rows:
        field(d, 80, y, lab, val, lw=380)
        positions[lab] = y
        y += 75
    y += 30
    d.text((80, y), "Declaration: I confirm that the information above is true.", font=font(24), fill=(40, 40, 40))
    y += 70
    box = (80, y + 40, 520, y + 180)
    d.text((80, y), "Applicant Signature", font=font(26, bold=True), fill=(20, 20, 20))
    d.rectangle(box, outline=(0, 0, 0), width=2)
    if signature_inside:
        signature(d, box[0] + 70, box[1] + 35, w=280, h=70, seed=11)
    else:
        signature(d, 760, box[3] + 140, w=280, h=70, seed=11)
    watermark(img)
    return img, positions


def bank_statement_pdf(path, person, closing_override=None):
    """Digital (text-layer) bank statement produced with ReportLab.
    If closing_override is given, the PDF is afterwards edited with PyMuPDF:
    the closing balance is redacted and re-typed in a different font, and the
    document metadata is changed - mimicking an edit with a PDF editor."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.pdf")
    c = canvas.Canvas(str(tmp), pagesize=A4)
    c.setAuthor("Demo Bank core banking")
    c.setCreator("DemoBank eStatement v4")
    c.setProducer("ReportLab PDF Library")
    c.setTitle("Account Statement")
    Wp, Hp = A4
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, Hp - 60, "DEMO BANK - ACCOUNT STATEMENT")
    c.setFont("Helvetica", 9)
    c.drawString(50, Hp - 76, "Demo Bank Ltd (fictional) - SYNTHETIC SAMPLE FOR DEMONSTRATION ONLY")
    c.setFont("Helvetica", 11)
    rows = [("Account Holder", person["name"]), ("Account Number", "XXXXXXXX5521"),
            ("Address", person["address"]), ("Statement Period", "01/09/2026 to 30/09/2026")]
    y = Hp - 110
    for lab, val in rows:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, f"{lab}:")
        c.setFont("Helvetica", 11)
        c.drawString(190, y, val)
        y -= 18
    y -= 14
    cols = {"Date": 50, "Description": 130, "Debit": 330, "Credit": 410, "Balance": 490}
    c.setFont("Helvetica-Bold", 11)
    for k, x in cols.items():
        c.drawString(x, y, k)
    c.line(50, y - 5, 560, y - 5)
    y -= 22
    bal = 24450.00
    tx = [("01/09/2026", "Opening Balance", None, None),
          ("03/09/2026", "UPI GROCERY MART", 3250.00, None),
          ("05/09/2026", "RENT TRANSFER", 15000.00, None),
          ("12/09/2026", "ELECTRICITY BILL", 1180.00, None),
          ("30/09/2026", "SALARY NIMBUS SOFTWORKS", None, 45200.00)]
    c.setFont("Helvetica", 11)
    for date, desc, dr, cr in tx:
        if dr:
            bal -= dr
        if cr:
            bal += cr
        c.drawString(cols["Date"], y, date)
        c.drawString(cols["Description"], y, desc)
        if dr:
            c.drawString(cols["Debit"], y, inr(dr, True))
        if cr:
            c.drawString(cols["Credit"], y, inr(cr, True))
        c.drawString(cols["Balance"], y, inr(bal, True))
        y -= 18
    c.line(50, y + 8, 560, y + 8)
    y -= 10
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Closing Balance:")
    c.setFont("Helvetica", 11)
    c.drawString(190, y, inr(bal, True))
    closing_y = y
    c.setFont("Helvetica", 8)
    c.drawString(50, 40, "This is a system generated statement and does not require a signature.")
    c.showPage()
    c.save()

    import fitz
    doc = fitz.open(str(tmp))
    if closing_override is not None:
        page = doc[0]
        hits = page.search_for(inr(bal, True))
        # the closing balance is the last occurrence (also appears as last running balance)
        target = max(hits, key=lambda r: r.y0)
        page.add_redact_annot(target, fill=(1, 1, 1))
        page.apply_redactions()
        page.insert_text((target.x0, target.y1 - 2), inr(closing_override, True), fontname="tiro", fontsize=11.5)
        doc.set_metadata({**doc.metadata, "producer": "QuickPDF Editor 2.1", "modDate": "D:20261004213000+05'30'",
                          "creationDate": "D:20260930180000+05'30'"})
    else:
        doc.set_metadata({**doc.metadata, "creationDate": "D:20260930180000+05'30'",
                          "modDate": "D:20260930180000+05'30'"})
    doc.save(str(path))
    doc.close()
    tmp.unlink()


# ------------------------------------------------------------------ cases
def build_genuine():
    out = SAMPLES / "case_genuine"
    save_jpeg(scan(id_card(PERSON), seed=1), out / "01_identity_card.jpg")
    slip, _ = salary_slip(PERSON)
    save_jpeg(scan(slip, seed=2), out / "02_salary_slip.jpg")
    form, _ = application_form(PERSON)
    save_jpeg(scan(form, seed=3), out / "03_loan_application.jpg")
    bank_statement_pdf(out / "04_bank_statement.pdf", PERSON)


def build_tampered():
    out = SAMPLES / "case_tampered"

    # 1. ID card: photograph replaced (clean, noise-free photo pasted after scanning)
    idc = scan(id_card(PERSON), seed=1)
    new_photo = avatar(tone=(160, 120, 95), shirt=(120, 40, 40))
    idc.paste(new_photo, (900, 250))
    save_jpeg(idc, out / "01_identity_card.jpg")

    # 2. Salary slip: Net Pay overwritten 45,200 -> 95,200 (clean patch, serif font)
    slip, net_y = salary_slip(PERSON)
    slip = scan(slip, seed=2)
    paste_patch(slip, (408, net_y - 4, 640, net_y + 40), inr(95200), font(31, serif=True))
    save_jpeg(slip, out / "02_salary_slip.jpg")

    # 3. Loan application: DOB differs from ID, income overwritten, signature outside box
    form, pos = application_form(PERSON, dob="14/03/1994", signature_inside=False)
    form = scan(form, seed=3)
    y = pos["Monthly Net Income"]
    paste_patch(form, (458, y - 4, 700, y + 40), inr(95000), font(31, serif=True))
    save_jpeg(form, out / "03_loan_application.jpg")

    # 4. Bank statement: closing balance edited with a PDF editor
    bank_statement_pdf(out / "04_bank_statement.pdf", PERSON, closing_override=99220.00)

    (out / "MANIFEST.md").write_text(MANIFEST)


MANIFEST = """# Tampered case - ground truth (for judges)

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
"""

if __name__ == "__main__":
    build_genuine()
    build_tampered()
    print("Samples written to", SAMPLES)
