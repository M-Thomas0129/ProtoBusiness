"""PostgreSQL access (SQLAlchemy + pandas). Kept separate from analytics so it can be swapped later."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
DEFAULT_URL = "postgresql+psycopg2://inventory:inventory@localhost:5432/inventory"

# Allow-list: table name -> (date column, insertable columns). Prevents SQL injection via table names.
TABLES = {
    "products": (None, ["sku", "name", "category", "supplier", "unit_cost", "list_price",
                        "lead_time_days", "moq", "opening_stock", "on_order", "is_active"]),
    "sales": ("sold_on", ["sold_on", "sku", "qty", "unit_price"]),
    "receipts": ("received_on", ["received_on", "sku", "qty", "reference"]),
    "losses": ("lost_on", ["lost_on", "sku", "qty", "reason"]),
}


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(os.getenv("DATABASE_URL", DEFAULT_URL), pool_pre_ping=True)


def ping() -> None:
    with get_engine().connect() as c:
        c.execute(text("SELECT 1"))


def init_schema() -> None:
    with get_engine().begin() as c:
        c.exec_driver_sql(SCHEMA.read_text())


def reset_data() -> None:
    with get_engine().begin() as c:
        c.exec_driver_sql("TRUNCATE sales, receipts, losses, products, settings RESTART IDENTITY CASCADE")


def read_table(name: str) -> pd.DataFrame:
    if name not in TABLES:
        raise ValueError(name)
    order = {"products": "sku"}.get(name, f"{TABLES[name][0]} DESC, id DESC")
    return pd.read_sql(text(f"SELECT * FROM {name} ORDER BY {order}"), get_engine())


def load_all() -> dict:
    return {t: read_table(t) for t in TABLES}


def insert_df(name: str, df: pd.DataFrame) -> int:
    cols = TABLES[name][1]
    df = df[cols].copy()
    df.to_sql(name, get_engine(), if_exists="append", index=False, method="multi", chunksize=1000)
    return len(df)


def insert_row(name: str, row: dict) -> None:
    cols = TABLES[name][1]
    sql = f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    with get_engine().begin() as c:
        c.execute(text(sql), {k: row.get(k) for k in cols})


def delete_ids(name: str, ids: list[int]) -> None:
    if name == "products" or not ids:
        return
    with get_engine().begin() as c:
        c.execute(text(f"DELETE FROM {name} WHERE id = ANY(:ids)"), {"ids": [int(i) for i in ids]})


def upsert_products(df: pd.DataFrame) -> int:
    cols = TABLES["products"][1]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "sku")
    sql = (f"INSERT INTO products ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
           f"ON CONFLICT (sku) DO UPDATE SET {sets}")
    recs = []
    for r in df.to_dict("records"):
        if not str(r.get("sku") or "").strip():
            continue
        recs.append({
            "sku": str(r["sku"]).strip(), "name": str(r.get("name") or r["sku"]),
            "category": r.get("category") or None, "supplier": r.get("supplier") or None,
            "unit_cost": float(r.get("unit_cost") or 0), "list_price": float(r.get("list_price") or 0),
            "lead_time_days": int(r.get("lead_time_days") or 0), "moq": max(int(r.get("moq") or 1), 1),
            "opening_stock": int(r.get("opening_stock") or 0), "on_order": int(r.get("on_order") or 0),
            "is_active": bool(r.get("is_active", True)),
        })
    if recs:
        with get_engine().begin() as c:
            c.execute(text(sql), recs)
    return len(recs)


def load_settings() -> dict:
    with get_engine().connect() as c:
        return {k: v for k, v in c.execute(text("SELECT key, value FROM settings")).all()}


def save_settings(d: dict) -> None:
    with get_engine().begin() as c:
        for k, v in d.items():
            c.execute(text("INSERT INTO settings (key, value) VALUES (:k, :v) "
                           "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"), {"k": k, "v": v})
