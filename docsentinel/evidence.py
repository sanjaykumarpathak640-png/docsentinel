"""Stage 9 - Evidence generation: crops of every evidence region and annotated
page images, so each finding can be traced back to its source location."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import INCONSISTENCY, OBSERVATION, POTENTIAL_MANIPULATION

COLORS = {POTENTIAL_MANIPULATION: (220, 30, 40), INCONSISTENCY: (240, 140, 0), OBSERVATION: (30, 110, 220)}


def _font(size=18):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def make_crops(findings, docs, outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    pages = {(d.doc_id, p.index): p.image for d in docs for p in d.pages}
    for f in findings:
        for i, e in enumerate(f.evidence):
            if not e.bbox or (e.doc_id, e.page) not in pages:
                continue
            img = pages[(e.doc_id, e.page)]
            x0, y0, x1, y1 = [int(v) for v in e.bbox]
            pad = 40
            box = (max(0, x0 - pad * 3), max(0, y0 - pad), min(img.width, x1 + pad * 3), min(img.height, y1 + pad))
            crop = img.crop(box).copy()
            d = ImageDraw.Draw(crop)
            d.rectangle([x0 - box[0] - 3, y0 - box[1] - 3, x1 - box[0] + 3, y1 - box[1] + 3],
                        outline=COLORS[f.status], width=4)
            p = outdir / f"{f.id}_{i}.png"
            crop.save(p)
            e.crop_path = str(p)


def annotate_pages(findings, docs, outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    out = {}
    fnt = _font(20)
    for d in docs:
        for p in d.pages:
            img = p.image.copy()
            dr = ImageDraw.Draw(img)
            seen = set()
            # strongest status drawn last (on top)
            order = sorted(findings, key=lambda f: [OBSERVATION, INCONSISTENCY, POTENTIAL_MANIPULATION].index(f.status))
            for f in order:
                for e in f.evidence:
                    if e.doc_id != d.doc_id or e.page != p.index or not e.bbox:
                        continue
                    key = (tuple(int(v) for v in e.bbox), f.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    x0, y0, x1, y1 = [int(v) for v in e.bbox]
                    c = COLORS[f.status]
                    dr.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline=c, width=4)
                    tw = dr.textlength(f.id, font=fnt)
                    ty = max(0, y0 - 28)
                    dr.rectangle([x1 + 6, ty, x1 + 14 + tw, ty + 24], fill=c)
                    dr.text((x1 + 10, ty + 1), f.id, font=fnt, fill=(255, 255, 255))
            path = outdir / f"{d.doc_id}_p{p.index + 1}_annotated.png"
            img.save(path)
            out[(d.doc_id, p.index)] = str(path)
            d.artefacts.setdefault("annotated", {})[p.index] = str(path)
    return out
