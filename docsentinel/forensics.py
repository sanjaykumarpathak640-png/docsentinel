"""Stage 5 - Visual and digital forensic analysis.

Detectors (each produces *observations*, never verdicts):
  V1 noise-consistency   regions lacking the sensor/scanner noise present in the
                         rest of the page (typical of pasted/overwritten patches)
  V2 ELA                 Error Level Analysis heat-map (JPEG recompression residue)
  V3 glyph-size          a field value whose character height differs from the
                         other values aligned in the same column
  V4 signature           signature detection, placement vs. designated area,
                         and similarity between signatures across documents
  D1 pdf-fonts           text-layer spans using a font foreign to the document
  D2 pdf-metadata        editing software / modification after creation
"""
from __future__ import annotations

import io
import statistics
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .extract import FIELD_LABEL

BLOCK = 16


# ------------------------------------------------------------------- helpers
def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L")).astype(np.float32)


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    area = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    return inter / area


def heat_overlay(img: Image.Image, heat: np.ndarray) -> Image.Image:
    h = np.clip(heat / (max(float(np.percentile(heat, 99.5)), float(heat.max()) * 0.5) + 1e-6), 0, 1)
    h = cv2.resize((h * 255).astype(np.uint8), img.size, interpolation=cv2.INTER_NEAREST)
    colored = cv2.applyColorMap(h, cv2.COLORMAP_JET)[:, :, ::-1]
    base = np.asarray(img.convert("RGB")).astype(np.float32)
    alpha = (0.12 + 0.7 * (h.astype(np.float32) / 255.0))[:, :, None]
    out = base * (1 - alpha) + colored.astype(np.float32) * alpha
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


