import hashlib
import json
from pathlib import Path

import pytest
import requests

from extract.esef_filings import (
    append_manifest,
    download_file,
    is_wanted,
    iter_filings,
    load_manifest,
    parse_filing,
    run,
    sha256_file,
)

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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.pages[len(self.calls) - 1])


def test_iter_filings_follows_next_links():
    page1 = {"data": [{"id": "1"}, {"id": "2"}], "links": {"next": "https://example.test/page2"}}
    page2 = {"data": [{"id": "3"}], "links": {}}
    session = FakeSession([page1, page2])

    items = list(iter_filings(session, delay=0))

    assert [i["id"] for i in items] == ["1", "2", "3"]
    assert session.calls[1][0] == "https://example.test/page2"


class FakeBytesResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class FlakySession:
    """Fails the first `failures` calls, then succeeds."""

    def __init__(self, failures, content=b"data"):
        self.failures = failures
        self.content = content
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise requests.ConnectionError("boom")
        return FakeBytesResponse(self.content)


def test_is_wanted_keeps_clean_filings_from_2024_and_2025():
    assert is_wanted(
        {"error_count": 0, "period_end": "2024-12-31", "url": "https://example.test/a.json"}
    )
    assert is_wanted(
        {"error_count": 0, "period_end": "2025-06-30", "url": "https://example.test/b.json"}
    )
    assert not is_wanted(
        {"error_count": 2, "period_end": "2024-12-31", "url": "https://example.test/c.json"}
    )
    assert not is_wanted(
        {"error_count": 0, "period_end": "2023-12-31", "url": "https://example.test/d.json"}
    )


def test_download_file_writes_file_and_leaves_no_part_file(tmp_path):
    dest = tmp_path / "out" / "a.json"

    download_file(FlakySession(failures=0), "https://example.test/a.json", dest)

    assert dest.read_bytes() == b"data"
    assert list(dest.parent.glob("*.part")) == []


def test_download_file_retries_with_exponential_backoff(tmp_path):
    dest = tmp_path / "a.json"
    session = FlakySession(failures=2)
    waits = []

    download_file(session, "https://example.test/a.json", dest, sleep=waits.append)

    assert session.calls == 3
    assert waits == [1, 2]


def test_download_file_gives_up_and_leaves_no_file(tmp_path):
    dest = tmp_path / "a.json"
    session = FlakySession(failures=10)

    with pytest.raises(requests.ConnectionError):
        download_file(session, "https://example.test/a.json", dest, retries=3, sleep=lambda s: None)

    assert session.calls == 3
    assert not dest.exists()


class HttpErrorSession:
    def __init__(self, status):
        self.status = status
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        response = requests.Response()
        response.status_code = self.status
        raise requests.HTTPError("http error", response=response)


def test_download_file_fails_fast_on_404(tmp_path):
    session = HttpErrorSession(404)

    with pytest.raises(requests.HTTPError):
        download_file(
            session, "https://example.test/a.json", tmp_path / "a.json", sleep=lambda s: None
        )

    assert session.calls == 1


def test_download_file_retries_429(tmp_path):
    session = HttpErrorSession(429)

    with pytest.raises(requests.HTTPError):
        download_file(
            session, "https://example.test/a.json", tmp_path / "a.json", sleep=lambda s: None
        )

    assert session.calls == 4


def test_is_wanted_tolerates_missing_period_end():
    assert not is_wanted(
        {"error_count": 0, "period_end": None, "url": "https://example.test/a.json"}
    )


class RoutedSession:
    """Serves the listing page and the file downloads from one fake."""

    def __init__(self, page, files):
        self.page = page
        self.files = files
        self.downloads = 0

    def get(self, url, params=None, timeout=None):
        if url.endswith("/api/filings"):
            return FakeResponse(self.page)
        self.downloads += 1
        return FakeBytesResponse(self.files[url])


def make_session():
    page = {**load_page(), "links": {}}
    url = parse_filing(page["data"][0])["url"]
    return RoutedSession(page, {url: b'{"facts": {}}'})


def read_manifest(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_run_downloads_wanted_filings_and_writes_manifest(tmp_path):
    session = make_session()

    counts = run(session, tmp_path, "2026-10-15", delay=0, sleep=lambda s: None)

    assert counts == {"new": 1, "skipped": 0, "failed": 0}
    files = list((tmp_path / "esef" / "ingest_date=2026-10-15").glob("*.json"))
    assert [f.name for f in files] == ["529900TESTLEI0000001_2024-12-31_1001.json"]
    manifest = read_manifest(tmp_path / "esef" / "manifest.jsonl")
    assert manifest[0]["filing_id"] == "1001"
    assert manifest[0]["sha256"] == sha256_file(files[0])


def test_run_twice_is_idempotent(tmp_path):
    session = make_session()

    run(session, tmp_path, "2026-10-15", delay=0, sleep=lambda s: None)
    counts = run(session, tmp_path, "2026-10-16", delay=0, sleep=lambda s: None)

    assert counts == {"new": 0, "skipped": 1, "failed": 0}
    assert session.downloads == 1
    assert len(read_manifest(tmp_path / "esef" / "manifest.jsonl")) == 1


def test_parse_filing_keeps_missing_json_url_as_none():
    item = load_page()["data"][3]

    assert parse_filing(item)["url"] is None


def test_is_wanted_rejects_filings_without_url():
    assert not is_wanted({"error_count": 0, "period_end": "2024-12-31", "url": None})
