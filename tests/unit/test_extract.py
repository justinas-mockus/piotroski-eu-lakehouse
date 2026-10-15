import hashlib
import json
from pathlib import Path

from extract.esef_filings import append_manifest, load_manifest, parse_filing, sha256_file

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_page():
    return json.loads((FIXTURES / "filings_page.json").read_text())


def test_parse_filing_extracts_manifest_fields():
    item = load_page()["data"][0]

    record = parse_filing(item)

    assert record == {
        "filing_id": "1001",
        "lei": "529900TESTLEI0000001",
        "period_end": "2024-12-31",
        "url": "https://filings.xbrl.org/529900TESTLEI0000001/2024-12-31/ESEF/DK/0/529900TESTLEI0000001-2024-12-31-da.json",
        "error_count": 0,
    }


def test_load_manifest_mising_file_returns_empty_set(tmp_path):
    assert load_manifest(tmp_path / "manifest.jsonl") == set()


def test_load_manifest_return_filing_ids(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text('{"filing_id": "1001", "lei": "A"}\n{"filing_id": "1002", "lei": "B"}\n')

    assert load_manifest(manifest) == {"1001", "1002"}


def test_sha256_file_matches_known_value(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_bytes(b"hello")

    assert sha256_file(f) == ("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


def test_sha256_file_handles_file_larger_than_one_chunk(tmp_path):
    data = b"x" * (2_500_000)
    f = tmp_path / "big.bin"
    f.write_bytes(data)

    assert sha256_file(f) == hashlib.sha256(data).hexdigest()


def test_append_manifest_creates_file_and_appends_lines(tmp_path):
    manifest = tmp_path / "landing" / "manifest.jsonl"

    append_manifest(manifest, {"filing_id": "1001", "lei": "A"})
    append_manifest(manifest, {"filing_id": "1002", "lei": "B"})

    lines = manifest.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"filing_id": "1001", "lei": "A"}


def test_append_manifest_roundtrips_with_load_manifest(tmp_path):
    manifest = tmp_path / "landing" / "manifest.jsonl"

    append_manifest(manifest, {"filing_id": "1001"})
    append_manifest(manifest, {"filing_id": "1002"})

    assert load_manifest(manifest) == {"1001", "1002"}
