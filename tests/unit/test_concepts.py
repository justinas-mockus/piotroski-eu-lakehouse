from datetime import date

import pytest
from pyspark.sql import functions as F

from piotroski.concepts import map_concepts

FY_START, FY_END = date(2024, 1, 1), date(2024, 12, 31)

# (source_file, concept, period_start, period_end)
FACTS = [
    # a.json: only the fallback revenue concept, and no ProfitLoss at all
    ("a.json", "ifrs-full:RevenueFromContractsWithCustomers", FY_START, FY_END),
    # b.json: both revenue concepts, with Revenue tagged twice (a duplicate)
    ("b.json", "ifrs-full:Revenue", FY_START, FY_END),
    ("b.json", "ifrs-full:Revenue", FY_START, FY_END),
    ("b.json", "ifrs-full:RevenueFromContractsWithCustomers", FY_START, FY_END),
    ("b.json", "ifrs-full:ProfitLoss", FY_START, FY_END),
    # Assets as a duration (wrong period type) and an unmapped concept
    ("b.json", "ifrs-full:Assets", FY_START, FY_END),
    ("b.json", "ifrs-full:ProfitLossBeforeTax", FY_START, FY_END),
]


@pytest.fixture(scope="module")
def mapped(spark):
    facts = spark.createDataFrame(
        FACTS, "source_file STRING, concept STRING, period_start DATE, period_end DATE"
    ).withColumn("scope", F.lit("consolidated"))
    return [(r.source_file, r.canonical, r.concept) for r in map_concepts(facts).collect()]


def test_falls_back_to_second_concept(mapped):
    assert ("a.json", "revenue", "ifrs-full:RevenueFromContractsWithCustomers") in mapped


def test_missing_concept_gives_no_row_not_zero(mapped):
    assert [m for m in mapped if m[:2] == ("a.json", "profit_loss")] == []


def test_first_concept_wins_and_duplicates_survive(mapped):
    revenue_b = [m for m in mapped if m[:2] == ("b.json", "revenue")]
    assert revenue_b == [("b.json", "revenue", "ifrs-full:Revenue")] * 2


def test_drops_wrong_period_type_and_unmapped_concepts(mapped):
    assert {m[2] for m in mapped} == {
        "ifrs-full:Revenue",
        "ifrs-full:RevenueFromContractsWithCustomers",
        "ifrs-full:ProfitLoss",
    }
