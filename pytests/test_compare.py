import shutil
import sqlite3

from ecom.compare import compare_marts


def test_identical_marts_match(demo, tmp_path):
    db = demo["root"] / "target" / "harness.sqlite"
    assert compare_marts(db, db) == []


def test_a_changed_value_is_reported(demo, tmp_path):
    db = demo["root"] / "target" / "harness.sqlite"
    other = tmp_path / "other.sqlite"
    shutil.copy(db, other)
    conn = sqlite3.connect(other)
    conn.execute("update fct_daily_revenue set net_revenue = net_revenue + 5 where order_date = "
                 "(select min(order_date) from fct_daily_revenue)")
    conn.commit()
    problems = compare_marts(db, other)
    assert len(problems) == 1 and problems[0].startswith("fct_daily_revenue.net_revenue")
