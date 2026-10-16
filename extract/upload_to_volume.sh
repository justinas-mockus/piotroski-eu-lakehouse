#!/usr/bin/env bash
set -euo pipefail

CATALOG="${1:-piotroski_dev}"
databricks fs cp -r --overwrite data/landing "dbfs:/Volumes/${CATALOG}/bronze/landing"
