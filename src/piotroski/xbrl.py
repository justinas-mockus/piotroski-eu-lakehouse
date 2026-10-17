from pyspark.sql import Column, DataFrame
from pyspark.sql import functions as F

FILE_NAME_PATTERN = r"_(\d{4}-\d{2}-\d{2})_(\d+)\.json$"

FACTS_SCHEMA = """STRUCT<
  documentInfo: STRUCT<namespaces: MAP<STRING, STRING>>,
  facts: MAP<STRING, STRUCT<value: STRING, decimals: STRING, dimensions: MAP<STRING, STRING>>>>"""
CORE_DIMENSIONS = ["concept", "entity", "period", "unit", "language"]
SCOPE_AXIS = ":ConsolidatedAndSeparateFinancialStatementsAxis"


def _is_scope_axis(key: Column, _value: Column) -> Column:
    return key.endswith(SCOPE_AXIS)


def _date(timestamp: Column) -> Column:
    """`yyyy-MM-dd` from an xBRL-JSON timestamp like `2025-01-01T00:00:00`."""
    return F.to_date(F.substring(timestamp, 1, 10))


def parse_facts(bronze: DataFrame) -> DataFrame:
    """One row per numeric, non-dimensional fact (ADR-009 rules 1, 2, 5), tagged with its scope."""
    parsed = bronze.select(
        "source_file", "ingested_at", F.from_json("raw_json", FACTS_SCHEMA).alias("doc")
    )
    facts = parsed.select(
        "source_file",
        "ingested_at",
        F.col("doc.documentInfo.namespaces").alias("ns"),
        F.explode("doc.facts").alias("fact_id", "fact"),
    )

    dims = F.col("fact.dimensions")
    concept, period = dims["concept"], dims["period"]
    is_ifrs = F.try_element_at("ns", F.substring_index(concept, ":", 1)).endswith("/ifrs-full")
    member = F.try_element_at(F.map_values(F.map_filter(dims, _is_scope_axis)), F.lit(1))
    other_keys = F.map_keys(F.map_filter(dims, lambda k, v: ~_is_scope_axis(k, v)))
    extra = F.array_except(other_keys, F.array(*[F.lit(d) for d in CORE_DIMENSIONS]))
    start = F.when(period.contains("/"), _date(F.substring_index(period, "/", 1)))
    end = F.date_sub(_date(F.substring_index(period, "/", -1)), 1)

    return (
        facts.where(F.size(extra) == 0)
        .select(
            "source_file",
            "ingested_at",
            "fact_id",
            F.substring_index(dims["entity"], ":", -1).alias("lei"),
            F.when(is_ifrs, F.concat(F.lit("ifrs-full:"), F.substring_index(concept, ":", -1)))
            .otherwise(concept)
            .alias("concept"),
            dims["unit"].alias("unit"),
            start.alias("period_start"),
            end.alias("period_end"),
            F.col("fact.value").try_cast("decimal(38,4)").alias("value"),
            F.col("fact.decimals").alias("decimals"),
            F.when(member.isNull() | member.endswith(":ConsolidatedMember"), "consolidated")
            .when(member.endswith(":SeparateMember"), "separate")
            .alias("scope"),
        )
        .where(F.col("unit").isNotNull() & F.col("value").isNotNull() & F.col("scope").isNotNull())
    )


def filing_keys(df: DataFrame) -> DataFrame:
    """Add report_period_end and filing_id from `{lei}_{period_end}_{filing_id}.json` (ADR-009)."""
    path = F.col("source_file")
    return df.withColumns(
        {
            "report_period_end": F.try_to_date(F.regexp_extract(path, FILE_NAME_PATTERN, 1)),
            "filing_id": F.regexp_extract(path, FILE_NAME_PATTERN, 2).try_cast("bigint"),
        }
    )
