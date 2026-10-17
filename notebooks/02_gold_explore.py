# Databricks notebook source

# COMMAND ----------
import pyspark, sys
print(pyspark.__version__, sys.version)

# COMMAND ----------
spark.read.table("piotroski_dev.silver.fundamentals").selectExpr(
    "count_if(cost_of_sales < 0) AS neg",
    "count_if(cost_of_sales > 0) AS pos",
    "count_if(gross_profit IS NULL AND revenue IS NOT NULL AND cost_of_sales IS NOT NULL) AS derivable",
).show()

# COMMAND ----------
