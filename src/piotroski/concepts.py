"""IFRS concept -> canonical Piotroski field (PLAN Day 4, ADR-007)."""

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

# Canonical field -> ifrs-full concepts in priority order; the first one present wins.
# Balance-sheet fields only match instant facts, flow fields only duration facts.
BALANCE_SHEET: dict[str, list[str]] = {
    "assets": ["ifrs-full:Assets"],
    "current_assets": ["ifrs-full:CurrentAssets"],
    "current_liabilities": ["ifrs-full:CurrentLiabilities"],
    "noncurrent_liabilities": ["ifrs-full:NoncurrentLiabilities"],
    "liabilities": ["ifrs-full:Liabilities"],
    "equity": ["ifrs-full:Equity"],
}
FLOWS: dict[str, list[str]] = {
    "revenue": ["ifrs-full:Revenue", "ifrs-full:RevenueFromContractsWithCustomers"],
    "gross_profit": ["ifrs-full:GrossProfit"],
    "cost_of_sales": ["ifrs-full:CostOfSales"],
    "profit_loss": ["ifrs-full:ProfitLoss"],
    "cfo": ["ifrs-full:CashFlowsFromUsedInOperatingActivities"],
    "proceeds_from_issuing_shares": ["ifrs-full:ProceedsFromIssuingShares"],
}
CANONICAL: dict[str, list[str]] = {**BALANCE_SHEET, **FLOWS}


def concept_map(spark: SparkSession) -> DataFrame:
    """One row per (canonical, concept) with its priority (0 = best) and period type."""
    rows = [
        (canonical, concept, priority, canonical in BALANCE_SHEET)
        for canonical, concepts in CANONICAL.items()
        for priority, concept in enumerate(concepts)
    ]
    return spark.createDataFrame(
        rows, "canonical STRING, concept STRING, priority INT, is_instant BOOLEAN"
    )


def map_concepts(facts: DataFrame) -> DataFrame:
    """Tag facts with their canonical field, keeping only the best-priority concept per period.

    Ties survive on purpose: duplicates of the winning concept are resolved later (ADR-009 rule 6).
    """
    mapping = F.broadcast(concept_map(facts.sparkSession))
    period = Window.partitionBy("source_file", "scope", "canonical", "period_start", "period_end")
    return (
        facts.join(mapping, "concept")
        .where(F.col("period_start").isNull() == F.col("is_instant"))
        .withColumn("best_priority", F.min("priority").over(period))
        .where(F.col("priority") == F.col("best_priority"))
        .drop("best_priority", "is_instant")
    )
