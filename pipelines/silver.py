from pyspark import pipelines as dp
from pyspark.sql import SparkSession

from piotroski.fundamentals import fundamentals
from piotroski.listings import common_stock
from piotroski.xbrl import filing_keys, parse_facts

spark = SparkSession.active()


@dp.table(
    name="silver.fact",
    comment="One row per numeric, non-dimensional xBRL fact, tagged with scope (ADR-009).",
)
def fact():
    return filing_keys(parse_facts(spark.readStream.table("bronze.esef_filing_raw")))


@dp.materialized_view(
    name="silver.fundamentals",
    comment="One row per LEI and fiscal year end; newest annual filing wins (ADR-007, ADR-009).",
)
@dp.expect_all_or_drop(
    {
        "currency_is_iso": "currency RLIKE '^[A-Z]{3}$'",
        "fiscal_year_in_range": "fiscal_year BETWEEN 2015 AND 2026",
        "assets_positive_or_missing": "assets IS NULL OR assets > 0",
    }
)
def silver_fundamentals():
    return fundamentals(spark.read.table("silver.fact"))


@dp.materialized_view(
    name="silver.isin_listing",
    comment="Nasdaq Copenhagen common-stock listings, latest OpenFIGI snapshot (ADR-008).",
)
def silver_isin_listing():
    return common_stock(spark.read.table("bronze.isin_listing"))
