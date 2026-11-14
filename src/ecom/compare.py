"""Compare marts from dbt-duckdb with the SQLite harness output. Used by CI after `dbt build`."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .report import Warehouse

KEYS = {
    "fct_orders": ["order_id"],
    "dim_customers": ["customer_id"],
    "fct_daily_revenue": ["order_date"],
    "fct_cohort_retention": ["cohort_month", "months_since_first_order"],
    "fct_product_performance": ["product_id"],
}


def _norm(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_bool_dtype(out[c]):
            out[c] = out[c].astype(int)
    return out.sort_values(keys).reset_index(drop=True)


def compare_marts(duck: Path, lite: Path, tolerance: float = 0.011) -> list[str]:
    d, s = Warehouse(duck), Warehouse(lite)
    problems = []
    for table, keys in KEYS.items():
        a, b = _norm(d.table(table), keys), _norm(s.table(table), keys)
        if len(a) != len(b):
            problems.append(f"{table}: {len(a)} rows in duckdb vs {len(b)} in sqlite")
            continue
        for col in a.columns:
            if col not in b.columns or col in ("order_ts", "updated_at"):
                continue
            x, y = a[col], b[col]
            if pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y):
                diff = (x.astype(float) - y.astype(float)).abs()
                both_null = x.isna() & y.isna()
                bad = (diff > tolerance) & ~both_null | (x.isna() != y.isna())
            else:
                bad = x.astype(str).where(x.notna(), "") != y.astype(str).where(y.notna(), "")
            if bad.any():
                i = bad.idxmax()
                problems.append(f"{table}.{col}: {int(bad.sum())} rows differ, e.g. {a.loc[i, keys].tolist()}: "
                                f"duckdb={x[i]!r} sqlite={y[i]!r}")
    return problems
