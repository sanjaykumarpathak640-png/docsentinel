"""End-to-end tests against the demonstration dataset (ground truth in
samples/case_tampered/MANIFEST.md).  Run:  pytest -q"""
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

from docsentinel.audit import AuditLog  # noqa: E402
from docsentinel.models import INCONSISTENCY, POTENTIAL_MANIPULATION  # noqa: E402
from docsentinel.pipeline import Investigation  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def run(case, tmp_path):
    files = sorted((ROOT / "samples" / case).glob("0*"))
    inv = Investigation(files, tmp_path, case_id="T")
    return inv, inv.run(generate_dossier=True)


@pytest.fixture(scope="module")
def tampered(tmp_path_factory):
    return run("case_tampered", tmp_path_factory.mktemp("t"))


@pytest.fixture(scope="module")
def genuine(tmp_path_factory):
    return run("case_genuine", tmp_path_factory.mktemp("g"))


def rules(case):
    return {f.rule for f in case["findings"]}


def test_classification(tampered):
    _, case = tampered
    assert [d.doc_type for d in case["docs"]] == ["identity_card", "salary_slip", "loan_application", "bank_statement"]


def test_extraction_values(tampered):
    _, case = tampered
    d = {x.doc_type: x for x in case["docs"]}
    assert d["identity_card"].fields["name"].value == "Rohan Verma"
    assert d["salary_slip"].fields["gross"].value == 52000
    assert d["bank_statement"].tables["transactions"][-1]["credit"] == 45200


def test_T1_photo_replacement(tampered):
    _, case = tampered
    assert any(f.rule == "V1-noise-consistency" and f.signals.get("kind") == "image" for f in case["findings"])


def test_T2_T3_overwritten_fields(tampered):
    _, case = tampered
    pm = {f.signals["fields"][0] for f in case["findings"] if f.status == POTENTIAL_MANIPULATION}
    assert {"net_pay", "income", "closing"} <= pm


def test_T4_dob_mismatch(tampered):
    _, case = tampered
    assert "X-dob" in rules(case)


def test_T5_signature_outside(tampered):
    _, case = tampered
    assert "V4-signature-placement" in rules(case)


def test_T6_pdf_edit(tampered):
    _, case = tampered
    assert {"D1-pdf-font", "D2-pdf-metadata", "C5-bank-closing"} <= rules(case)


def test_likely_original_value(tampered):
    _, case = tampered
    f = next(f for f in case["findings"] if f.status == POTENTIAL_MANIPULATION and f.signals["fields"] == ["net_pay"])
    assert f.signals["likely_original"] == 45200


def test_genuine_has_no_inconsistencies(genuine):
    _, case = genuine
    bad = [f for f in case["findings"] if f.status in (INCONSISTENCY, POTENTIAL_MANIPULATION)]
    assert bad == []
    assert case["priority"]["case_level"] == "LOW"


def test_dossier_and_audit(tampered):
    inv, case = tampered
    assert Path(case["dossier"]).stat().st_size > 50_000
    ok, _ = inv.audit.verify()
    assert ok


def test_audit_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.log("a", x=1)
    log.log("b", x=2)
    lines = log.path.read_text().splitlines()
    lines[0] = lines[0].replace('"x": 1', '"x": 9')
    log.path.write_text("\n".join(lines) + "\n")
    assert not AuditLog(tmp_path / "a.jsonl").verify()[0]


def test_unsupported_file_fails_safely(tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    inv = Investigation([bad], tmp_path, case_id="B")
    case = inv.run(generate_dossier=False)
    assert case["errors"] and case["docs"] == []
