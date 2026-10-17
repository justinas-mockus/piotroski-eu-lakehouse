from pyspark import pipelines as dp
from pyspark.sql import SparkSession

from piotroski.xbrl import filing_keys, parse_facts

spark = SparkSession.active()


@dp.table(
    name="silver.fact",
    comment="One row per numeric, non-dimensional xBRL fact, tagged with scope (ADR-009).",
)
def fact():
    return filing_keys(parse_facts(spark.readStream.table("bronze.esef_filing_raw")))
