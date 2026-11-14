"""Charts for the README, read from the marts.

Works on the SQLite harness database (``target/harness.sqlite``) and on the DuckDB file that
``dbt build`` writes (``target/ecommerce.duckdb``), so CI can regenerate the same charts from real dbt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

INK = "#0e1a2b"
MUTED = "#5b6676"
GRID = "#e3e7ee"
ACCENT = "#2a78d6"
SIGNAL = "#eda100"
BAD = "#e34948"
GOOD = "#1baf7a"
PURPLE = "#6250d6"
LAYER_COLORS = {"sources": "#b0702b", "staging": "#7d8794", "intermediate": PURPLE, "marts": "#c99a06",
                "snapshots": ACCENT, "exposures": GOOD}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED,
    "ytick.color": MUTED, "axes.titleweight": "bold", "axes.titlesize": 13, "axes.titlecolor": INK,
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150,
})

MARTS = ("fct_orders", "dim_customers", "fct_daily_revenue", "fct_cohort_retention", "fct_product_performance")


class Warehouse:
    """Read a mart from either engine: SQLite harness (flat names) or dbt-duckdb (layer schemas)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.suffix == ".duckdb":
            import duckdb

            self.conn = duckdb.connect(str(self.path), read_only=True)
            self.engine = "duckdb"
        else:
            import sqlite3

            self.conn = sqlite3.connect(str(self.path))
            self.engine = "sqlite"

    def table(self, name: str, schema: str = "marts") -> pd.DataFrame:
        rel = f"{schema}.{name}" if self.engine == "duckdb" else f'"{name}"'
        cur = self.conn.execute(f"select * from {rel}")
        cols = [c[0] for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        for c in df.columns:
            if c.endswith(("_date", "_month")) or c in ("order_date",):
                df[c] = pd.to_datetime(df[c].astype(str))
        return df


def _save(fig, out: Path, name: str) -> Path:
    fig.tight_layout()
    path = out / name
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def _inr(x, _pos=None) -> str:
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:.1f} L"
    if abs(x) >= 1e3:
        return f"₹{x / 1e3:.0f}k"
    return f"₹{x:,.0f}"


