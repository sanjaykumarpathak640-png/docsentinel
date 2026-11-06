"""Stage 3 - OCR (Tesseract) and layout grouping into rows and segments."""
from __future__ import annotations

import statistics

import pytesseract
from PIL import Image, ImageOps

from .models import Segment, Word


def ocr_page(img: Image.Image, lang: str = "eng") -> list:
    gray = ImageOps.grayscale(img)
    data = pytesseract.image_to_data(gray, lang=lang, config="--psm 3",
                                     output_type=pytesseract.Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        t = (text or "").strip()
        conf = float(data["conf"][i])
        if not t or conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        if w < 3 or h < 6:
            continue
        words.append(Word(text=t, bbox=(x, y, x + w, y + h), conf=conf))
    return words


def build_rows(words: list) -> list:
    """Cluster words into visual rows (vertical overlap), then split each row
    into segments wherever the horizontal gap is much wider than a word space."""
    if not words:
        return []
    ws = sorted(words, key=lambda w: (w.bbox[1] + w.bbox[3]) / 2)
    rows, current = [], [ws[0]]
    for w in ws[1:]:
        ref = current[-1]
        cy = (w.bbox[1] + w.bbox[3]) / 2
        rtop = min(x.bbox[1] for x in current)
        rbot = max(x.bbox[3] for x in current)
        h = rbot - rtop
        if rtop - 0.15 * h <= cy <= rbot + 0.15 * h and abs(cy - (ref.bbox[1] + ref.bbox[3]) / 2) < 0.7 * h:
            current.append(w)
        else:
            rows.append(current)
            current = [w]
    rows.append(current)

    out = []
    for ri, row in enumerate(rows):
        row.sort(key=lambda w: w.bbox[0])
        hs = [w.bbox[3] - w.bbox[1] for w in row]
        med_h = statistics.median(hs) if hs else 20
        gap_thr = max(28.0, 1.25 * med_h)
        segs, cur = [], [row[0]]
        for w in row[1:]:
            if w.bbox[0] - cur[-1].bbox[2] > gap_thr:
                segs.append(Segment(words=cur, row=ri))
                cur = [w]
            else:
                cur.append(w)
        segs.append(Segment(words=cur, row=ri))
        out.append(segs)
    return out


def page_text(page) -> str:
    return "\n".join("    ".join(s.text for s in row) for row in page.rows)
