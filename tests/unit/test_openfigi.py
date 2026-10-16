import pytest
import requests

from extract.openfigi import (
    MAPPING_URL,
    batches,
    latest_lei_isin,
    mapping_jobs,
    parse_results,
    post_mapping,
    read_lei_by_isin,
    run,
)


def test_batches_splits_into_chunks():
    assert list(batches([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_mapping_jobs_ask_for_copenhagen_listing():
    assert mapping_jobs(["DK0000000001"]) == [
        {"idType": "ID_ISIN", "idValue": "DK0000000001", "exchCode": "DC"}
    ]


def test_parse_results_keeps_matches_and_skips_warnings():
    isins = ["DK0000000001", "DK0000000002"]
    results = [
        {
            "data": [
                {
                    "figi": "BBG000000001",
                    "ticker": "ABC",
                    "name": "ABC A/S",
                    "exchCode": "DC",
                    "securityType": "Common Stock",
                    "marketSector": "Equity",
                }
            ]
        },
        {"warning": "No identifier found."},
    ]

    rows = parse_results(isins, results, {"DK0000000001": "LEI_A", "DK0000000002": "LEI_B"})

    assert rows == [
        {
            "lei": "LEI_A",
            "isin": "DK0000000001",
            "figi": "BBG000000001",
            "ticker": "ABC",
            "name": "ABC A/S",
            "exch_code": "DC",
            "security_type": "Common Stock",
            "market_sector": "Equity",
        }
    ]


def test_latest_lei_isin_picks_newest_ingest_date(tmp_path):
    for day in ["2026-10-01", "2026-10-16"]:
        path = tmp_path / "lei_isin" / f"ingest_date={day}" / "lei_isin.csv"
        path.parent.mkdir(parents=True)
        path.write_text("LEI,ISIN\n")

    assert latest_lei_isin(tmp_path).parent.name == "ingest_date=2026-10-16"


def test_read_lei_by_isin_keeps_only_danish_isins(tmp_path):
    path = tmp_path / "lei_isin.csv"
    path.write_text("LEI,ISIN\nLEI_A,DK0000000001\nLEI_A,US0000000002\n")

    assert read_lei_by_isin(path) == {"DK0000000001": "LEI_A"}


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self.payload


class FigiSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, json, headers, timeout):
        self.posts.append((url, json, headers))
        return self.responses.pop(0)


def test_post_mapping_retries_on_429():
    session = FigiSession([FakeResponse(429), FakeResponse(200, [{"data": []}])])
    sleeps = []

    assert post_mapping(session, [], {}, sleep=sleeps.append) == [{"data": []}]
    assert sleeps == [5]


def test_post_mapping_does_not_retry_on_400():
    session = FigiSession([FakeResponse(400)])

    with pytest.raises(requests.HTTPError):
        post_mapping(session, [], {}, sleep=lambda s: None)
    assert len(session.posts) == 1


def test_post_mapping_413_says_lower_batch_size():
    session = FigiSession([FakeResponse(413)])

    with pytest.raises(RuntimeError, match="lower batch_size"):
        post_mapping(session, [{}] * 10, {}, sleep=lambda s: None)


def test_run_without_key_sends_batches_of_ten_and_no_header(tmp_path):
    source = tmp_path / "lei_isin" / "ingest_date=2026-10-16" / "lei_isin.csv"
    source.parent.mkdir(parents=True)
    lines = [f"LEI_A,DK{i:010d}" for i in range(11)]
    source.write_text("LEI,ISIN\n" + "\n".join(lines) + "\n")
    session = FigiSession(
        [FakeResponse(200, [{"warning": "x"}] * 10), FakeResponse(200, [{"warning": "x"}])]
    )

    run(session, tmp_path, "2026-10-16", sleep=lambda s: None)

    assert [len(jobs) for _, jobs, _ in session.posts] == [10, 1]
    assert session.posts[0][2] == {}


def test_run_writes_csv_then_skips_same_day(tmp_path):
    source = tmp_path / "lei_isin" / "ingest_date=2026-10-16" / "lei_isin.csv"
    source.parent.mkdir(parents=True)
    source.write_text("LEI,ISIN\nLEI_A,DK0000000001\n")
    match = {"data": [{"figi": "BBG1", "ticker": "ABC", "exchCode": "DC"}]}
    session = FigiSession([FakeResponse(200, [match])])

    first = run(session, tmp_path, "2026-10-16", api_key="k", sleep=lambda s: None)
    second = run(session, tmp_path, "2026-10-16", api_key="k", sleep=lambda s: None)

    dest = tmp_path / "openfigi" / "ingest_date=2026-10-16" / "isin_ticker.csv"
    assert first == {
        "status": "written",
        "isins_sent": 1,
        "isins_matched": 1,
        "leis_sent": 1,
        "leis_matched": 1,
        "rows": 1,
    }
    assert second == {"status": "skipped"}
    assert session.posts[0][0] == MAPPING_URL
    assert session.posts[0][2] == {"X-OPENFIGI-APIKEY": "k"}
    assert dest.read_text().splitlines()[1] == "LEI_A,DK0000000001,BBG1,ABC,,DC,,"