# ------------------------------------------------------------------------------------------------ lineage
def lineage(project_root: Path, out: Path) -> Path:
    """The DAG drawn from the project's own files: sources, refs, snapshot and exposure."""
    from .harness import Project

    p = Project(project_root)
    src_rx = re.compile(r"""source\(\s*['"](\w+)['"]\s*,\s*['"](\w+)['"]\s*\)""")
    nodes, edges = {}, []
    for name, node in p.nodes.items():
        layer = node.layer if node.kind == "model" else "snapshots"
        nodes[name] = layer
        for s, t in src_rx.findall(node.sql):
            nodes[f"raw.{t}"] = "sources"
            edges.append((f"raw.{t}", name))
        edges += [(d, name) for d in sorted(node.deps)]
    import yaml

    exposures = yaml.safe_load((project_root / "models" / "exposures.yml").read_text())["exposures"]
    for e in exposures:
        nodes[e["label"]] = "exposures"
        edges += [(re.search(r"ref\('(\w+)'\)", d).group(1), e["label"]) for d in e["depends_on"]]
    # layered layout: column = longest path from the raw tables, so every edge points left to right
    parents: dict[str, set] = {n: set() for n in nodes}
    for a, b in edges:
        parents[b].add(a)
    depth: dict[str, int] = {}

    def d(n: str) -> int:
        if n not in depth:
            depth[n] = 0 if not parents[n] else 1 + max(d(x) for x in parents[n])
        return depth[n]

    for n in nodes:
        d(n)
    n_cols = max(depth.values()) + 1
    col_w, w, h = 2.05, 1.8, 0.5
    pos: dict[str, tuple[float, float]] = {}
    for c in range(n_cols):
        names = [n for n in nodes if depth[n] == c]
        if c == 0:
            names.sort()
        else:
            names.sort(key=lambda n: (round(sum(pos[x][1] for x in sorted(parents[n])) / len(parents[n]), 6), n),
                       reverse=True)
        top = 6.8
        step = min(1.05, 6.4 / max(len(names), 1))
        start_y = top - (6.4 - step * len(names)) / 2
        for i, n in enumerate(names):
            pos[n] = (0.1 + c * col_w, start_y - step * (i + 1))
    fig, ax = plt.subplots(figsize=(16, 6.4))
    ax.set_xlim(0, n_cols * col_w + 0.1)
    ax.set_ylim(-0.5, 7.6)
    ax.axis("off")
    for a, b in edges:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ax.add_patch(FancyArrowPatch((x1 + w, y1 + h / 2), (x2, y2 + h / 2), arrowstyle="-|>", mutation_scale=9,
                                     lw=0.9, color="#aab3c2", zorder=1, shrinkA=0, shrinkB=1))
    for n, (x, y) in pos.items():
        color = LAYER_COLORS[nodes[n]]
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08", fc="white",
                                    ec=color, lw=1.8, zorder=3))
        label = n if len(n) <= 25 else n[:24] + "…"
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=7.6, color=INK, zorder=4)
    for i, (layer, color) in enumerate(LAYER_COLORS.items()):
        ax.add_patch(FancyBboxPatch((0.1 + i * 1.9, 7.0), 0.28, 0.22, boxstyle="round,pad=0.01", fc="white",
                                    ec=color, lw=1.8))
        ax.text(0.45 + i * 1.9, 7.11, {"sources": "raw (seeds)", "exposures": "exposure"}.get(layer, layer),
                va="center", fontsize=9, color=color, weight="bold")
    ax.text(0.1, 7.45, "dbt-ecommerce-analytics: lineage parsed from the project's own ref() / source() calls",
            fontsize=13, weight="bold", color=INK)
    ax.text(0.1, -0.4, "fct_orders is incremental (delete+insert on order_id, filtered on updated_at) · "
            "customers_snapshot is SCD2 (timestamp strategy) · cross-database SQL via adapter.dispatch macros",
            fontsize=8.5, color=MUTED)
    return _save(fig, out, "lineage.png")


# ------------------------------------------------------------------------------------------------ marts
def daily_revenue(wh: Warehouse, out: Path, source: str) -> Path:
    d = wh.table("fct_daily_revenue").sort_values("order_date")
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar(d["order_date"], d["net_revenue"], color="#c9daf3", width=1.0, label="net revenue per day")
    ax.plot(d["order_date"], d["net_revenue_7d_avg"], color=ACCENT, lw=2, label="trailing 7-day average")
    ax.yaxis.set_major_formatter(_inr)
    ax.grid(axis="y", color=GRID)
    ax.legend(frameon=False, loc="upper left")
    total = d["net_revenue"].sum()
    ax.set_title(f"fct_daily_revenue: {_inr(total)} net revenue from {int(d['orders'].sum()):,} orders "
                 f"(synthetic, 2025)")
    ax.text(1, -0.14, source, transform=ax.transAxes, ha="right", fontsize=7.5, color=MUTED)
    return _save(fig, out, "daily_revenue.png")


