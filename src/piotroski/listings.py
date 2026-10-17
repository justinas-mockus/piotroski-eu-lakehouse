"""Copenhagen common-stock listings per LEI, one-to-many (ADR-008)."""

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F


def common_stock(listings: DataFrame) -> DataFrame:
    """Latest OpenFIGI snapshot, Nasdaq Copenhagen common stock only."""
    snapshot = F.max("ingest_date").over(Window.partitionBy())
    return (
        listings.where((F.col("security_type") == "Common Stock") & (F.col("exch_code") == "DC"))
        .withColumn("_snapshot", snapshot)
        .where(F.col("ingest_date") == F.col("_snapshot"))
        .select("lei", "isin", "ticker", "name")
        .distinct()
    )


def with_listings(scores: DataFrame, listings: DataFrame) -> DataFrame:
    """Attach all listings of an LEI as an array; an LEI without one keeps its score."""
    per_lei = listings.groupBy("lei").agg(
        F.sort_array(F.collect_list(F.struct("isin", "ticker", "name"))).alias("listings")
    )
    return scores.join(per_lei, "lei", "left")
