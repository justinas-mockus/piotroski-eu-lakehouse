"""Data-quality rules for gold.dq_results: one row per rule (PLAN testing strategy, ADR-009)."""

from functools import reduce

from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

IDENTITY_TOLERANCE = 0.01


def _lei_year() -> Column:
    return F.concat_ws(":", "lei", "fiscal_year")


def _rule(name: str, rows: DataFrame, failed: Column, key: Column) -> DataFrame:
    """Count rows checked and failed; details lists the keys of the failed rows."""
    return rows.agg(
        F.lit(name).alias("rule"),
        F.count("*").alias("checked"),
        F.count_if(failed).alias("failed"),
        F.sort_array(F.collect_list(F.when(failed, key))).alias("details"),
    ).withColumn("pct_failed", F.round(100 * F.col("failed") / F.nullif("checked", F.lit(0)), 2))


def balance_identity(fundamentals: DataFrame) -> DataFrame:
    """Assets = Equity + Liabilities within 1%; rows with a missing side are not checked."""
    rows = fundamentals.where(
        "assets IS NOT NULL AND equity IS NOT NULL AND liabilities IS NOT NULL"
    )
    gap = F.abs(F.col("assets") - F.col("equity") - F.col("liabilities"))
    return _rule("balance_identity", rows, gap > IDENTITY_TOLERANCE * F.col("assets"), _lei_year())


def duplicate_conflicts(fundamentals: DataFrame) -> DataFrame:
    """LEI-years with a conflicting duplicate nulled in silver (ADR-009 rule 6)."""
    return _rule("duplicate_conflicts", fundamentals, F.col("n_conflicts") > 0, _lei_year())


def all_signals_available(scores: DataFrame) -> DataFrame:
    """LEI-years scored on fewer than 9 signals (ADR-005)."""
    return _rule("all_signals_available", scores, F.col("signals_available") < 9, _lei_year())


def _leis_matched(leis: DataFrame, other: DataFrame) -> DataFrame:
    matched = other.select("lei").distinct().withColumn("matched", F.lit(True))
    return leis.select("lei").distinct().join(matched, "lei", "left")


def unmapped_leis(facts: DataFrame, fundamentals: DataFrame) -> DataFrame:
    """ESEF LEIs with no row in silver.fundamentals (interim-only filers, expectation drops)."""
    rows = _leis_matched(facts, fundamentals)
    return _rule("unmapped_leis", rows, F.col("matched").isNull(), F.col("lei"))


def listing_coverage(facts: DataFrame, listings: DataFrame) -> DataFrame:
    """ESEF LEIs without a Nasdaq Copenhagen common-stock listing (ADR-008)."""
    rows = _leis_matched(facts, listings)
    return _rule("listing_coverage", rows, F.col("matched").isNull(), F.col("lei"))


def dq_results(
    facts: DataFrame, fundamentals: DataFrame, scores: DataFrame, listings: DataFrame
) -> DataFrame:
    """All rules as one table, stamped with the time of the run."""
    rules = [
        balance_identity(fundamentals),
        duplicate_conflicts(fundamentals),
        all_signals_available(scores),
        unmapped_leis(facts, fundamentals),
        listing_coverage(facts, listings),
    ]
    return reduce(DataFrame.unionByName, rules).withColumn("computed_at", F.current_timestamp())
