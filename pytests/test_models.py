"""Model logic checked against the generator's truth, on the SQLite harness run of both loads."""
import pytest

from pytests.conftest import rows


def test_no_failing_tests_and_expected_warnings(demo):
    tests = demo["results"]["batches"][-1]["tests"]
    assert not [t for t in tests if t["status"] == "fail"]
    warns = {(t["target"], t["name"]): t["failures"] for t in tests if t["status"] == "warn"}
    d = demo["truth"].defects
    assert warns[("shop.orders", "relationships(customer_id)")] == d["orphan_orders"]
    assert warns[("shop.orders", "unique(order_id)")] == d["duplicate_order_rows"]
    assert ("shop.customers", "unique(customer_id)") in warns


def test_daily_revenue_matches_truth(demo):
    got = {r["order_date"]: r["net_revenue"] for r in rows(demo["conn"], "select * from fct_daily_revenue")}
    want = demo["truth"].daily_revenue()
    assert set(got) == set(want)
    for day, value in want.items():
        assert got[day] == pytest.approx(value, abs=0.011), day


def test_customer_lifetime_revenue_matches_truth(demo):
    got = {r["customer_id"]: r["lifetime_revenue"] for r in rows(demo["conn"], "select * from dim_customers")}
    want = demo["truth"].lifetime_revenue()
    assert set(got) == set(demo["truth"].customers)                 # real customers only, no test accounts
    for cid, value in want.items():
        assert got[cid] == pytest.approx(value, abs=0.011), cid
    assert all(got[c] == 0 for c in set(got) - set(want))


def test_staging_keeps_the_latest_customer_version(demo):
    got = {r["customer_id"]: r for r in rows(demo["conn"], "select * from stg_customers")}
    for cid, c in demo["truth"].customers.items():
        assert got[cid]["country"] == c["country"] and got[cid]["email"] == c["email"]


def test_orders_exclude_test_accounts_and_orphans(demo):
    ids = {r["order_id"] for r in rows(demo["conn"], "select order_id from fct_orders")}
    assert ids == set(demo["truth"].orders)


def test_late_status_changes_reach_the_incremental_fact(demo):
    statuses = {r["order_id"]: r["status"] for r in rows(demo["conn"], "select order_id, status from fct_orders")}
    assert statuses == {k: v["status"] for k, v in demo["truth"].orders.items()}
    assert demo["results"]["incremental_equals_full_refresh"]
    b2 = demo["results"]["batches"][1]
    assert 0 < b2["incremental_rows_processed"] < b2["model_rows"]["fct_orders"]


def test_snapshot_records_customer_changes(demo):
    snap = rows(demo["conn"], "select * from customers_snapshot")
    closed = [r for r in snap if r["dbt_valid_to"] is not None]
    assert len(closed) == demo["truth"].customer_changes
    assert demo["results"]["batches"][1]["snapshot"] == {"inserted": 40, "closed": 40}
    current = {r["customer_id"] for r in snap if r["dbt_valid_to"] is None}
    assert len(current) == len({r["customer_id"] for r in snap})


def test_cohorts(demo):
    c = rows(demo["conn"], "select * from fct_cohort_retention")
    assert all(r["retention_rate"] == 1 for r in c if r["months_since_first_order"] == 0)
    sizes = sum(r["cohort_size"] for r in c if r["months_since_first_order"] == 0)
    buyers = rows(demo["conn"], "select count(*) n from dim_customers where lifetime_orders > 0")[0]["n"]
    assert sizes == buyers


def test_rfm_scores_are_quintiles(demo):
    r = rows(demo["conn"], "select recency_score s, count(*) n from dim_customers where recency_score is not null "
                           "group by 1 order by 1")
    counts = [x["n"] for x in r]
    assert [x["s"] for x in r] == [1, 2, 3, 4, 5] and max(counts) - min(counts) <= 1


def test_imputed_prices_and_bad_quantities(demo):
    lines = rows(demo["conn"], "select count(*) n, sum(is_price_imputed) imputed from int_order_lines")[0]
    staged = rows(demo["conn"], "select count(*) n, sum(case when quantity <= 0 then 1 else 0 end) bad "
                                "from stg_order_items")[0]
    d = demo["truth"].defects
    assert staged["bad"] == d["bad_quantity_items"]
    assert lines["n"] == staged["n"] - staged["bad"]
    assert lines["imputed"] > 0
