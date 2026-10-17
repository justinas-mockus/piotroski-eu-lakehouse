import pytest

from piotroski.dq import balance_identity, dq_results, listing_coverage, unmapped_leis

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
