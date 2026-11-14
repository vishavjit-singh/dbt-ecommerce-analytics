PY ?= python3
export PYTHONPATH := src
export DBT_PROFILES_DIR := .

.PHONY: install install-dbt demo harness report summary test lint dbt-demo dbt-docs compare clean

install:
	$(PY) -m pip install -r requirements-dev.txt

install-dbt:
	$(PY) -m pip install -r requirements-dbt.txt

## No dbt needed: two deliveries through the SQLite test harness → charts → summary
demo: harness report summary

harness:
	$(PY) -m ecom harness

report:
	$(PY) -m ecom report

summary:
	$(PY) -m ecom summary

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src pytests

## The real thing: dbt-duckdb, two deliveries (second run is incremental + snapshot), docs, parity check
dbt-demo:
	$(PY) -m ecom generate --batch 1
	dbt seed && dbt build
	$(PY) -m ecom generate --batch 2
	dbt seed && dbt build
	dbt source freshness
	dbt docs generate
	$(PY) -m ecom harness
	$(PY) -m ecom compare
	$(PY) -m ecom report --db target/ecommerce.duckdb --out dbt-report

dbt-docs:
	dbt docs generate && dbt docs serve

compare:
	$(PY) -m ecom compare

clean:
	$(PY) -m ecom clean
