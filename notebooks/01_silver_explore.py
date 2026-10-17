# Databricks notebook source

# COMMAND ----------
from pyspark.sql import functions as F

raw = spark.table("piotroski_dev.bronze.esef_filing_raw")
path = (raw.where(F.length("raw_json").between(100_000, 200_000))
           .select("source_file").orderBy("source_file").first()["source_file"])
sample = raw.where(F.col("source_file") == path)
print(path.rsplit("/", 1)[-1])
sample.select(F.json_object_keys("raw_json").alias("top_keys")).show(truncate=False)


# COMMAND ----------
schema = """STRUCT<
  documentInfo: STRUCT<documentType: STRING, namespaces: MAP<STRING, STRING>>,
  facts: MAP<STRING, STRUCT<value: STRING, decimals: STRING, dimensions: MAP<STRING, STRING>>>>"""

doc = sample.select("source_file", F.from_json("raw_json", schema).alias("doc"))
doc.select("doc.documentInfo.documentType",
           F.col("doc.documentInfo.namespaces")["ifrs-full"].alias("ifrs_ns")).show(truncate=False)
facts = doc.select("source_file", F.explode("doc.facts").alias("fact_id", "fact"))
print(facts.count())


# COMMAND ----------
(facts.select(F.explode(F.map_keys("fact.dimensions")).alias("dim"))
      .groupBy("dim").count().orderBy(F.desc("count")).show(40, truncate=False))


# COMMAND ----------
(facts.where(F.col("fact.dimensions")["concept"] == "ifrs-full:Assets")
      .select("fact.value", "fact.decimals", "fact.dimensions").show(truncate=False))


# COMMAND ----------
dims = F.col("fact.dimensions")
facts.groupBy(dims["period"].contains("/").alias("is_duration")).count().show()
facts.groupBy("fact.decimals").count().show()

core = F.array(*[F.lit(k) for k in ["concept", "entity", "period", "unit", "language"]])
nondim = facts.where(F.size(F.array_except(F.map_keys(dims), core)) == 0)
(nondim.groupBy(dims["concept"], dims["period"], dims["unit"]).count()
       .where("count > 1").show(truncate=False))

# COMMAND ----------
from pyspark.sql import Window

docs = raw.select("source_file", F.from_json("raw_json", schema)["facts"].alias("facts"))
all_facts = docs.select("source_file", F.explode("facts").alias("fact_id", "fact"))

csfs = lambda k, v: k.endswith(":ConsolidatedAndSeparateFinancialStatementsAxis")
member = F.try_element_at(F.map_values(F.map_filter(dims, csfs)), F.lit(1))
scope = (F.when(member.isNull() | member.endswith(":ConsolidatedMember"), "consolidated")
          .when(member.endswith(":SeparateMember"), "separate"))
extra_keys = F.array_except(F.map_keys(F.map_filter(dims, lambda k, v: ~csfs(k, v))), core)

by_file = Window.partitionBy("source_file")
all_nondim = (all_facts.withColumn("scope", scope)
    .where((F.size(extra_keys) == 0) & F.col("scope").isNotNull())
    .withColumn("has_consolidated", F.max((F.col("scope") == "consolidated").cast("int")).over(by_file))
    .where((F.col("scope") == "consolidated") | (F.col("has_consolidated") == 0)))

conflicts = (all_nondim
    .groupBy("source_file", dims["concept"].alias("concept"),
             dims["period"].alias("period"), dims["unit"].alias("unit"))
    .agg(F.countDistinct(F.col("fact.value").try_cast("decimal(38,4)")).alias("n_values"))
    .where("n_values > 1"))
print(all_nondim.count(), conflicts.count(), conflicts.select("source_file").distinct().count())
all_nondim.groupBy("scope").agg(F.countDistinct("source_file").alias("files")).show()

val = F.col("fact.value").try_cast("decimal(38,4)")
detail = (all_nondim
    .groupBy("source_file", dims["concept"].alias("concept"),
             dims["period"].alias("period"), dims["unit"].alias("unit"))
    .agg(F.collect_set(F.struct(val.alias("v"), F.col("fact.decimals").alias("d"))).alias("vals"),
         F.countDistinct(val).alias("n"))
    .where("n > 1"))


# COMMAND ----------
vs = F.transform("vals", lambda x: x["v"])
abs_vs = F.transform("vals", lambda x: F.abs(x["v"]))
kind = (F.when(F.array_max(abs_vs) == F.array_min(abs_vs), "sign")
         .when(F.array_max(vs) - F.array_min(vs) <= F.array_max(abs_vs) * 0.005, "rounding")
         .otherwise("other"))
