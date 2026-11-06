"""Command-line investigation.

    python -m docsentinel.cli samples/case_tampered
    python -m docsentinel.cli doc1.jpg doc2.pdf --out output --analyst "Ayush"
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from .ingest import SUPPORTED  # noqa: E402
from .models import STATUS_LABEL  # noqa: E402
from .pipeline import Investigation  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="DocSentinel - document forensics investigation")
    ap.add_argument("inputs", nargs="+", help="files or a folder of related documents")
    ap.add_argument("--out", default="output", help="output folder")
    ap.add_argument("--analyst", default="analyst")
    ap.add_argument("--case-id", default=None)
    a = ap.parse_args(argv)

    files = []
    for i in a.inputs:
        p = Path(i)
        files += sorted(x for x in p.iterdir() if x.suffix.lower() in SUPPORTED) if p.is_dir() else [p]
    if not files:
        print("No supported documents found.", file=sys.stderr)
        return 2

    def progress(i, name, msg=""):
        print(f"  [{i + 1:2d}/10] {name}")

    inv = Investigation(files, a.out, case_id=a.case_id, analyst=a.analyst)
    print(f"Investigation {inv.case_id} - {len(files)} document(s)")
    case = inv.run(progress=progress)
    print("\nFindings:")
    for f in case["findings"]:
        print(f"  {f.id}  {STATUS_LABEL[f.status]:<45} {f.confidence:>4.0%}  {f.title}")
    print(f"\nReview priority: {case['priority']['case_level']}")
    print(f"Dossier: {case['dossier']}")
    print(f"JSON:    {inv.outdir / 'investigation.json'}")
    ok, msg = inv.audit.verify()
    print(f"Audit:   {inv.audit.path} ({'verified' if ok else 'BROKEN'}: {msg})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
