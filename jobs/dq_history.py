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
# replaceWhere swaps this run's rows atomically, so a repair run of the task doesn't duplicate them
(
    rows.write.mode("overwrite")
    .option("replaceWhere", f"run_id = '{run_id}'")
    .saveAsTable(f"{catalog}.gold.dq_results_history")
)
