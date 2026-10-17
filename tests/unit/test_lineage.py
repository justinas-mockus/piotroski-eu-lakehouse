from datetime import date

from piotroski.lineage import with_lineage

LANDING = "/Volumes/c/bronze/landing/esef"


def lineage_row(spark, path):
    df = spark.createDataFrame([((path,),)], "_metadata struct<file_path: string>")
    return with_lineage(df).first()


def test_ingest_date_from_folder(spark):
    row = lineage_row(spark, f"{LANDING}/ingest_date=2026-10-16/x.json")
    assert row.ingest_date == date(2026, 10, 16)
    assert row.source_file.endswith("/x.json")


def test_ingest_date_null_without_folder(spark):
    assert lineage_row(spark, f"{LANDING}/x.json").ingest_date is None


def test_ingest_date_null_when_invalid(spark):
    assert lineage_row(spark, f"{LANDING}/ingest_date=2026-13-40/x.json").ingest_date is None
