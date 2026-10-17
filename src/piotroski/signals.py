"""The 9 Piotroski signals as 1 / 0 / null (ADR-005)."""

from pyspark.sql import Column, DataFrame, Window
from pyspark.sql import functions as F

from piotroski.fundamentals import ANNUAL_DAYS

RATIOS = ["roa", "lever", "liquid", "margin", "turn"]
SIGNALS = [
    "f_roa",
    "f_cfo",
    "f_delta_roa",
    "f_accrual",
    "f_delta_lever",
    "f_delta_liquid",
    "f_eq_offer",
    "f_delta_margin",
    "f_delta_turn",
]


def _ratio(num: Column, den: Column) -> Column:
    """num / den, null when the denominator is null or 0 (ANSI mode raises on division by 0)."""
    return F.when(den != 0, num / den)


def _flag(condition: Column) -> Column:
    """1 when true, 0 when false, null when the condition is null (ADR-005)."""
    return F.when(condition, 1).when(~condition, 0)


def with_ratios(fundamentals: DataFrame) -> DataFrame:
    """Add the ratios behind the change signals, all on end-of-year assets (ADR-005)."""
    gross_profit = F.coalesce("gross_profit", F.col("revenue") - F.abs("cost_of_sales"))
    return fundamentals.withColumns(
        {
            "roa": _ratio(F.col("profit_loss"), F.col("assets")),
            "lever": _ratio(F.col("noncurrent_liabilities"), F.col("assets")),
            "liquid": _ratio(F.col("current_assets"), F.col("current_liabilities")),
            "margin": _ratio(gross_profit, F.col("revenue")),
            "turn": _ratio(F.col("revenue"), F.col("assets")),
        }
    )


def with_prior_year(ratios: DataFrame) -> DataFrame:
    """Add <ratio>_prev from the previous fiscal year, null after a gap or in the first year."""
    by_year = Window.partitionBy("lei").orderBy("fiscal_year_end")
    prev_end = F.lag("fiscal_year_end").over(by_year)
    is_prior = F.datediff("fiscal_year_end", prev_end).between(*ANNUAL_DAYS)
    return ratios.withColumns(
        {f"{name}_prev": F.when(is_prior, F.lag(name).over(by_year)) for name in RATIOS}
    )


def with_signals(prior: DataFrame) -> DataFrame:
    """Add the 9 signals. Equity issuance follows ADR-007 rule 2."""
    proceeds = F.col("proceeds_from_issuing_shares")
    return prior.withColumns(
        {
            "f_roa": _flag(F.col("roa") > 0),
            "f_cfo": _flag(F.col("cfo") > 0),
            "f_delta_roa": _flag(F.col("roa") > F.col("roa_prev")),
            "f_accrual": _flag(F.col("cfo") > F.col("profit_loss")),
            "f_delta_lever": _flag(F.col("lever") < F.col("lever_prev")),
            "f_delta_liquid": _flag(F.col("liquid") > F.col("liquid_prev")),
            "f_eq_offer": F.when(proceeds > 0, 0).when(
                proceeds.isNotNull() | F.col("cfo").isNotNull(), 1
            ),
            "f_delta_margin": _flag(F.col("margin") > F.col("margin_prev")),
            "f_delta_turn": _flag(F.col("turn") > F.col("turn_prev")),
        }
    )


def piotroski_score(fundamentals: DataFrame) -> DataFrame:
    """silver.fundamentals -> signals, f_score (sum of non-null) and signals_available."""
    available = sum(F.col(name).isNotNull().cast("int") for name in SIGNALS)
    return with_signals(with_prior_year(with_ratios(fundamentals))).withColumns(
        {
            "f_score": sum(F.coalesce(F.col(name), F.lit(0)) for name in SIGNALS),
            "signals_available": available,
            "data_completeness": F.round(available / 9, 2),
        }
    )
