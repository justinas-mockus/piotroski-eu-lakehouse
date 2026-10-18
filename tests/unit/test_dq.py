import json
from datetime import datetime

import pytest

from piotroski.dq import (
    balance_identity,
    dq_history,
    dq_results,
    expectation_drops,
    listing_coverage,
    unmapped_leis,
)

FUNDAMENTALS_SCHEMA = (
    "lei STRING, fiscal_year INT, assets DOUBLE, equity DOUBLE, liabilities DOUBLE, n_conflicts INT"
)
FUNDAMENTALS = [
    ("OK", 2024, 100.0, 40.0, 60.0, 0),
    ("ROUNDING", 2024, 100.0, 40.0, 59.5, 0),  # 0.5% off: within tolerance
    ("BROKEN", 2024, 100.0, 40.0, 58.0, 1),  # 2% off
    ("NEGEQ", 2024, 100.0, -20.0, 120.0, 0),  # negative equity still balances
    ("NOLIAB", 2024, 100.0, 40.0, None, 0),  # missing side: not checked
]


@pytest.fixture(scope="module")
def frames(spark):
    fundamentals = spark.createDataFrame(FUNDAMENTALS, FUNDAMENTALS_SCHEMA)
    facts = spark.createDataFrame(
        [(lei,) for lei in ["OK", "ROUNDING", "BROKEN", "NEGEQ", "NOLIAB", "INTERIM"]], "lei STRING"
    )
    scores = spark.createDataFrame(
        [("OK", 2024, 9), ("BROKEN", 2024, 4)], "lei STRING, fiscal_year INT, signals_available INT"
    )
    listings = spark.createDataFrame([("OK",), ("NEGEQ",)], "lei STRING")
    return facts, fundamentals, scores, listings


def test_balance_identity_tolerance_and_missing_side(frames):
    _, fundamentals, _, _ = frames
    row = balance_identity(fundamentals).first()
    assert (row.checked, row.failed, row.details) == (4, 1, ["BROKEN:2024"])
    assert row.pct_failed == 25.0


def test_unmapped_leis_lists_esef_leis_without_fundamentals(frames):
    facts, fundamentals, _, _ = frames
    row = unmapped_leis(facts, fundamentals).first()
    assert (row.checked, row.failed, row.details) == (6, 1, ["INTERIM"])


def test_listing_coverage_lists_misses(frames):
    facts, _, _, listings = frames
    row = listing_coverage(facts, listings).first()
    assert (row.checked, row.failed) == (6, 4)
    assert "OK" not in row.details


def test_dq_results_has_one_row_per_rule(frames):
    rows = {r.rule: r for r in dq_results(*frames).collect()}
    assert set(rows) == {
        "balance_identity",
        "duplicate_conflicts",
        "all_signals_available",
        "unmapped_leis",
        "listing_coverage",
    }
    assert rows["duplicate_conflicts"].details == ["BROKEN:2024"]
    assert rows["all_signals_available"].failed == 1


LOG_SCHEMA = (
    "event_type STRING, timestamp TIMESTAMP, origin STRUCT<update_id: STRING>, details STRING"
)


def _progress(update, hour, expectations):
    details = {
        "flow_progress": {"status": "COMPLETED", "data_quality": {"expectations": expectations}}
    }
    return ("flow_progress", datetime(2026, 10, 18, hour), (update,), json.dumps(details))


def _exp(name, passed, failed):
    return {
        "name": name,
        "dataset": "piotroski_dev.silver.fundamentals",
        "passed_records": passed,
        "failed_records": failed,
    }


def test_expectation_drops_uses_latest_update_only(spark):
    no_dq = json.dumps({"flow_progress": {"status": "COMPLETED"}})
    log = spark.createDataFrame(
        [
            _progress("old", 1, [_exp("assets_positive", 90, 10)]),
            _progress("new", 2, [_exp("assets_positive", 98, 2), _exp("currency_is_iso", 100, 0)]),
            ("flow_progress", datetime(2026, 10, 18, 3), ("new",), no_dq),
            ("user_code_context", datetime(2026, 10, 18, 4), ("new",), "{}"),
        ],
        LOG_SCHEMA,
    )
    rows = {r.rule: r for r in expectation_drops(log).collect()}
    assert set(rows) == {
        "expectation:silver.fundamentals:assets_positive",
        "expectation:silver.fundamentals:currency_is_iso",
    }
    r = rows["expectation:silver.fundamentals:assets_positive"]
    assert (r.checked, r.failed, r.pct_failed, r.details) == (100, 2, 2.0, [])


def test_dq_history_unions_and_tags_run(spark, frames):
    log = spark.createDataFrame([_progress("u", 1, [_exp("assets_positive", 9, 1)])], LOG_SCHEMA)
    rows = dq_history(dq_results(*frames), log, "123").collect()
    assert len(rows) == 6  # 5 rules + 1 expectation
    assert {r.run_id for r in rows} == {"123"}
