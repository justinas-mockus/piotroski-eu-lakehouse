from datetime import date

from piotroski.listings import common_stock, with_listings

OLD, NEW = date(2026, 10, 1), date(2026, 10, 16)
SCHEMA = "lei STRING, isin STRING, ticker STRING, name STRING, exch_code STRING, "
SCHEMA += "security_type STRING, ingest_date DATE"

LISTINGS = [
    # dual-class issuer: two common-stock listings
    ("DUAL", "DK0000000001", "CARLA", "Carlsberg A", "DC", "Common Stock", NEW),
    ("DUAL", "DK0000000002", "CARLB", "Carlsberg B", "DC", "Common Stock", NEW),
    ("DUAL", "DK0000000003", "CARLP", "Carlsberg Pref", "DC", "Preference", NEW),
    ("FUND", "DK0000000004", "FUND", "Some Fund", "DC", "Open-End Fund", NEW),
    # only in an older snapshot
    ("GONE", "DK0000000005", "GONE", "Delisted", "DC", "Common Stock", OLD),
]


def test_common_stock_keeps_latest_snapshot_common_stock(spark):
    rows = common_stock(spark.createDataFrame(LISTINGS, SCHEMA)).collect()
    assert sorted(r.ticker for r in rows) == ["CARLA", "CARLB"]


def test_with_listings_is_one_row_per_score(spark):
    listings = common_stock(spark.createDataFrame(LISTINGS, SCHEMA))
    scores = spark.createDataFrame([("DUAL", 2024), ("NONE", 2024)], "lei STRING, fiscal_year INT")
    rows = {r.lei: r for r in with_listings(scores, listings).collect()}
    assert len(rows) == 2
    assert [x.ticker for x in rows["DUAL"].listings] == ["CARLA", "CARLB"]
    assert rows["NONE"].listings is None
