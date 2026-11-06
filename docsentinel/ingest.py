"""Stage 1 - Document submission: load files, hash them, render pages.

Scanned images are passed to OCR. Digital PDFs keep their text layer (exact
characters, fonts and positions), which is also used for digital forensics.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from .models import Document, Page, Word
from .ocr import build_rows, ocr_page

DPI = 150
SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_document(path: Path, doc_id: str) -> Document:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {ext}")
    doc = Document(doc_id=doc_id, filename=path.name, path=str(path), sha256=sha256_file(path),
                   media_type="application/pdf" if ext == ".pdf" else f"image/{ext.strip('.')}")
    if ext == ".pdf":
        _load_pdf(doc, path)
    else:
        img = Image.open(path)
        img.load()
        doc.metadata["image_format"] = img.format
        doc.metadata["image_mode"] = img.mode
        doc.metadata["image_size"] = img.size
        exif = img.getexif()
        if exif:
            doc.metadata["exif"] = {str(k): str(v)[:80] for k, v in exif.items()}
        img = img.convert("RGB")
        page = Page(index=0, image=img, source="ocr")
        page.words = ocr_page(img)
        page.rows = build_rows(page.words)
        doc.pages.append(page)
    doc.status = "ingested"
    return doc


def _load_pdf(doc: Document, path: Path) -> None:
    import pymupdf as fitz

    pdf = fitz.open(str(path))
    doc.metadata["pdf"] = {k: v for k, v in (pdf.metadata or {}).items() if v}
    raw = path.read_bytes()
    doc.metadata["pdf_eof_markers"] = raw.count(b"%%EOF")
    scale = DPI / 72.0
    for i, pg in enumerate(pdf):
        pix = pg.get_pixmap(dpi=DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        words = _text_layer_words(pg, scale)
        if len(words) >= 5:
            page = Page(index=i, image=img, words=words, source="text-layer")
        else:  # scanned PDF without text layer -> OCR
            page = Page(index=i, image=img, words=ocr_page(img), source="ocr")
        page.rows = build_rows(page.words)
        doc.pages.append(page)
    pdf.close()


def _text_layer_words(pg, scale: float) -> list:
    """Words from the PDF text layer, each tagged with the font of its span."""
    spans = []
    for block in pg.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                if s["text"].strip():
                    spans.append((s["bbox"], s["font"], s["size"]))
    words = []
    for x0, y0, x1, y1, text, *_ in pg.get_text("words"):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        fnt, size = None, None
        for (sx0, sy0, sx1, sy1), f, sz in spans:
            if sx0 - 1 <= cx <= sx1 + 1 and sy0 - 1 <= cy <= sy1 + 1:
                fnt, size = f, sz
                break
        words.append(Word(text=text, bbox=(x0 * scale, y0 * scale, x1 * scale, y1 * scale),
                          conf=99.0, font=fnt, size=size))
    return words
