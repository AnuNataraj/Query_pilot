"""Builds the demo retail warehouse: a realistic, deterministic SQLite database.

The data has patterns worth discovering: month-over-month growth, a holiday
spike in Nov/Dec, Smart Home rising while Audio declines, higher refund rates
on the mobile channel and on wearables, and customer churn.
"""
from __future__ import annotations

import bisect
import math
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

REGIONS = {
    "West": [("Seattle", "WA"), ("Portland", "OR"), ("San Francisco", "CA"), ("Los Angeles", "CA"), ("Denver", "CO"), ("Phoenix", "AZ")],
    "Central": [("Chicago", "IL"), ("Minneapolis", "MN"), ("Kansas City", "MO"), ("Omaha", "NE"), ("Columbus", "OH"), ("Detroit", "MI")],
    "East": [("New York", "NY"), ("Boston", "MA"), ("Philadelphia", "PA"), ("Washington", "DC"), ("Pittsburgh", "PA")],
    "South": [("Atlanta", "GA"), ("Miami", "FL"), ("Nashville", "TN"), ("Charlotte", "NC"), ("Houston", "TX"), ("Austin", "TX")],
}
REGION_WEIGHTS = {"West": 0.30, "East": 0.28, "South": 0.24, "Central": 0.18}

SEGMENTS = {  # segment: (share of customers, ordering frequency weight)
    "Consumer": (0.70, 1.0),
    "Small Business": (0.22, 2.5),
    "Enterprise": (0.08, 5.0),
}

# category: (cost as share of price, popularity trend per month, products)
CATALOG = {
    "Audio": (0.55, -0.015, [
        ("Studio Wireless Headphones", 199), ("Noise-Cancel Earbuds", 149), ("Portable Speaker", 89),
        ("Soundbar 2.1", 279), ("Vinyl Turntable", 229), ("Bluetooth Earbuds Lite", 49),
        ("Desktop Speakers", 119), ("Podcast Microphone", 129)]),
    "Smart Home": (0.50, 0.035, [
        ("Smart Thermostat", 179), ("Video Doorbell", 149), ("Smart Plug 4-Pack", 39),
        ("Mesh Wi-Fi System", 249), ("Smart Light Starter Kit", 99), ("Indoor Security Camera", 69),
        ("Robot Vacuum", 399), ("Smart Lock", 229)]),
    "Computing": (0.82, 0.0, [
        ("14-inch Ultrabook", 1099), ("Gaming Laptop", 1599), ("27-inch 4K Monitor", 379),
        ("Mechanical Keyboard", 129), ("Wireless Mouse", 39), ("USB-C Docking Station", 189),
        ("External SSD 2TB", 159), ("Tablet 11-inch", 499)]),
    "Wearables": (0.60, 0.01, [
        ("Fitness Tracker", 79), ("Smartwatch Pro", 349), ("Smartwatch Sport", 229),
        ("Smart Ring", 299), ("Kids Smartwatch", 99), ("Sleep Tracker Band", 59)]),
    "Gaming": (0.70, 0.005, [
        ("Game Console", 499), ("Wireless Controller", 69), ("Gaming Headset", 99),
        ("VR Headset", 449), ("Racing Wheel", 299), ("Streaming Capture Card", 179)]),
    "Accessories": (0.35, 0.0, [
        ("USB-C Cable 3-Pack", 19), ("65W GaN Charger", 45), ("Laptop Sleeve", 35),
        ("Screen Protector", 15), ("Power Bank 20000mAh", 55), ("Phone Case", 29),
        ("Cable Organizer Kit", 19), ("Laptop Stand", 49)]),
}

MONTH_SEASONALITY = {1: 0.80, 2: 0.85, 3: 0.95, 4: 0.95, 5: 1.0, 6: 1.0, 7: 1.05, 8: 1.05, 9: 0.95, 10: 1.0, 11: 1.35, 12: 1.6}
CHANNELS = [("web", 0.55), ("mobile", 0.30), ("store", 0.15)]
REFUND_RATE = {"web": 0.05, "mobile": 0.085, "store": 0.03}

FIRST_NAMES = ["Olivia", "Liam", "Emma", "Noah", "Ava", "Elijah", "Sophia", "Mateo", "Isabella", "Lucas",
               "Mia", "Levi", "Amelia", "Ethan", "Harper", "James", "Evelyn", "Aarav", "Priya", "Wei",
               "Mei", "Diego", "Sofia", "Omar", "Layla", "Kenji", "Yuki", "Arjun", "Ananya", "Grace",
               "Hannah", "Daniel", "Chloe", "Samuel", "Zoe", "Nora", "Leo", "Maya", "Ravi", "Fatima"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Lee", "Patel", "Nguyen",
              "Kim", "Chen", "Singh", "Shah", "Rao", "Clark", "Lewis", "Walker", "Hall", "Young", "King"]
COMPANY_SUFFIXES = ["Labs", "Studio", "Partners", "Group", "Works", "Systems", "Co"]