def cohort_retention(wh: Warehouse, out: Path, source: str) -> Path:
    c = wh.table("fct_cohort_retention")
    c = c[c["months_since_first_order"] <= 11]
    piv = c.pivot_table(index="cohort_month", columns="months_since_first_order", values="retention_rate")
    sizes = c.groupby("cohort_month")["cohort_size"].first()
    piv = piv.sort_index()
    fig, ax = plt.subplots(figsize=(11, 5.2))
    m = piv.values.copy()
    shown = np.where(np.isnan(m), np.nan, m)
    shown[:, 0] = np.nan                        # month 0 is 100% by definition; keep the colour scale useful
    ax.imshow(shown, cmap="Blues", vmin=0, vmax=np.nanmax(shown) if np.isfinite(np.nanmax(shown)) else 1,
              aspect="auto")
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            if not np.isnan(m[i, j]):
                v = m[i, j]
                ax.text(j, i, f"{v:.0%}", ha="center", va="center", fontsize=7.5,
                        color="white" if j > 0 and v > np.nanmax(shown) * 0.6 else INK)
    ax.set_yticks(range(len(piv.index)),
                  [f"{d:%b %Y}  (n={sizes[d]})" for d in piv.index], fontsize=8.5)
    ax.set_xticks(range(len(piv.columns)), [str(int(x)) for x in piv.columns])
    ax.set_xlabel("months since first revenue order")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title("fct_cohort_retention: share of each monthly cohort ordering again")
    ax.text(1, -0.12, source, transform=ax.transAxes, ha="right", fontsize=7.5, color=MUTED)
    return _save(fig, out, "cohort_retention.png")


def segments(wh: Warehouse, out: Path, source: str) -> Path:
    d = wh.table("dim_customers")
    order = ["champions", "loyal", "new", "needs_attention", "at_risk", "hibernating", "prospect"]
    g = d.groupby("segment").agg(customers=("customer_id", "count"), revenue=("lifetime_revenue", "sum"))
    g = g.reindex([s for s in order if s in g.index])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    y = np.arange(len(g))
    colors = [GOOD, GOOD, ACCENT, SIGNAL, BAD, BAD, GRID]
    a1.barh(y, g["customers"], color=colors[:len(g)], height=0.6)
    a2.barh(y, g["revenue"], color=colors[:len(g)], height=0.6)
    for i, (c, r) in enumerate(zip(g["customers"], g["revenue"])):
        a1.text(c, i, f" {c:,}", va="center", fontsize=8.5, color=INK)
        a2.text(r, i, f" {r / g['revenue'].sum():.0%}", va="center", fontsize=8.5, color=INK)
    a1.set_yticks(y, g.index)
    a1.invert_yaxis()
    a1.set_title("dim_customers: customers per RFM segment")
    a2.set_title("lifetime revenue share")
    a2.xaxis.set_major_formatter(_inr)
    a2.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(4))
    for a in (a1, a2):
        a.grid(axis="x", color=GRID)
    a1.set_xlim(0, g["customers"].max() * 1.18)
    a2.set_xlim(0, g["revenue"].max() * 1.18)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.text(0.99, 0.01, source, ha="right", fontsize=7.5, color=MUTED)
    path = out / "segments.png"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def products(wh: Warehouse, out: Path, source: str) -> Path:
    p = wh.table("fct_product_performance")
    g = p.groupby("category").agg(revenue=("revenue", "sum"), margin=("margin", "sum")).sort_values("revenue")
    g["margin_pct"] = g["margin"] / g["revenue"]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    y = np.arange(len(g))
    ax.barh(y, g["revenue"], color="#c9daf3", height=0.62, label="revenue")
    ax.barh(y, g["margin"], color=ACCENT, height=0.62, label="gross margin")
    for i, (r, m) in enumerate(zip(g["revenue"], g["margin_pct"])):
        ax.text(r, i, f"  {_inr(r)} · margin {m:.0%}", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y, g.index)
    ax.xaxis.set_major_formatter(_inr)
    ax.set_xlim(0, g["revenue"].max() * 1.35)
    ax.grid(axis="x", color=GRID)
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("fct_product_performance: revenue and gross margin by category")
    ax.text(1, -0.16, source, transform=ax.transAxes, ha="right", fontsize=7.5, color=MUTED)
    return _save(fig, out, "product_performance.png")


