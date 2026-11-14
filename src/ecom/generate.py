"""Synthetic raw e-commerce extracts (the dbt seeds) and the truth the models must reproduce.

Everything here is synthetic: names come from short word lists, emails use example.com, and a fixed
seed makes every file and every number reproducible. The raw files are deliberately messy:

* customers: re-delivered duplicates, an older and a newer version of the same customer, emails in
  mixed case with stray spaces, lower-case country codes, internal test accounts
* orders: re-delivered duplicate rows, status values in mixed case with trailing spaces, orders that
  point at customers who do not exist (orphans)
* order items: zero or negative quantities, missing unit prices (the list price applies)
* payments: failed attempts before a successful one, refunds for returned orders

Batch 1 covers orders up to ``BATCH1_END``. Batch 2 is the next delivery: the same files with a
week of new orders plus late changes to old ones (returns, shipped → completed) and customer
attribute changes. It exercises the incremental model and the snapshot.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 42
START = date(2025, 1, 1)
END = date(2025, 12, 31)
BATCH1_END = date(2025, 12, 24)
REVENUE_STATUSES = ("completed", "shipped")
COUNTRIES = ["IN", "US", "GB", "DE", "AE", "SG"]
FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Isha", "Arjun", "Sana", "Vihaan", "Anaya", "Kiran", "Neha",
         "Rahul", "Priya", "Aman", "Simran", "Dev", "Tara", "Nikhil", "Riya", "Harpreet", "Gurleen", "Leo", "Maya"]
LAST = ["Sharma", "Verma", "Gill", "Sandhu", "Iyer", "Nair", "Khan", "Das", "Mehta", "Kapoor", "Reddy", "Bose",
        "Joshi", "Malhotra", "Grewal", "Bhatia", "Saxena", "Clark", "Weber", "Tan"]
CATEGORIES = {"electronics": (900, 15000), "home": (300, 4000), "fashion": (400, 3500), "beauty": (150, 1800),
              "books": (150, 900), "sports": (500, 6000)}
METHODS = ["card", "upi", "wallet", "cod"]
CHANNELS = ["web", "app", "marketplace"]

TABLES = {
    "raw_customers": ["customer_id", "email", "first_name", "last_name", "country", "signup_date", "updated_at",
                      "_loaded_at"],
    "raw_products": ["product_id", "product_name", "category", "unit_cost", "list_price", "is_active", "_loaded_at"],
    "raw_orders": ["order_id", "customer_id", "order_ts", "status", "channel", "discount_amount", "shipping_amount",
                   "updated_at", "_loaded_at"],
    "raw_order_items": ["order_item_id", "order_id", "product_id", "quantity", "unit_price", "_loaded_at"],
    "raw_payments": ["payment_id", "order_id", "payment_method", "amount", "status", "created_at", "_loaded_at"],
}


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Truth:
    """Clean facts, computed in Python independently of the SQL models."""
    customers: dict[str, dict] = field(default_factory=dict)      # current version of real customers
    orders: dict[str, dict] = field(default_factory=dict)         # valid orders (not test, not orphan)
    defects: dict[str, int] = field(default_factory=dict)
    customer_changes: int = 0                                      # tracked changes delivered in batch 2

    def revenue_orders(self) -> list[dict]:
        return [o for o in self.orders.values() if o["status"] in REVENUE_STATUSES]

    def daily_revenue(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for o in self.revenue_orders():
            out[o["order_date"]] = out.get(o["order_date"], 0.0) + o["net_revenue"]
        return {k: round(v, 2) for k, v in sorted(out.items())}

    def lifetime_revenue(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for o in self.revenue_orders():
            out[o["customer_id"]] = out.get(o["customer_id"], 0.0) + o["net_revenue"]
        return {k: round(v, 2) for k, v in out.items()}


class Generator:
    def __init__(self, customers: int = 2500, products: int = 60, seed: int = SEED):
        self.rng = random.Random(seed)
        self.n_customers = customers
        self.n_products = products

    # ------------------------------------------------------------------ entities
    def _products(self) -> list[dict]:
        rng, out = self.rng, []
        cats = list(CATEGORIES)
        for i in range(1, self.n_products + 1):
            cat = cats[(i - 1) % len(cats)]
            lo, hi = CATEGORIES[cat]
            price = round(rng.uniform(lo, hi), 2)
            out.append({"product_id": f"P{i:03d}", "product_name": f"{cat.title()} item {i}", "category": cat,
                        "unit_cost": round(price * rng.uniform(0.45, 0.75), 2), "list_price": price,
                        "is_active": "true" if rng.random() > 0.08 else "false"})
        return out

    def _customers(self) -> list[dict]:
        rng, out = self.rng, []
        for i in range(1, self.n_customers + 1):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            signup = START + timedelta(days=int(rng.triangular(0, 364, 250)))
            out.append({"customer_id": f"C{i:05d}", "email": f"{first.lower()}.{last.lower()}{i}@example.com",
                        "first_name": first, "last_name": last,
                        "country": rng.choices(COUNTRIES, [6, 3, 2, 2, 1, 1])[0],
                        "signup_date": signup, "is_test": False,
                        "updated_at": datetime.combine(signup, datetime.min.time())
                        + timedelta(hours=rng.randrange(24))})
        for j in range(1, 13):        # internal test accounts: they place orders that must not count
            signup = START + timedelta(days=rng.randrange(300))
            out.append({"customer_id": f"T{j:03d}", "email": f"qa{j}@test.example.com", "first_name": "QA",
                        "last_name": f"Bot{j}", "country": "IN", "signup_date": signup, "is_test": True,
                        "updated_at": datetime.combine(signup, datetime.min.time())})
        return out

    # ------------------------------------------------------------------ build
    def build(self, batch: int = 2) -> tuple[dict[str, list[dict]], Truth]:
        """Generate the whole year once, then cut it down to what each delivery would contain.

        Generating everything first keeps batch 1 an exact prefix of batch 2: same ids, same values.
        """
        if batch not in (1, 2):
            raise ValueError("batch must be 1 or 2")
        rng = self.rng
        products = self._products()
        customers = self._customers()
        orders, items, payments = [], [], []
        defects = {"duplicate_customer_rows": 0, "stale_customer_versions": 0, "test_orders": 0,
                   "orphan_orders": 0, "duplicate_order_rows": 0, "bad_quantity_items": 0,
                   "missing_price_items": 0, "failed_payments": 0, "refunds": 0, "late_status_changes": 0}
        net_of: dict[str, float] = {}
        kind_of: dict[str, str] = {}          # order_id -> real | test | orphan
        oid = iid = pid = 0

        def add_order(cust_id: str, ts: datetime, kind: str) -> None:
            nonlocal oid, iid, pid
            oid += 1
            order_id = f"O{oid:06d}"
            n_lines = rng.choices([1, 2, 3, 4], [50, 30, 14, 6])[0]
            gross = 0.0
            for prod in rng.sample(products, n_lines):
                iid += 1
                qty = rng.choices([1, 2, 3], [75, 20, 5])[0]
                price = round(prod["list_price"] * rng.choice([1, 1, 1, 0.9, 0.85]), 2)
                raw_price: str | float = price
                if rng.random() < 0.01:                     # missing unit price: list price applies
                    raw_price, price = "", prod["list_price"]
                    defects["missing_price_items"] += 1
                raw_qty = qty
                if rng.random() < 0.006:                    # zero / negative quantity: excluded line
                    raw_qty = rng.choice([0, -1])
                    defects["bad_quantity_items"] += 1
                else:
                    gross += qty * price
                items.append({"order_item_id": f"I{iid:07d}", "order_id": order_id,
                              "product_id": prod["product_id"], "quantity": raw_qty, "unit_price": raw_price,
                              "_order_ts": ts})
            discount = round(gross * rng.choice([0, 0, 0, 0.05, 0.1]), 2)
            shipping = 0.0 if gross > 999 else 49.0
            status = rng.choices(["completed", "shipped", "pending", "cancelled", "returned"], [70, 12, 4, 8, 6])[0]
            if (END - ts.date()).days <= 2 and status == "completed":
                status = rng.choice(["shipped", "pending"])
            updated = ts + timedelta(hours=rng.randrange(1, 72))
            orders.append({"order_id": order_id, "customer_id": cust_id, "order_ts": ts, "status": status,
                           "channel": rng.choice(CHANNELS), "discount_amount": discount,
                           "shipping_amount": shipping, "updated_at": updated, "_b1_status": status,
                           "_b1_updated": updated})
            if status != "cancelled":
                method = rng.choice(METHODS)
                total = round(gross - discount + shipping, 2)
                if rng.random() < 0.07:
                    pid += 1
                    payments.append({"payment_id": f"Y{pid:07d}", "order_id": order_id, "payment_method": method,
                                     "amount": total, "status": "failed", "created_at": ts + timedelta(minutes=2)})
                pid += 1
                payments.append({"payment_id": f"Y{pid:07d}", "order_id": order_id, "payment_method": method,
                                 "amount": total, "status": "success", "created_at": ts + timedelta(minutes=5)})
                if status == "returned":
                    pid += 1
                    payments.append({"payment_id": f"Y{pid:07d}", "order_id": order_id, "payment_method": method,
                                     "amount": round(gross - discount, 2), "status": "refunded",
                                     "created_at": updated})
            net_of[order_id] = round(gross - discount, 2)
            kind_of[order_id] = kind

        for c in customers:
            n = 1 + int(rng.expovariate(0.55)) if not c["is_test"] else rng.randint(2, 5)
            if rng.random() < 0.12 and not c["is_test"]:
                n = 0                                     # signed up, never ordered
            day = c["signup_date"] + timedelta(days=rng.randrange(0, 20))
            for _ in range(n):
                if day > END:
                    break
                ts = datetime.combine(day, datetime.min.time()) + timedelta(seconds=rng.randrange(86400))
                add_order(c["customer_id"], ts, "test" if c["is_test"] else "real")
                day += timedelta(days=int(rng.expovariate(1 / 45)) + 1)
        for _ in range(25):                                # orphans: customer ids nobody knows
            day = START + timedelta(days=rng.randrange((END - START).days + 1))
            ts = datetime.combine(day, datetime.min.time()) + timedelta(seconds=rng.randrange(86400))
            add_order(f"C9{rng.randrange(10000):04d}", ts, "orphan")

        # late changes delivered with batch 2: shipped orders from the last month of batch 1 complete
        b1_end = datetime.combine(BATCH1_END, datetime.max.time()).replace(microsecond=0)
        for o in orders:
            d = o["order_ts"].date()
            if BATCH1_END - timedelta(days=30) < d <= BATCH1_END and o["status"] == "shipped" and rng.random() < 0.6:
                o["status"], o["updated_at"] = "completed", datetime(2025, 12, 27, 9, 30)
                defects["late_status_changes"] += 1
        new_country = {}
        for c in rng.sample([c for c in customers if not c["is_test"]], 40):
            new_country[c["customer_id"]] = (rng.choice([x for x in COUNTRIES if x != c["country"]]),
                                              datetime(2025, 12, 28, 10, 0) + timedelta(minutes=rng.randrange(600)))
        row_noise = [(rng.random(), rng.random(), rng.random(), rng.random(), rng.choice(COUNTRIES))
                     for _ in customers]
        order_noise = {o["order_id"]: (rng.random(), rng.random()) for o in orders}
        product_noise = [rng.random() for _ in products]

        # ---- cut the delivery
        truth = Truth()
        if batch == 1:
            orders = [dict(o, status=o["_b1_status"], updated_at=min(o["_b1_updated"], b1_end))
                      for o in orders if o["order_ts"] <= b1_end]
            keep = {o["order_id"] for o in orders}
            items = [i for i in items if i["order_id"] in keep]
            payments = [p for p in payments if p["order_id"] in keep and p["created_at"] <= b1_end]
            defects["late_status_changes"] = 0
        for o in orders:
            if kind_of[o["order_id"]] == "real":
                truth.orders[o["order_id"]] = {"order_id": o["order_id"], "customer_id": o["customer_id"],
                                               "status": o["status"], "order_ts": o["order_ts"],
                                               "order_date": o["order_ts"].date().isoformat(),
                                               "net_revenue": net_of[o["order_id"]]}
        defects["test_orders"] = sum(1 for o in orders if kind_of[o["order_id"]] == "test")
        defects["orphan_orders"] = sum(1 for o in orders if kind_of[o["order_id"]] == "orphan")
        defects["failed_payments"] = sum(1 for p in payments if p["status"] == "failed")
        defects["refunds"] = sum(1 for p in payments if p["status"] == "refunded")
        defects["bad_quantity_items"] = sum(1 for i in items if int(i["quantity"]) <= 0)
        defects["missing_price_items"] = sum(1 for i in items if i["unit_price"] == "")

        cust_rows = []
        for c, (r_stale, r_dup, r_email, r_country, stale_country) in zip(customers, row_noise):
            row = {k: c[k] for k in ("customer_id", "email", "first_name", "last_name", "country", "signup_date",
                                     "updated_at")}
            if batch == 2 and c["customer_id"] in new_country:
                row["country"], row["updated_at"] = new_country[c["customer_id"]]
                truth.customer_changes += 1
            if r_stale < 0.05:                                # an older version delivered alongside
                cust_rows.append(dict(row, country=stale_country.lower(),
                                      updated_at=row["updated_at"] - timedelta(days=3)))
                defects["stale_customer_versions"] += 1
            if r_dup < 0.04:                                  # exact re-delivery
                cust_rows.append(dict(row))
                defects["duplicate_customer_rows"] += 1
            if r_email < 0.15:
                row["email"] = f"  {row['email'].upper()} "
            if r_country < 0.1:
                row["country"] = row["country"].lower()
            cust_rows.append(row)
            if not c["is_test"]:
                truth.customers[c["customer_id"]] = {"customer_id": c["customer_id"], "email": c["email"],
                                                     "country": row["country"].upper()}

        order_rows = []
        for o in orders:
            r_case, r_dup = order_noise[o["order_id"]]
            row = {k: v for k, v in o.items() if not k.startswith("_")}
            if r_case < 0.08:
                row["status"] = row["status"].upper()
            elif r_case < 0.14:
                row["status"] = row["status"].title() + " "
            order_rows.append(row)
            if r_dup < 0.02:
                order_rows.append(dict(row))
                defects["duplicate_order_rows"] += 1

        truth.defects = defects
        tables = {
            "raw_customers": sorted(cust_rows, key=lambda r: (r["customer_id"], r["updated_at"])),
            "raw_products": [dict(p, category=p["category"] if r > 0.2 else f" {p['category'].upper()}")
                             for p, r in zip(products, product_noise)],
            "raw_orders": sorted(order_rows, key=lambda r: (r["order_ts"], r["order_id"])),
            "raw_order_items": [{k: v for k, v in i.items() if not k.startswith("_")} for i in items],
            "raw_payments": payments,
        }
        return tables, truth


def write_seeds(tables: dict[str, list[dict]], out: Path, loaded_at: datetime | None = None) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    loaded = _ts(loaded_at or datetime.now().replace(microsecond=0))
    counts = {}
    for name, rows in tables.items():
        cols = TABLES[name]
        with (out / f"{name}.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                rec = {}
                for c in cols:
                    v = loaded if c == "_loaded_at" else r.get(c, "")
                    if isinstance(v, datetime):
                        v = _ts(v)
                    elif isinstance(v, date):
                        v = v.isoformat()
                    elif isinstance(v, float):
                        v = f"{v:.2f}"
                    rec[c] = v
                w.writerow(rec)
        counts[name] = len(rows)
    return counts


def generate(out: Path, batch: int = 2, **kw) -> tuple[dict[str, int], Truth]:
    tables, truth = Generator(**kw).build(batch)
    return write_seeds(tables, out), truth
