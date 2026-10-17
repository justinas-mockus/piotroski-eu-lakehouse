import json
from datetime import date

import pytest
from pyspark.sql import functions as F

from piotroski.xbrl import parse_facts

NS = {"ifrs_full": "https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-full"}
LEI = "LEI0000000000000TEST"
SCOPE_AXIS = "ifrs_full:ConsolidatedAndSeparateFinancialStatementsAxis"
FY2024 = "2024-01-01T00:00:00/2025-01-01T00:00:00"
END_2024 = "2025-01-01T00:00:00"


def fact(concept, period, value, unit="iso4217:DKK", axes=None):
    dims = {"concept": concept, "entity": f"scheme:{LEI}", "period": period, **(axes or {})}
    if unit:
        dims["unit"] = unit
    return {"value": value, "decimals": "-3", "dimensions": dims}


FACTS = {
    "assets": fact("ifrs_full:Assets", END_2024, "1000"),
    "profit_separate": fact(
        "ifrs_full:ProfitLoss", FY2024, "100", axes={SCOPE_AXIS: "ifrs_full:SeparateMember"}
    ),
    "equity_component": fact(
        "ifrs_full:Equity",
        END_2024,
        "500",
        axes={"ifrs_full:ComponentsOfEquityAxis": "ifrs_full:RetainedEarningsMember"},
    ),
    "entity_name": fact("ifrs_full:NameOfReportingEntity", FY2024, "Test A/S", unit=None),
}


@pytest.fixture(scope="module")
def parsed(spark):
    doc = json.dumps({"documentInfo": {"namespaces": NS}, "facts": FACTS})
    bronze = spark.createDataFrame(
        [("x.json", doc)], "source_file string, raw_json string"
    ).withColumn("ingested_at", F.current_timestamp())
    return {row.fact_id: row for row in parse_facts(bronze).collect()}


def test_keeps_only_numeric_non_dimensional_facts(parsed):
    assert set(parsed) == {"assets", "profit_separate"}


def test_resolves_prefix_and_lei(parsed):
    assert parsed["assets"].concept == "ifrs-full:Assets"
    assert parsed["assets"].lei == LEI


def test_periods_use_next_day_midnight(parsed):
    assert (parsed["assets"].period_start, parsed["assets"].period_end) == (
        None,
        date(2024, 12, 31),
    )
    profit = parsed["profit_separate"]
    assert (profit.period_start, profit.period_end) == (date(2024, 1, 1), date(2024, 12, 31))


def test_scope_from_axis(parsed):
    assert parsed["assets"].scope == "consolidated"
    assert parsed["profit_separate"].scope == "separate"
