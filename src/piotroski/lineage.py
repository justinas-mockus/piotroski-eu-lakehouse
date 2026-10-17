from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

INGEST_DATE_PATTERN = r"ingest_date=(\d{4}-\d{2}-\d{2})"


def ingest_date(path: Column) -> Column:
    """Date from the `ingest_date=YYYY-MM-DD` path folder; null if absent or invalid."""
    return F.try_to_date(F.regexp_extract(path, INGEST_DATE_PATTERN, 1))


def with_lineage(df: DataFrame) -> DataFrame:
    """Add source_file, ingest_date and ingested_at from Auto Loader's `_metadata` column."""
    return (
        df.withColumn("source_file", F.col("_metadata.file_path"))
        .withColumn("ingest_date", ingest_date(F.col("_metadata.file_path")))
        .withColumn("ingested_at", F.current_timestamp())
    )
