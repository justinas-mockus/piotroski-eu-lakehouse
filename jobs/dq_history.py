"""Job task: append gold.dq_results and expectation drop counts to the DQ history (ADR-009)."""

import sys

from pyspark.sql import SparkSession

from piotroski.dq import dq_history

catalog, run_id = sys.argv[1:3]
spark = SparkSession.builder.getOrCreate()

rows = dq_history(
    spark.read.table(f"{catalog}.gold.dq_results"),
    spark.read.table(f"{catalog}.bronze.pipeline_event_log"),
    run_id,
)
rows.write.mode("append").saveAsTable(f"{catalog}.gold.dq_results_history")
