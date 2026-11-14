import shutil
from pathlib import Path

import pytest

from ecom.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def demo(tmp_path_factory):
    """Both deliveries through the SQLite harness, in a throw-away copy of the project."""
    tmp = tmp_path_factory.mktemp("project")
    for item in ("dbt_project.yml", "models", "macros", "tests", "snapshots"):
        src = ROOT / item
        (shutil.copytree if src.is_dir() else shutil.copy)(src, tmp / item)
    out = run_demo(tmp, tmp / "seeds", tmp / "target" / "harness.sqlite")
    from ecom.generate import Generator

    _, truth = Generator().build(2)
    import sqlite3

    conn = sqlite3.connect(str(tmp / "target" / "harness.sqlite"))
    return {"root": tmp, "results": out, "truth": truth, "conn": conn}


def rows(conn, sql):
    cur = conn.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
