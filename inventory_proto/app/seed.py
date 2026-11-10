"""Create the schema and load fictional sample data.

    python -m app.seed            # create tables + load sample data if the DB is empty
    python -m app.seed --reset    # wipe everything first
Sample data always ends today, so the dashboard looks "live".
"""
from __future__ import annotations

import math
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

PROFILES = {
    "flat":    [1.0] * 12,
    "summer":  [0.8, 0.9, 1.4, 1.8, 1.6, 1.1, 0.8, 0.7, 0.7, 0.7, 0.7, 0.8],
    "rainy":   [0.4, 0.4, 0.5, 0.7, 1.2, 1.6, 1.7, 1.8, 1.7, 1.5, 0.8, 0.5],
    "winter":  [1.7, 1.5, 0.9, 0.5, 0.4, 0.4, 0.4, 0.5, 0.6, 0.9, 1.6, 2.1],
    "holiday": [0.8, 0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.9, 1.0, 1.1, 1.7, 2.2],
    "fitness": [1.8, 1.3, 1.0, 0.9, 0.9, 0.8, 0.8, 0.8, 0.9, 0.9, 1.0, 1.0],
    "cool":    [1.4, 1.3, 1.0, 0.8, 0.7, 0.6, 0.6, 0.7, 0.9, 1.2, 1.5, 1.5],
}
# sku, name, category, supplier, cost, price, lead, moq, base units/day, season profile, target stock now, on_order
CATALOG = [
    ("WB-001", "Insulated Water Bottle 750ml", "Outdoor", "Northwind Supply", 180, 390, 14, 24, 5.0, "flat", 30, 0),
    ("SF-002", "Portable Fan", "Home", "Coolair Co.", 250, 520, 21, 12, 2.5, "summer", 60, 0),
    ("SU-003", "Sunscreen SPF50", "Personal Care", "SunCare Ltd", 90, 220, 10, 48, 4.0, "summer", 150, 0),
    ("UM-004", "Compact Umbrella", "Accessories", "RainGear", 70, 190, 10, 30, 3.0, "rainy", 120, 0),
    ("JK-005", "Fleece Jacket", "Apparel", "Alpine Textiles", 420, 990, 30, 10, 1.6, "winter", 28, 0),
    ("TS-006", "Cotton T-Shirt", "Apparel", "Alpine Textiles", 110, 290, 21, 50, 3.5, "flat", 200, 0),
    ("YM-007", "Yoga Mat", "Fitness", "FlexFit", 150, 390, 21, 20, 1.5, "fitness", 90, 0),
    ("FP-008", "Non-stick Frying Pan", "Kitchen", "HomeChef", 200, 450, 14, 20, 2.0, "holiday", 45, 40),
    ("CP-009", "Coffee Press", "Kitchen", "HomeChef", 160, 350, 14, 12, 0.7, "flat", 160, 0),
    ("LN-010", "LED Desk Lamp", "Home", "BrightLite", 245, 320, 21, 12, 1.6, "flat", 60, 0),
    ("PB-011", "Power Bank 10000mAh", "Electronics", "VoltTech", 260, 450, 14, 24, 2.2, "flat", 80, 0),
    ("DS-012", "Retro Desk Radio", "Electronics", "VoltTech", 520, 1190, 30, 6, 1.0, "flat", 40, 0),   # goes dead
    ("HN-013", "Hiking Backpack 30L", "Outdoor", "Northwind Supply", 480, 1190, 21, 6, 0.3, "cool", 60, 0),  # slow
    ("SC-014", "Scented Candle Set", "Home", "Glow & Co", 85, 260, 12, 36, 2.2, "holiday", 95, 0),
]
LOSS_REASONS = ["Damaged", "Expired / defective", "Theft / shrinkage", "Returned - unsellable"]