SCHEMA_SQL = """
CREATE TABLE customers (
    customer_id  INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    region       TEXT NOT NULL,
    segment      TEXT NOT NULL,
    signup_date  TEXT NOT NULL
);
CREATE TABLE products (
    product_id   INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit_price   REAL NOT NULL,
    unit_cost    REAL NOT NULL
);
CREATE TABLE orders (
    order_id     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date   TEXT NOT NULL,
    channel      TEXT NOT NULL,
    status       TEXT NOT NULL
);
CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,
    discount      REAL NOT NULL DEFAULT 0
);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
"""


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def build_warehouse(
    path: Path,
    *,
    today: date | None = None,
    months: int = 24,
    n_customers: int = 1200,
    base_daily_orders: float = 10.0,
    seed: int = 42,
) -> dict[str, int]:
    """Create (or replace) the warehouse at `path`. Returns row counts per table."""
    rng = random.Random(seed)
    today = today or date.today()
    end = today - timedelta(days=1)
    start_month = (today.year * 12 + today.month - 1) - (months - 1)
    start = date(start_month // 12, start_month % 12 + 1, 1)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA_SQL)

    # --- products -------------------------------------------------------------
    products = []  # (id, name, category, price, cost, trend)
    for category, (cost_ratio, trend, items) in CATALOG.items():
        for name, price in items:
            cost = round(price * cost_ratio * rng.uniform(0.92, 1.08), 2)
            products.append((len(products) + 1, name, category, float(price), cost, trend))
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?)", [p[:5] for p in products]
    )

    # --- customers ------------------------------------------------------------
    regions = list(REGION_WEIGHTS)
    region_w = list(REGION_WEIGHTS.values())
    segments = list(SEGMENTS)
    segment_w = [s[0] for s in SEGMENTS.values()]
    signup_span = (end - (start - timedelta(days=365))).days
    customers = []  # (id, signup, churn, segment)
    rows = []
    for _ in range(n_customers):
        region = rng.choices(regions, region_w)[0]
        city, state = rng.choice(REGIONS[region])
        segment = rng.choices(segments, segment_w)[0]
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        name = f"{first} {last}"
        if segment != "Consumer":
            name = f"{last} {rng.choice(COMPANY_SUFFIXES)}"
        # More recent signups as the business grows (sqrt skews toward later dates).
        offset = int(signup_span * math.sqrt(rng.random()))
        signup = start - timedelta(days=365) + timedelta(days=offset)
        churn = signup + timedelta(days=int(rng.expovariate(1 / 420)) + 30)
        customers.append((signup, churn, segment))
        rows.append((name, f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com",
                     city, state, region, segment, signup.isoformat()))
    order = sorted(range(n_customers), key=lambda i: customers[i][0])
    conn.executemany(
        "INSERT INTO customers (customer_id, name, email, city, state, region, segment, signup_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(rank + 1, *rows[i]) for rank, i in enumerate(order)],
    )
    customers = [customers[i] for i in order]  # index + 1 == customer_id
    signups = [c[0] for c in customers]
    cum_w, total = [], 0.0
    for _, _, segment in customers:
        total += SEGMENTS[segment][1]
        cum_w.append(total)

    # --- orders + items ---------------------------------------------------------
    order_rows, item_rows = [], []
    day = start
    while day <= end:
        m = _months_between(start, day)
        lam = base_daily_orders * (1.02 ** m) * MONTH_SEASONALITY[day.month]
        lam *= 1.15 if day.weekday() >= 5 else 1.0
        n_orders = max(0, round(rng.gauss(lam, math.sqrt(lam))))
        eligible = bisect.bisect_right(signups, day)
        prod_w = [(1 + p[5]) ** m / math.sqrt(p[3]) for p in products]
        for _ in range(n_orders if eligible else 0):
            cid = None
            for _try in range(6):
                idx = bisect.bisect_left(cum_w, rng.random() * cum_w[eligible - 1])
                if day <= customers[idx][1]:
                    cid = idx + 1
                    break
            if cid is None:
                continue
            segment = customers[cid - 1][2]
            channel = rng.choices([c for c, _ in CHANNELS], [w for _, w in CHANNELS])[0]
            if segment == "Enterprise" and channel == "store":
                channel = "web"
            order_id = len(order_rows) + 1
            has_wearable = False
            for product in rng.choices(products, prod_w, k=rng.choice([1, 1, 1, 2, 2, 3, 4])):
                qty = rng.choice([1, 1, 1, 2]) if segment == "Consumer" else rng.randint(1, 6 if segment == "Small Business" else 12)
                discount = 0.0
                if segment == "Enterprise":
                    discount = rng.choice([0.10, 0.10, 0.15])
                elif rng.random() < (0.30 if day.month in (11, 12) else 0.12):
                    discount = rng.choice([0.05, 0.10, 0.15, 0.20])
                item_rows.append((order_id, product[0], qty, product[3], discount))
                has_wearable |= product[2] == "Wearables"
            r = rng.random()
            refund_p = REFUND_RATE[channel] + (0.06 if has_wearable else 0)
            status = "cancelled" if r < 0.025 else "refunded" if r < 0.025 + refund_p else "completed"
            order_rows.append((order_id, cid, day.isoformat(), channel, status))
        day += timedelta(days=1)

    conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", order_rows)
    conn.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount) VALUES (?, ?, ?, ?, ?)",
        item_rows,
    )
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()
    path.unlink(missing_ok=True)
    tmp.replace(path)
    return {
        "customers": n_customers,
        "products": len(products),
        "orders": len(order_rows),
        "order_items": len(item_rows),
    }
