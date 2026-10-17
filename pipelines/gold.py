from pyspark import pipelines as dp
from pyspark.sql import SparkSession

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
