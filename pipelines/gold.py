from pyspark import pipelines as dp
from pyspark.sql import SparkSession

from piotroski.dq import dq_results
from piotroski.listings import with_listings
from piotroski.signals import piotroski_score

spark = SparkSession.active()


@dp.materialized_view(
    name="gold.piotroski_score",
    comment="Piotroski score per LEI and fiscal year; a null signal means missing input (ADR-005).",
)
def gold_piotroski_score():
    scores = piotroski_score(spark.read.table("silver.fundamentals"))
    return with_listings(scores, spark.read.table("silver.isin_listing"))


@dp.materialized_view(
    name="gold.dq_results",
    comment="One row per DQ rule for the latest run; history in gold.dq_results_history",
)
def gold_dq_results():
    return dq_results(
        spark.read.table("silver.fact"),
        spark.read.table("silver.fundamentals"),
        spark.read.table("gold.piotroski_score"),
        spark.read.table("silver.isin_listing"),
    )
