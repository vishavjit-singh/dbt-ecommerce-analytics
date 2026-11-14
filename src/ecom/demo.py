"""Two deliveries through the SQLite harness, the way the dbt job runs them in CI.

1. batch 1 → seed → build (full)
2. batch 2 → seed → build again (fct_orders runs incrementally, the snapshot records changes)
3. check: a full refresh on batch 2 gives the same fct_orders as the incremental run
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .generate import generate
from .harness import Project, SqliteRunner


def _rows(runner: SqliteRunner, table: str, order: str) -> list[tuple]:
    return runner.conn.execute(f'select * from "{table}" order by {order}').fetchall()


def run_demo(root: Path, seeds: Path, db: Path) -> dict:
    project = Project(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    runner = SqliteRunner(project, db)
    out: dict = {"batches": []}
    truth = None
    for batch in (1, 2):
        if seeds.exists():
            shutil.rmtree(seeds)
        counts, truth = generate(seeds, batch=batch)
        runner.seed(seeds)
        before = runner.count("fct_orders") if batch == 2 else 0
        res = runner.build()
        tests = res["tests"]
        out["batches"].append({
            "batch": batch,
            "raw_rows": counts,
            "model_rows": res["rows"],
            "snapshot": res["snapshots"].get("customers_snapshot"),
            "fct_orders_rows_before": before,
            "incremental_rows_processed": runner.incremental_rows.get("fct_orders"),
            "tests": [{"name": t.name, "target": t.target, "layer": t.layer, "severity": t.severity,
                       "failures": t.failures, "status": t.status} for t in tests],
            "defects": truth.defects,
            "truth_customer_changes": truth.customer_changes,
        })

    # full refresh on the final data must equal the incrementally built table
    fresh = SqliteRunner(project, ":memory:")
    fresh.seed(seeds)
    fresh.build(full_refresh=True)
    out["incremental_equals_full_refresh"] = (_rows(runner, "fct_orders", "order_id")
                                              == _rows(fresh, "fct_orders", "order_id"))
    out["truth"] = {"revenue_orders": len(truth.revenue_orders()),
                    "net_revenue": round(sum(truth.daily_revenue().values()), 2),
                    "real_customers": len(truth.customers)}
    (db.parent / "harness_results.json").write_text(json.dumps(out, indent=2))
    return out