classified = detail.withColumn("kind", kind)
classified.groupBy("kind").count().show()
(classified.where("kind = 'other'")
    .select(F.substring_index("source_file", "/", -1).alias("file"), "concept", "period", "vals")
    .show(10, truncate=False))


# COMMAND ----------
d10 = lambda c: F.to_date(F.substring(c, 1, 10))
start = d10(F.substring_index(dims["period"], "/", 1))
end = F.date_sub(d10(F.substring_index(dims["period"], "/", -1)), 1)
report_end = F.to_date(F.regexp_extract("source_file", r"_(\d{4}-\d{2}-\d{2})_\d+\.json$", 1))

annual_files = (all_nondim.where(dims["period"].contains("/"))
    .where((end == report_end) & F.datediff(end, start).between(330, 400))
    .select("source_file").distinct())
multi_entity = (all_nondim.groupBy("source_file")
    .agg(F.countDistinct(dims["entity"]).alias("n")).where("n > 1"))
print("files", raw.count(), "annual", annual_files.count(), "multi-entity", multi_entity.count())

KEY = ["Assets", "ProfitLoss", "CashFlowsFromUsedInOperatingActivities", "CurrentAssets",
       "CurrentLiabilities", "NoncurrentLiabilities", "Revenue", "GrossProfit", "CostOfSales",
       "ProceedsFromIssuingShares", "Equity", "Liabilities"]
key_conflicts = (classified.join(annual_files, "source_file")
    .where(F.col("concept").startswith("ifrs") & F.substring_index("concept", ":", -1).isin(KEY)))
key_conflicts.groupBy("kind").count().show()
(key_conflicts.where("kind = 'other'")
    .select(F.substring_index("source_file", "/", -1).alias("file"), "concept", "period", "vals")
    .show(20, truncate=False))


# COMMAND ----------
dur = F.datediff(end, start)
per_file = (all_nondim.where(dims["period"].contains("/") & (end == report_end))
    .groupBy("source_file").agg(F.max(dur).alias("max_days")))
excluded = (raw.select("source_file")
    .join(annual_files, "source_file", "left_anti")
    .join(per_file, "source_file", "left"))

bucket = (F.when(F.col("max_days").isNull(), "a: no duration ends on report_end")
           .when(F.col("max_days") < 100, "b: <100 days (quarter)")
           .when(F.col("max_days") < 200, "c: 100-199 (half year)")
           .when(F.col("max_days") < 330, "d: 200-329 (9 months)")
           .otherwise("e: >400 (long year)"))
excluded.groupBy(bucket.alias("bucket")).count().orderBy("bucket").show(truncate=False)

(all_nondim.join(excluded.where("max_days IS NULL").select("source_file"), "source_file")
    .where(dims["period"].contains("/"))
    .groupBy(F.substring_index("source_file", "/", -1).alias("file"))
    .agg(F.max(end).alias("latest_duration_end"))
    .show(5, truncate=False))


# COMMAND ----------
a_files = excluded.where("max_days IS NULL").select("source_file")
check = (raw.join(a_files, "source_file")
    .select(F.length("raw_json").alias("bytes"),
            F.from_json("raw_json", schema)["facts"].alias("facts"))
    .select("bytes", F.col("facts").isNull().alias("parse_null"), F.size("facts").alias("n_facts")))
(check.groupBy("parse_null")
    .agg(F.count("*").alias("files"), F.min("bytes"), F.max("bytes"), F.max("n_facts"))
    .show())


# COMMAND ----------
a_facts = all_facts.join(a_files, "source_file")
(a_facts.select(F.explode(F.map_keys(dims)).alias("dim"))
    .groupBy("dim").count().orderBy(F.desc("count")).show(15, truncate=False))
a_facts.groupBy(dims["period"].contains("/").alias("is_duration")).count().show()


# COMMAND ----------
csfs = lambda k, v: k.endswith(":ConsolidatedAndSeparateFinancialStatementsAxis")
(a_facts.select(F.map_values(F.map_filter(dims, csfs))[0].alias("member"))
    .groupBy("member").count().show(truncate=False))


# COMMAND ----------
fact = spark.table("piotroski_dev.silver.fact")
fact.agg(F.count("*").alias("rows"), F.countDistinct("source_file").alias("files"),
         F.sum(F.col("filing_id").isNull().cast("int")).alias("null_filing_id")).show()
fact.groupBy("scope").count().show()
(fact.where((F.col("lei") == "549300DAQ1CVT6CXN342") & (F.col("concept") == "ifrs-full:Assets"))
     .select("report_period_end", "period_end", "value", "decimals", "scope")
     .orderBy("report_period_end", "period_end").show())
