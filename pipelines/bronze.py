from pyspark import pipelines as dp
from pyspark.sql import SparkSession

from piotroski.lineage import with_lineage

spark = SparkSession.active()
LANDING_ROOT = spark.conf.get("landing_root")


@dp.table(comment="One row per landed xBRL-JSON file, stored as raw text (ADR-004).")
def esef_filing_raw():
    raw = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "text")
        .option("wholetext", "true")
        .option("pathGlobFilter", "*.json")
        .load(f"{LANDING_ROOT}/esef/")
        .withColumnRenamed("value", "raw_json")
    )
    return with_lineage(raw).select("raw_json", "source_file", "ingest_date", "ingested_at")


def csv_stream(source: str):
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "csv")
        .option("header", "true")
        .option("pathGlobFilter", "*.csv")
        .option("cloudFiles.inferColumnTypes", "false")
        .load(f"{LANDING_ROOT}/{source}/")
    )


@dp.table(comment="GLEIF LEI-ISIN pairs for ESEF filers, one row per pair per snapshot.")
def lei_isin():
    return with_lineage(csv_stream("lei_isin")).withColumnsRenamed({"LEI": "lei", "ISIN": "isin"})


@dp.table(comment="OpenFIGI Copenhagen listings per ISIN, unfiltered (ADR-008).")
def isin_listing():
    return with_lineage(csv_stream("openfigi"))
