from ecom.generate import TABLES, Generator, write_seeds


def test_deterministic():
    a, _ = Generator().build(2)
    b, _ = Generator().build(2)
    assert a == b


def test_batch1_is_a_prefix_of_batch2():
    b1, _ = Generator().build(1)
    b2, t2 = Generator().build(2)
    o1 = {r["order_id"]: r for r in b1["raw_orders"]}
    o2 = {r["order_id"]: r for r in b2["raw_orders"]}
    assert set(o1) < set(o2)
    same = sum(1 for k in o1 if o1[k]["order_ts"] == o2[k]["order_ts"] and o1[k]["customer_id"] == o2[k]["customer_id"])
    assert same == len(o1)
    changed = sum(1 for k in o1 if o1[k]["status"].strip().lower() != o2[k]["status"].strip().lower())
    assert changed == t2.defects["late_status_changes"] > 0
    i1 = {r["order_item_id"] for r in b1["raw_order_items"]}
    assert i1 < {r["order_item_id"] for r in b2["raw_order_items"]}


def test_defects_are_present():
    _, t = Generator().build(2)
    for k in ("duplicate_customer_rows", "stale_customer_versions", "test_orders", "orphan_orders",
              "duplicate_order_rows", "bad_quantity_items", "missing_price_items", "failed_payments", "refunds"):
        assert t.defects[k] > 0, k
    assert t.customer_changes == 40


def test_seed_files_have_the_contracted_columns(tmp_path):
    tables, _ = Generator(customers=50, products=12).build(2)
    write_seeds(tables, tmp_path)
    for name, cols in TABLES.items():
        assert (tmp_path / f"{name}.csv").read_text().splitlines()[0] == ",".join(cols)
