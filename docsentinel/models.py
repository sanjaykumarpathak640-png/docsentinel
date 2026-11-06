"""Common data model shared by every stage of the investigation pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

BBox = tuple  # (x0, y0, x1, y1) in page-pixel coordinates (150 dpi)

# Finding status taxonomy - required by the problem statement to keep
# observations, inconsistencies and potential manipulation clearly apart.
OBSERVATION = "OBSERVATION"                    # a visual/technical characteristic was observed
INCONSISTENCY = "INCONSISTENCY"                # a verifiable logical or data conflict exists
POTENTIAL_MANIPULATION = "POTENTIAL_MANIPULATION"  # several independent signals converge

STATUS_LABEL = {
    OBSERVATION: "Observation",
    INCONSISTENCY: "Detected inconsistency",
    POTENTIAL_MANIPULATION: "Potential manipulation (needs verification)",
}


@dataclass
class Word:
    text: str
    bbox: BBox
    conf: float            # 0-100
    font: Optional[str] = None
    size: Optional[float] = None


@dataclass
class Segment:
    """A run of words on one visual row separated from neighbours by a wide gap
    (typically a label, a value, or a table cell)."""
    words: list
    row: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> BBox:
        return (min(w.bbox[0] for w in self.words), min(w.bbox[1] for w in self.words),
                max(w.bbox[2] for w in self.words), max(w.bbox[3] for w in self.words))

    @property
    def conf(self) -> float:
        return sum(w.conf for w in self.words) / max(1, len(self.words))


@dataclass
class Page:
    index: int
    image: Any                 # PIL.Image (RGB)
    words: list = field(default_factory=list)
    rows: list = field(default_factory=list)   # list[list[Segment]]
    source: str = "ocr"        # "ocr" (scanned/image) or "text-layer" (digital PDF)


@dataclass
class ExtractedField:
    name: str
    value: Any                 # normalised value
    raw: str                   # text as read
    conf: float                # 0-100
    page: int
    bbox: BBox
    label_bbox: Optional[BBox] = None
    method: str = "label-value"


@dataclass
class Document:
    doc_id: str
    filename: str
    path: str
    sha256: str
    media_type: str
    pages: list = field(default_factory=list)
    doc_type: str = "unknown"
    type_conf: float = 0.0
    type_scores: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)      # name -> ExtractedField
    tables: dict = field(default_factory=dict)      # name -> list[dict]
    metadata: dict = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    status: str = "received"
    artefacts: dict = field(default_factory=dict)   # paths to heatmaps etc.

    def summary(self) -> dict:
        return {
            "doc_id": self.doc_id, "filename": self.filename, "sha256": self.sha256,
            "media_type": self.media_type, "pages": len(self.pages),
            "doc_type": self.doc_type, "type_conf": round(self.type_conf, 2),
            "source": self.pages[0].source if self.pages else "-", "status": self.status,
        }


@dataclass
class Evidence:
    doc_id: str
    page: int
    bbox: Optional[BBox]
    field: Optional[str] = None
    value: Optional[str] = None
    note: str = ""
    kind: str = "region"       # region | field | metadata | computed
    crop_path: Optional[str] = None


@dataclass
class Finding:
    id: str
    title: str
    category: str              # structural | visual | digital | contextual | cross_document | correlated
    status: str
    severity: str              # low | medium | high
    confidence: float          # 0-1
    explanation: str
    evidence: list = field(default_factory=list)
    verification: str = ""     # what a human should check next
    rule: str = ""             # detector / rule identifier
    related: list = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    review: dict = field(default_factory=dict)   # analyst decision

    def to_dict(self) -> dict:
        d = asdict(self)
        return d
