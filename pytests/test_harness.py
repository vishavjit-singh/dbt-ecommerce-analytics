import re
from pathlib import Path

import pytest

from ecom.harness import HarnessError, Project

ROOT = Path(__file__).resolve().parents[1]
SQLITE_ONLY = re.compile(r"\b(julianday|group_concat|strftime|datetime)\s*\(", re.I)
DUCKDB_ONLY = re.compile(r"\b(date_trunc|date_diff|string_agg)\s*\(|interval\s+'", re.I)


def all_sql(project):
    for name, node in project.nodes.items():
        yield name, node.sql
    for path in sorted((ROOT / "tests").glob("*.sql")):
        yield path.stem, path.read_text()
    for path in sorted((ROOT / "analyses").glob("*.sql")):
        yield path.stem, path.read_text()


@pytest.mark.parametrize("adapter, forbidden", [("duckdb", SQLITE_ONLY), ("sqlite", DUCKDB_ONLY)])
def test_every_file_renders_for_both_adapters(adapter, forbidden):
    """The DuckDB rendering never contains SQLite functions, and vice versa."""
    p = Project(ROOT, adapter_type=adapter)
    for name, sql in all_sql(p):
        rendered = p.render(sql, this=name, incremental=True)
        assert not forbidden.search(rendered), f"{name} rendered for {adapter} contains {forbidden.search(rendered)}"


def test_dispatch_picks_the_adapter_implementation():
    duck = Project(ROOT, adapter_type="duckdb").render("{{ xdb_month('d') }} {{ xdb_days_between('a', 'b') }}")
    lite = Project(ROOT, adapter_type="sqlite").render("{{ xdb_month('d') }} {{ xdb_days_between('a', 'b') }}")
    assert "date_trunc('month', d)" in duck and "date_diff('day'" in duck
    assert "date(d, 'start of month')" in lite and "julianday" in lite


def test_vars_and_incremental_branch():
    p = Project(ROOT)
    sql = p.nodes["fct_orders"].sql
    full = p.render(sql, this="fct_orders", incremental=False)
    inc = p.render(sql, this="fct_orders", incremental=True)
    assert "max(updated_at)" not in full
    assert "datetime(max(updated_at), '-3 days')" in inc and "from fct_orders" in inc
    assert "('completed', 'shipped')" in p.render("{{ revenue_status_list() }}")
    assert Project(ROOT, vars={"incremental_lookback_days": 7}).render(
        sql, this="fct_orders", incremental=True).count("'-7 days'") == 1


def test_dependency_order():
    order = Project(ROOT).order()
    for name, node in Project(ROOT).nodes.items():
        for dep in node.deps:
            assert order.index(dep) < order.index(name), (dep, name)


def test_unknown_ref_is_an_error(tmp_path):
    for item in ("dbt_project.yml",):
        (tmp_path / item).write_text((ROOT / item).read_text())
    (tmp_path / "models").mkdir()
    (tmp_path / "macros").mkdir()
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "models" / "a.sql").write_text("select * from {{ ref('missing') }}")
    with pytest.raises(HarnessError, match="missing"):
        Project(tmp_path).order()
