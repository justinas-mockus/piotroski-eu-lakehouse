from datetime import date
from decimal import Decimal

import pytest
from pyspark.sql import functions as F

from piotroski.fundamentals import (
    annual_filings,
    annual_periods,
    latest_filing,
    pick_scope,
    resolve_duplicates,
    to_wide,
)

END = date(2024, 12, 31)

# (source_file, report_period_end, scope, period_start, period_end)
FACTS = [
    ("annual.json", END, "consolidated", date(2024, 1, 1), END),
    ("annual.json", END, "separate", date(2024, 1, 1), END),
    ("annual.json", END, "consolidated", None, END),
    ("quarter.json", END, "consolidated", date(2024, 10, 1), END),
    # a half-year report carrying last year's full-year figures as comparatives
    ("half.json", date(2024, 6, 30), "consolidated", date(2023, 1, 1), date(2023, 12, 31)),
    ("separate.json", END, "separate", date(2024, 1, 1), END),
]
SCHEMA = (
    "source_file STRING, report_period_end DATE, scope STRING, period_start DATE, period_end DATE"
)


@pytest.fixture(scope="module")
def facts(spark):
    return spark.createDataFrame(FACTS, SCHEMA)


def test_annual_filings_drops_interim_reports(facts):
    assert {r.source_file for r in annual_filings(facts).collect()} == {
        "annual.json",
        "separate.json",
    }


def test_pick_scope_prefers_consolidated(facts):
    kept = {(r.source_file, r.scope) for r in pick_scope(facts).collect()}
    assert ("annual.json", "separate") not in kept
    assert ("separate.json", "separate") in kept


def test_annual_periods_drops_quarters(facts):
    assert date(2024, 10, 1) not in {r.period_start for r in annual_periods(facts).collect()}


# (canonical, period_end, value, decimals, unit)
DUPLICATES = [
    ("revenue", END, Decimal("1000000"), "-3", "iso4217:DKK"),
    ("revenue", END, Decimal("1000400"), "0", "iso4217:DKK"),  # rounding: keep the precise one
    ("assets", END, Decimal("5000"), "0", "iso4217:DKK"),
    ("assets", END, Decimal("5000000"), "-3", "iso4217:DKK"),  # x1000 scale error: conflict
]


@pytest.fixture(scope="module")
def duplicates(spark):
    return spark.createDataFrame(
        DUPLICATES,
        "canonical STRING, period_end DATE, value DECIMAL(38,4), decimals STRING, unit STRING",
    ).withColumns(
        {
            "lei": F.lit("LEI"),
            "source_file": F.lit("a.json"),
            "filing_id": F.lit(1),
            "report_period_end": F.lit(END),
            "ingested_at": F.current_timestamp(),
            "scope": F.lit("consolidated"),
        }
    )


@pytest.fixture(scope="module")
def resolved(duplicates):
    return {r.canonical: r for r in resolve_duplicates(duplicates).collect()}


def test_consistent_duplicates_keep_highest_precision(resolved):
    assert (resolved["revenue"].value, resolved["revenue"].is_conflict) == (
        Decimal("1000400"),
        False,
    )
    assert resolved["revenue"].currency == "DKK"


def test_conflicting_duplicates_become_null(resolved):
    assert (resolved["assets"].value, resolved["assets"].is_conflict) == (None, True)


@pytest.fixture(scope="module")
def wide(duplicates):
    return to_wide(resolve_duplicates(duplicates)).collect()


def test_to_wide_one_row_with_missing_fields_null(wide):
    assert len(wide) == 1
    row = wide[0]
    assert row.revenue == Decimal("1000400")
    assert row.assets is None  # conflict
    assert row.profit_loss is None  # never tagged: null, not 0
    assert (row.fiscal_year_end, row.currency, row.n_conflicts) == (END, "DKK", 1)


# (lei, fiscal_year_end, report_period_end, filing_id, assets)
WIDE = [
    ("LEI", date(2023, 12, 31), date(2023, 12, 31), 1, 100),  # FY2023 report
    ("LEI", date(2023, 12, 31), date(2024, 12, 31), 2, 110),  # restated in the FY2024 report
    ("LEI", date(2023, 12, 31), date(2024, 12, 31), 3, 111),  # FY2024 report filed again
    ("LEI", END, END, 2, 120),
]


def test_latest_filing_wins(spark):
    wide = spark.createDataFrame(
        WIDE,
        "lei STRING, fiscal_year_end DATE, report_period_end DATE, filing_id BIGINT, assets INT",
    )
    kept = {r.fiscal_year_end: r.filing_id for r in latest_filing(wide).collect()}
    assert kept == {date(2023, 12, 31): 3, END: 2}