def tests_chart(results: dict, out: Path) -> Path:
    tests = results["batches"][-1]["tests"]
    layers = ["sources", "staging", "intermediate", "marts", "singular"]
    counts = {l_: {"pass": 0, "warn": 0, "fail": 0} for l_ in layers}
    for t in tests:
        counts[t["layer"]][t["status"]] += 1
    fig, ax = plt.subplots(figsize=(10, 3.8))
    y = np.arange(len(layers))
    left = np.zeros(len(layers))
    for status, color in (("pass", GOOD), ("warn", SIGNAL), ("fail", BAD)):
        vals = np.array([counts[l_][status] for l_ in layers])
        ax.barh(y, vals, left=left, color=color, height=0.6, label=status)
        for i, v in enumerate(vals):
            if v:
                ax.text(left[i] + v / 2, i, str(v), ha="center", va="center", fontsize=9,
                        color="white" if status != "warn" else INK)
        left += vals
    warns = [t for t in tests if t["status"] == "warn"]
    note = "\n".join(f"  {t['target']} · {t['name']}: {t['failures']} rows" for t in warns)
    ax.set_yticks(y, layers)
    ax.invert_yaxis()
    ax.grid(axis="x", color=GRID)
    ax.set_xlim(0, left.max() * 1.25)
    ax.legend(frameon=False, loc="upper right")
    ax.set_title(f"Data tests after the second load: {len(tests)} tests, "
                 f"{sum(c['fail'] for c in counts.values())} failing, {len(warns)} warnings on raw data")
    ax.text(0.99, 0.04, "warnings = defects caught in the raw extracts (severity: warn)\n" + note,
            transform=ax.transAxes, fontsize=7.8, color="#9a6a00", ha="right", va="bottom")
    return _save(fig, out, "data_tests.png")


def render_all(project_root: Path, db: Path, out: Path, results_path: Path | None = None) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    wh = Warehouse(db)
    source = ("rendered from the SQLite test-harness run of the same models"
              if wh.engine == "sqlite" else "rendered from dbt-duckdb output")
    paths = [lineage(project_root, out), daily_revenue(wh, out, source), cohort_retention(wh, out, source),
             segments(wh, out, source), products(wh, out, source)]
    results_path = results_path or db.parent / "harness_results.json"
    if results_path.exists():
        paths.append(tests_chart(json.loads(results_path.read_text()), out))
    return paths


def summary(db: Path, results_path: Path | None = None) -> dict:
    wh = Warehouse(db)
    f = wh.table("fct_orders")
    d = wh.table("dim_customers")
    c = wh.table("fct_cohort_retention")
    rev = f[f["is_revenue"] == 1]
    m1 = c[c["months_since_first_order"] == 1]
    out = {
        "engine": wh.engine,
        "fct_orders": len(f),
        "revenue_orders": len(rev),
        "net_revenue": round(float(rev["net_revenue"].sum()), 2),
        "avg_order_value": round(float(rev["net_revenue"].mean()), 2),
        "customers": len(d),
        "customers_with_orders": int((d["lifetime_orders"] > 0).sum()),
        "repeat_customers": int((d["lifetime_orders"] > 1).sum()),
        "segments": d["segment"].value_counts().to_dict(),
        "month1_retention_weighted": round(float(m1["active_customers"].sum() / m1["cohort_size"].sum()), 4)
        if len(m1) else None,
    }
    results_path = results_path or db.parent / "harness_results.json"
    if results_path.exists():
        r = json.loads(results_path.read_text())
        b1, b2 = r["batches"]
        out["harness"] = {
            "raw_rows_batch2": b2["raw_rows"],
            "tests": len(b2["tests"]),
            "tests_failing": sum(1 for t in b2["tests"] if t["status"] == "fail"),
            "warnings": {f"{t['target']} {t['name']}": t["failures"] for t in b2["tests"] if t["status"] == "warn"},
            "incremental_rows_processed_batch2": b2["incremental_rows_processed"],
            "fct_orders_rows_batch1": b1["model_rows"]["fct_orders"],
            "snapshot_batch2": b2["snapshot"],
            "incremental_equals_full_refresh": r["incremental_equals_full_refresh"],
            "truth": r["truth"],
            "defects": b2["defects"],
        }
    return out