def generate_sample(end: date | None = None, seed: int = 11) -> dict:
    """Pure function (no DB). Returns DataFrames shaped like the database tables."""
    rng = np.random.default_rng(seed)
    end = end or date.today()
    start = end - timedelta(days=372)
    n_days = (end - start).days + 1
    dead_after = end - timedelta(days=135)          # radio stops selling
    discount_from = end - timedelta(days=310)       # power bank gets discounted below cost

    sales, losses = [], []
    for sku, _, _, _, cost, price, lead, moq, base, prof, tgt, onord in CATALOG:
        for i in range(n_days):
            d = start + timedelta(days=i)
            if sku == "DS-012" and d > dead_after:
                continue
            lam = base * PROFILES[prof][d.month - 1] * (1.15 if d.weekday() >= 5 else 1.0) * rng.uniform(0.85, 1.15)
            q = int(rng.poisson(lam))
            if q <= 0:
                continue
            if sku == "PB-011" and d >= discount_from:
                p = int(rng.choice([205, 215, 225, 235]))
            elif sku == "LN-010":
                p = round(price * float(rng.choice([1, 0.9, 0.9, 0.85])))
            else:
                p = round(price * float(rng.choice([1, 1, 1, 1, 0.9])))
            sales.append((d, sku, q, p))
    plan = {"PB-011": (7, (3, 6)), "SU-003": (4, (2, 5)), "WB-001": (3, (1, 3)), "DS-012": (2, (1, 2)),
            "UM-004": (2, (1, 3)), "TS-006": (3, (1, 3)), "SC-014": (2, (1, 3)), "CP-009": (1, (1, 2)),
            "FP-008": (2, (1, 2)), "LN-010": (2, (1, 2))}
    for sku, (n, (a, b)) in plan.items():
        for _ in range(n):
            d = start + timedelta(days=int(rng.integers(10, n_days - 5)))
            if sku == "DS-012" and d > dead_after:
                d = dead_after - timedelta(days=int(rng.integers(5, 40)))
            reason = "Expired / defective" if sku == "SU-003" else str(rng.choice(LOSS_REASONS))
            losses.append((d, sku, int(rng.integers(a, b + 1)), reason))

    sales_df = pd.DataFrame(sales, columns=["sold_on", "sku", "qty", "unit_price"])
    loss_df = pd.DataFrame(losses, columns=["lost_on", "sku", "qty", "reason"])

    # Monthly deliveries, then opening stock + a final top-up so stock today matches the target above.
    receipts, products = [], []
    months = pd.date_range(start.replace(day=1), end, freq="MS")
    for sku, name, cat, sup, cost, price, lead, moq, base, prof, tgt, onord in CATALOG:
        rec = []
        for m in months:
            d = m.date() + timedelta(days=int(rng.integers(2, 11)))
            if d < start or d > end - timedelta(days=6):
                continue
            if sku == "DS-012" and d > dead_after - timedelta(days=30):
                continue
            q = math.ceil(max(base * PROFILES[prof][m.month - 1] * 30 * 0.95, moq) / moq) * moq
            rec.append((d, q))
        events = [(d, q) for d, q in rec]
        events += [(r.sold_on, -r.qty) for r in sales_df[sales_df.sku == sku].itertuples()]
        events += [(r.lost_on, -r.qty) for r in loss_df[loss_df.sku == sku].itertuples()]
        events.sort(key=lambda e: (e[0], -e[1]))
        cum, low = 0, 0
        for _, q in events:
            cum += q; low = min(low, cum)
        opening = -low
        top_up = max(0, tgt - (opening + cum))
        if top_up:
            rec.append((dead_after - timedelta(days=30) if sku == "DS-012" else end - timedelta(days=5), top_up))
        receipts += [(d, sku, q, f"PO-{d:%y%m%d}-{sku}") for d, q in rec]
        products.append((sku, name, cat, sup, cost, price, lead, moq, opening, onord, True))

    return {
        "products": pd.DataFrame(products, columns=["sku", "name", "category", "supplier", "unit_cost", "list_price",
                                                    "lead_time_days", "moq", "opening_stock", "on_order", "is_active"]),
        "sales": sales_df,
        "receipts": pd.DataFrame(sorted(receipts), columns=["received_on", "sku", "qty", "reference"]),
        "losses": loss_df.sort_values("lost_on").reset_index(drop=True),
    }


def main(reset: bool = False) -> None:
    from . import db
    db.init_schema()
    if reset:
        db.reset_data()
    if len(db.read_table("products")):
        print("Database already has products - use --reset to replace them.")
        return
    data = generate_sample()
    db.upsert_products(data["products"])
    for t in ("sales", "receipts", "losses"):
        print(f"{t}: inserted {db.insert_df(t, data[t])} rows")
    print("Done. Run:  streamlit run streamlit_app.py")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
