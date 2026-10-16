import io
import json
import zipfile

from extract.gleif_isin import (
    LATEST_URL,
    download_to,
    filter_rows,
    manifest_leis,
    parse_latest,
    read_zip_csv,
    run,
    write_csv,
)


def test_filter_rows_keeps_only_wanted_leis():
    rows = [
        {"LEI": "LEI_A", "ISIN": "DK0000000001"},
        {"LEI": "LEI_B", "ISIN": "US0000000002"},
        {"LEI": "LEI_A", "ISIN": "DK0000000003"},
    ]

    result = list(filter_rows(rows, {"LEI_A"}))

    assert result == [
        {"LEI": "LEI_A", "ISIN": "DK0000000001"},
        {"LEI": "LEI_A", "ISIN": "DK0000000003"},
    ]


def test_manifest_leis_returns_unique_leis(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"filing_id": "1", "lei": "LEI_A"}\n'
        '{"filing_id": "2", "lei": "LEI_A"}\n'
        '{"filing_id": "3", "lei": "LEI_B"}\n'
    )

    assert manifest_leis(manifest) == {"LEI_A", "LEI_B"}


def test_read_zip_csv_yields_rows_as_dicts(tmp_path):
    zip_path = tmp_path / "isin.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("lei-isin.csv", "LEI,ISIN\nLEI_A,DK0000000001\nLEI_B,US0000000002\n")

    rows = list(read_zip_csv(zip_path))

    assert rows == [
        {"LEI": "LEI_A", "ISIN": "DK0000000001"},
        {"LEI": "LEI_B", "ISIN": "US0000000002"},
    ]


def test_write_csv_writes_header_rows_and_no_part_file(tmp_path):
    dest = tmp_path / "out" / "lei_isin.csv"
    rows = [{"LEI": "LEI_A", "ISIN": "DK0000000001"}]

    count = write_csv(rows, dest)

    assert count == 1
    assert dest.read_text() == "LEI,ISIN\nLEI_A,DK0000000001\n"
    assert list(dest.parent.glob("*.part")) == []


def test_parse_latest_extracts_download_metadata():
    payload = {
        "data": {
            "attributes": {
                "fileName": "isin-lei-test.zip",
                "uploadedAt": "2026-10-16T07:00:00Z",
                "downloadLink": "https://example.test/download",
            }
        }
    }

    assert parse_latest(payload) == {
        "file_name": "isin-lei-test.zip",
        "uploaded_at": "2026-10-16T07:00:00Z",
        "download_link": "https://example.test/download",
    }


class FakeStreamResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield from self.chunks


class StreamSession:
    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = None

    def get(self, url, **kwargs):
        self.kwargs = kwargs
        return FakeStreamResponse(self.chunks)


def test_download_to_streams_chunks_to_file(tmp_path):
    dest = tmp_path / "isin.zip"
    session = StreamSession([b"ab", b"cd"])

    download_to(session, "https://example.test/isin.zip", dest)

    assert dest.read_bytes() == b"abcd"
    assert session.kwargs["stream"] is True
    assert list(tmp_path.glob("*.part")) == []


def make_zip_bytes(csv_text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("lei-isin.csv", csv_text)
    return buffer.getvalue()


class FakeJsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class GleifSession:
    def __init__(self, zip_bytes):
        self.zip_bytes = zip_bytes
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if url == LATEST_URL:
            return FakeJsonResponse(
                {
                    "data": {
                        "attributes": {
                            "fileName": "isin-lei-test.zip",
                            "uploadedAt": "2026-10-16T07:00:00Z",
                            "downloadLink": "https://example.test/download",
                        }
                    }
                }
            )
        return FakeStreamResponse([self.zip_bytes])


def write_manifest(landing_dir, leis):
    path = landing_dir / "esef" / "manifest.jsonl"
    path.parent.mkdir(parents=True)
    lines = [json.dumps({"filing_id": str(i), "lei": lei}) for i, lei in enumerate(leis)]
    path.write_text("\n".join(lines) + "\n")


def test_run_writes_filtered_csv_and_source(tmp_path):
    write_manifest(tmp_path, ["LEI_A"])
    session = GleifSession(make_zip_bytes("LEI,ISIN\nLEI_A,DK0000000001\nLEI_B,US0000000002\n"))

    result = run(session, tmp_path, "2026-10-16")

    out_dir = tmp_path / "lei_isin" / "ingest_date=2026-10-16"
    assert result == {"status": "written", "leis": 1, "rows": 1}
    assert (out_dir / "lei_isin.csv").read_text() == "LEI,ISIN\nLEI_A,DK0000000001\n"
    assert json.loads((out_dir / "source.json").read_text())["file_name"] == "isin-lei-test.zip"


def test_run_twice_same_day_is_noop(tmp_path):
    write_manifest(tmp_path, ["LEI_A"])
    session = GleifSession(make_zip_bytes("LEI,ISIN\nLEI_A,DK0000000001\n"))

    run(session, tmp_path, "2026-10-16")
    result = run(session, tmp_path, "2026-10-16")

    assert result == {"status": "skipped"}
    assert session.calls == 2
