from datetime import date

import pytest

from piotroski.signals import SIGNALS, piotroski_score

COLUMNS = [
    "lei",
    "fiscal_year_end",
    "assets",
    "profit_loss",
    "cfo",
    "noncurrent_liabilities",
    "current_assets",
    "current_liabilities",
    "revenue",
    "gross_profit",
    "cost_of_sales",
    "proceeds_from_issuing_shares",
]
SCHEMA = "lei STRING, fiscal_year_end DATE, " + ", ".join(f"{c} DOUBLE" for c in COLUMNS[2:])
Y23, Y24 = date(2023, 12, 31), date(2024, 12, 31)

# lei, year end, assets, profit, cfo, ncl, ca, cl, revenue, gross profit, cost of sales, proceeds
ROWS = [
    # improves on every signal
    ("ALL9", Y23, 100.0, 5.0, 8.0, 40.0, 50.0, 40.0, 100.0, 30.0, None, None),
    ("ALL9", Y24, 100.0, 10.0, 15.0, 30.0, 60.0, 40.0, 120.0, 40.0, None, None),
    # no GrossProfit tag; margin from revenue - abs(cost of sales), one year signed negative
    ("DERIVED", Y23, 100.0, 5.0, 8.0, 40.0, 50.0, 40.0, 100.0, None, 70.0, None),
    ("DERIVED", Y24, 100.0, 5.0, 8.0, 40.0, 50.0, 40.0, 100.0, None, -60.0, None),
    # no gross profit, no cost of sales; issued shares; current liabilities of 0
    ("NOGP", Y23, 100.0, 5.0, 8.0, 40.0, 50.0, 40.0, 100.0, None, None, None),
    ("NOGP", Y24, 100.0, 5.0, 8.0, 40.0, 50.0, 0.0, 100.0, None, None, 5.0),
    # only one year
    ("FIRST", Y24, 100.0, -5.0, 8.0, 40.0, 50.0, 40.0, 100.0, 30.0, None, None),
    # a missing year in between: no prior year
    ("GAP", date(2022, 12, 31), 100.0, 5.0, 8.0, 40.0, 50.0, 40.0, 100.0, 30.0, None, None),
    ("GAP", Y24, 100.0, 10.0, 15.0, 30.0, 60.0, 40.0, 120.0, 40.0, None, None),
    # no cash-flow statement and no proceeds: equity issuance unknown
    ("NOCF", Y24, 100.0, 5.0, None, 40.0, 50.0, 40.0, 100.0, 30.0, None, None),
    # assets of 0: every ratio on assets is null, not a division error
    ("ZERO", Y23, 100.0, 5.0, 8.0, 40.0, 50.0, 40.0, 100.0, 30.0, None, None),
    ("ZERO", Y24, 0.0, 10.0, 15.0, 30.0, 60.0, 40.0, 120.0, 40.0, None, None),
]


@pytest.fixture(scope="module")
def scores(spark):
    df = piotroski_score(spark.createDataFrame(ROWS, SCHEMA))
    return {(r.lei, r.fiscal_year_end): r for r in df.collect()}


def test_all_nine_met(scores):
    row = scores[("ALL9", Y24)]
    assert [row[s] for s in SIGNALS] == [1] * 9
    assert (row.f_score, row.signals_available, row.data_completeness) == (9, 9, 1.0)


def test_gross_profit_derived_from_abs_cost_of_sales(scores):
    row = scores[("DERIVED", Y24)]
    assert row.margin == pytest.approx(0.4)
    assert row.f_delta_margin == 1


def test_missing_gross_profit_is_null_not_zero(scores):
    row = scores[("NOGP", Y24)]
    assert row.f_delta_margin is None
    assert row.f_delta_liquid is None  # current liabilities of 0
    assert row.signals_available == 7


def test_first_year_has_only_level_signals(scores):
    row = scores[("FIRST", Y24)]
    present = {s for s in SIGNALS if row[s] is not None}
    assert present == {"f_roa", "f_cfo", "f_accrual", "f_eq_offer"}
    assert (row.f_roa, row.f_score, row.signals_available) == (0, 3, 4)


def test_gap_year_is_not_a_prior_year(scores):
    row = scores[("GAP", Y24)]
    assert row.roa_prev is None
    assert row.signals_available == 4


def test_zero_assets_is_null_not_zero(scores):
    row = scores[("ZERO", Y24)]
    assert (row.roa, row.lever, row.turn) == (None, None, None)
    nulls = {s for s in SIGNALS if row[s] is None}
    assert nulls == {"f_roa", "f_delta_roa", "f_delta_lever", "f_delta_turn"}
    assert row.signals_available == 5


@pytest.mark.parametrize(
    ("key", "expected"),
    [(("ALL9", Y24), 1), (("NOGP", Y24), 0), (("NOCF", Y24), None)],
)
def test_eq_offer(scores, key, expected):
    assert scores[key].f_eq_offer == expected