# --------------------------------------------------------- V1 noise residual
def noise_analysis(img: Image.Image):
    """Per-block standard deviation of the high-frequency residual measured
    on flat (non-text) pixels. Scanned paper carries roughly uniform noise;
    a patch inserted after scanning is abnormally clean."""
    g = _gray(img)
    resid = g - cv2.GaussianBlur(g, (0, 0), 1.2)
    smooth = cv2.GaussianBlur(g, (0, 0), 3.0)
    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1)
    flat = np.hypot(gx, gy) < 6.0
    H, W = g.shape
    bh, bw = H // BLOCK, W // BLOCK
    stds = np.full((bh, bw), np.nan, dtype=np.float32)
    for by in range(bh):
        for bx in range(bw):
            ys, xs = slice(by * BLOCK, (by + 1) * BLOCK), slice(bx * BLOCK, (bx + 1) * BLOCK)
            m = flat[ys, xs]
            if m.mean() > 0.55:
                stds[by, bx] = resid[ys, xs][m].std()
    valid = stds[~np.isnan(stds)]
    if valid.size < 50:
        return {"available": False}
    med = float(np.median(valid))
    flagged = (stds < 0.42 * med) & ~np.isnan(stds)
    flagged_u8 = flagged.astype(np.uint8)
    flagged_u8 = cv2.morphologyEx(flagged_u8, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(flagged_u8, connectivity=8)
    regions = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 6:
            continue
        comp = labels == i
        region_std = float(np.nanmedian(np.where(comp, stds, np.nan)))
        regions.append({
            "bbox": (int(x * BLOCK), int(y * BLOCK), int((x + w) * BLOCK), int((y + h) * BLOCK)),
            "blocks": int(area),
            "region_noise": round(region_std, 2),
            "page_noise": round(med, 2),
            "ratio": round(region_std / med, 2) if med else 0.0,
        })
    heat = np.nan_to_num(np.clip((0.6 * med - stds) / (0.6 * med), 0, 1), nan=0.0)
    return {"available": True, "page_noise": round(med, 2), "regions": regions, "heat": heat}


# ------------------------------------------------------------------ V2 ELA
def ela(img: Image.Image, quality: int = 90):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    re = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    diff = np.abs(np.asarray(img).astype(np.int16) - np.asarray(re).astype(np.int16)).max(axis=2).astype(np.float32)
    H, W = diff.shape
    bh, bw = H // BLOCK, W // BLOCK
    blocks = diff[: bh * BLOCK, : bw * BLOCK].reshape(bh, BLOCK, bw, BLOCK).mean(axis=(1, 3))
    return {"map": blocks, "mean": float(blocks.mean())}


def region_ela_ratio(ela_res, bbox) -> float:
    m = ela_res["map"]
    x0, y0, x1, y1 = [int(v // BLOCK) for v in bbox]
    sub = m[y0:max(y0 + 1, y1), x0:max(x0 + 1, x1)]
    return round(float(sub.mean()) / (ela_res["mean"] + 1e-6), 2) if sub.size else 1.0


# --------------------------------------------------------- V3 glyph heights
def _core_height(gray: np.ndarray, bbox) -> float | None:
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    crop = gray[max(0, y0 - 3): y1 + 3, max(0, x0 - 2): x1 + 2]
    if crop.size == 0:
        return None
    ink = (crop < 128).sum(axis=1).astype(np.float32)
    if ink.max() <= 0:
        return None
    rows = np.where(ink >= 0.30 * ink.max())[0]
    return float(rows[-1] - rows[0] + 1) if rows.size else None


def glyph_size_check(doc) -> list:
    """Compare character height of numeric values that share a value column."""
    page = doc.pages[0]
    if page.source != "ocr":
        return []
    g = _gray(page.image)
    cand = []
    for name, f in doc.fields.items():
        if f.method != "label-value":
            continue
        txt = f.raw.replace(",", "").replace("/", "").replace("-", "").replace(".", "")
        if not txt or sum(c.isdigit() for c in txt) < 0.7 * len(txt):
            continue
        h = _core_height(g, f.bbox)
        if h:
            cand.append((name, f, h))
    out = []
    # group by column (left edge)
    groups = []
    for c in sorted(cand, key=lambda c: c[1].bbox[0]):
        if groups and abs(groups[-1][-1][1].bbox[0] - c[1].bbox[0]) <= 14:
            groups[-1].append(c)
        else:
            groups.append([c])
    for grp in groups:
        if len(grp) < 3:
            continue
        med = statistics.median(h for _, _, h in grp)
        for name, f, h in grp:
            dev = (h - med) / med
            if abs(dev) >= 0.07:
                out.append({"field": name, "bbox": f.bbox, "height": h, "column_median": med,
                            "deviation": round(dev, 3), "peers": [n for n, _, _ in grp if n != name]})
    return out


# ------------------------------------------------------------ V4 signatures
def _ink_mask(img: Image.Image) -> np.ndarray:
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    return ((b - r > 35) & (b - g > 20) & (b > 70)).astype(np.uint8)  # blue/coloured ink


def _boxes(gray: np.ndarray):
    bw = (gray < 110).astype(np.uint8) * 255
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)))
    lines = cv2.dilate(horiz | vert, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(lines, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if 150 < w < gray.shape[1] * 0.9 and 50 < h < 400:
            out.append((x, y, x + w, y + h))
    return out


def signature_analysis(doc) -> dict:
    page = doc.pages[0]
    if page.source != "ocr":
        return {"available": False, "reason": "digital document - no handwritten signature expected"}
    mask = _ink_mask(page.image)
    mask = cv2.dilate(mask, np.ones((9, 25), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    raw_ink = _ink_mask(page.image)
    blobs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (w > 80 and 25 < h < 220 and area > 1500 and w / h > 1.8):
            continue
        density = raw_ink[y:y + h, x:x + w].mean()
        if density < 0.22:  # handwriting is thin strokes, not filled shapes / frames
            blobs.append((int(x), int(y), int(x + w), int(y + h)))
    label_seg = None
    for row in page.rows:
        for seg in row:
            if "signature" in seg.text.lower() or "signatory" in seg.text.lower():
                label_seg = seg
    res = {"available": True, "signatures": blobs, "label_bbox": label_seg.bbox if label_seg else None}
    if not label_seg:
        res["placement"] = "no-signature-field"
        return res
    lb = label_seg.bbox
    boxes = [b for b in _boxes(_gray(page.image)) if b[1] >= lb[1] - 10 and b[1] - lb[3] < 120
             and abs(b[0] - lb[0]) < 200]
    area = boxes[0] if boxes else (lb[0] - 40, lb[3], lb[0] + 520, lb[3] + 200)
    res["designated_area"] = area
    res["designated_kind"] = "drawn box" if boxes else "area below label"
    inside = [b for b in blobs if _overlap(b, area) > 0.6]
    res["inside"] = inside
    res["outside"] = [b for b in blobs if b not in inside]
    if inside:
        res["placement"] = "inside"
    elif blobs:
        res["placement"] = "outside"
    else:
        res["placement"] = "missing"
    res["mask_crops"] = {}
    raw = _ink_mask(page.image)
    for b in blobs:
        res["mask_crops"][b] = raw[b[1]:b[3], b[0]:b[2]]
    return res


def signature_similarity(mask_a: np.ndarray, mask_b: np.ndarray) -> float:
    """Shape similarity of two signature ink masks (0-1). Heuristic only."""
    def prep(m):
        ys, xs = np.where(m > 0)
        if ys.size == 0:
            return None
        m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
        m = cv2.resize(m, (240, 64), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(m, (0, 0), 2.5)
    a, b = prep(mask_a), prep(mask_b)
    if a is None or b is None:
        return 0.0
    a = (a - a.mean()) / (a.std() + 1e-6)
    b = (b - b.mean()) / (b.std() + 1e-6)
    return round(float(max(0.0, (a * b).mean())), 2)


# --------------------------------------------------------- D1/D2 digital PDF
def pdf_font_analysis(doc) -> list:
    page = doc.pages[0]
    if page.source != "text-layer":
        return []
    fonts = [w.font for w in page.words if w.font]
    if not fonts:
        return []
    fam = lambda f: f.split("-")[0].split(",")[0].lower()
    counts = {}
    for f in fonts:
        counts[fam(f)] = counts.get(fam(f), 0) + 1
    dominant = max(counts, key=counts.get)
    out = []
    for w in page.words:
        if w.font and fam(w.font) != dominant and counts[fam(w.font)] / len(fonts) < 0.1:
            out.append({"text": w.text, "bbox": w.bbox, "font": w.font, "dominant": dominant,
                        "share": round(counts[fam(w.font)] / len(fonts), 3)})
    return out


def pdf_metadata_analysis(doc) -> list:
    md = doc.metadata.get("pdf", {})
    out = []
    editors = ("editor", "acrobat", "ilovepdf", "smallpdf", "foxit", "sejda", "pdfescape", "nitro", "quickpdf")
    prod = (md.get("producer") or "").lower()
    creator = (md.get("creator") or "").lower()
    if any(e in prod for e in editors) and not any(e in creator for e in editors):
        out.append({"kind": "producer", "detail": f"Created by '{md.get('creator')}' but last written by '{md.get('producer')}'"})
    c, m = md.get("creationDate", ""), md.get("modDate", "")
    if c and m and m[2:16] > c[2:16]:
        out.append({"kind": "modified", "detail": f"Modified ({_pdfdate(m)}) after creation ({_pdfdate(c)})"})
    if doc.metadata.get("pdf_eof_markers", 1) > 1:
        out.append({"kind": "incremental", "detail": f"{doc.metadata['pdf_eof_markers']} incremental save sections"})
    return out


def _pdfdate(s: str) -> str:
    s = s[2:] if s.startswith("D:") else s
    return f"{s[6:8]}/{s[4:6]}/{s[0:4]} {s[8:10]}:{s[10:12]}" if len(s) >= 12 else s


def _fields_near(doc, bbox) -> list:
    """Fields whose value sits on the same row as the region and touches it."""
    out = []
    for n, f in doc.fields.items():
        fb = f.bbox
        oy = max(0, min(fb[3], bbox[3]) - max(fb[1], bbox[1])) / max(1, fb[3] - fb[1])
        gap = max(0, bbox[0] - fb[2], fb[0] - bbox[2])
        if oy > 0.5 and gap < 120:
            out.append(n)
    return out


def _region_kind(img, bbox) -> str:
    x0, y0, x1, y1 = bbox
    a = np.asarray(img.convert("RGB"))[y0:y1, x0:x1].astype(np.int16)
    if a.size == 0:
        return "region"
    sat = (a.max(axis=2) - a.min(axis=2)).mean()
    dark = (a.mean(axis=2) < 200).mean()
    if sat > 18 or dark > 0.35:
        return "image"
    return "text-area"


# ---------------------------------------------------------------- run all
def analyse(doc, outdir: Path) -> dict:
    page = doc.pages[0]
    res = {"noise": {"available": False}, "glyph": [], "signature": {}, "pdf_fonts": [], "pdf_meta": []}
    if page.source == "ocr":
        nz = noise_analysis(page.image)
        res["noise"] = nz
        el = ela(page.image)
        res["ela"] = el
        if nz.get("available"):
            for r in nz["regions"]:
                r["ela_ratio"] = region_ela_ratio(el, r["bbox"])
                r["fields"] = _fields_near(doc, r["bbox"])
                r["kind"] = _region_kind(page.image, r["bbox"])
            p = outdir / f"{doc.doc_id}_noise.png"
            heat_overlay(page.image, nz["heat"]).save(p)
            doc.artefacts["noise_map"] = str(p)
        p = outdir / f"{doc.doc_id}_ela.png"
        heat_overlay(page.image, el["map"]).save(p)
        doc.artefacts["ela_map"] = str(p)
        res["glyph"] = glyph_size_check(doc)
    res["signature"] = signature_analysis(doc)
    res["pdf_fonts"] = pdf_font_analysis(doc)
    if res["pdf_fonts"]:
        for item in res["pdf_fonts"]:
            item["fields"] = [n for n, f in doc.fields.items() if _overlap(item["bbox"], f.bbox) > 0.5]
    res["pdf_meta"] = pdf_metadata_analysis(doc)
    return res


__all__ = ["analyse", "signature_similarity", "FIELD_LABEL"]
