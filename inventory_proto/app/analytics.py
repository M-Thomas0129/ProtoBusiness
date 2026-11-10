"""Business logic: every question the tool answers lives here.

Pure pandas. No database, no Streamlit, no web framework imports.
That is deliberate: the same module will be reused unchanged by the FastAPI
backend in the final version. DataFrames in, DataFrames out.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date

import numpy as np
import pandas as pd

NO_COVER = 9999.0          # "days of cover" when a product has no recent sales
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PRODUCT_COLS = ["sku", "name", "category", "supplier", "unit_cost", "list_price",
                "lead_time_days", "moq", "opening_stock", "on_order", "is_active"]
SALES_COLS = ["sold_on", "sku", "qty", "unit_price"]
RECEIPT_COLS = ["received_on", "sku", "qty", "reference"]
LOSS_COLS = ["lost_on", "sku", "qty", "reason"]


# --------------------------------------------------------------------------- config
@dataclass
class Config:
    as_of: date = field(default_factory=date.today)
    velocity_days: int = 30          # window that defines "current" daily sales
    safety_days: int = 7             # buffer on top of supplier lead time
    order_cycle_days: int = 30       # days of demand each order should cover
    stockout_warning_days: int = 7   # "runs out next week"
    dead_days: int = 90              # in stock but no sale for this long = dead
    slow_cover_days: int = 120       # stock covers this many days or more = slow
    target_margin: float = 0.30
    writeoff_alert: float = 0.03     # write-offs as share of revenue
    seasonal_adjust: bool = True
    growth: float = 0.05             # forecast growth vs last year

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        kw = {}
        for f in fields(cls):
            v = d.get(f.name)
            if v is None or str(v).strip() == "":
                continue
            t = str(f.type)
            if f.name == "as_of":
                kw[f.name] = date.fromisoformat(str(v)[:10])
            elif t == "int":
                kw[f.name] = int(float(v))
            elif t == "float":
                kw[f.name] = float(v)
            elif t == "bool":
                kw[f.name] = str(v).strip().lower() in ("1", "true", "yes", "on")
        return cls(**kw)

    def to_dict(self, store_as_of: bool = False) -> dict:
        d = {f.name: str(getattr(self, f.name)) for f in fields(self)}
        if not store_as_of:
            d["as_of"] = ""          # blank = "use today"
        return d


# --------------------------------------------------------------------------- cleaning
def _frame(df, cols):
    if df is None or len(df) == 0:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    return df.copy()


def _prep_products(products) -> pd.DataFrame:
    p = _frame(products, PRODUCT_COLS)
    for c in ("unit_cost", "list_price"):
        p[c] = pd.to_numeric(p[c]).astype(float)
    for c in ("lead_time_days", "moq", "opening_stock", "on_order"):
        p[c] = pd.to_numeric(p[c]).fillna(0).astype(float)
    p["moq"] = p["moq"].clip(lower=1)
    if "is_active" in p.columns and len(p):
        p = p[p["is_active"].fillna(True).astype(bool)]
    return p.drop_duplicates("sku").reset_index(drop=True)


def _prep_sales(prod: pd.DataFrame, sales) -> pd.DataFrame:
    s = _frame(sales, SALES_COLS)
    s["sold_on"] = pd.to_datetime(s["sold_on"])
    s["qty"] = pd.to_numeric(s["qty"]).astype(float)
    s["unit_price"] = pd.to_numeric(s["unit_price"]).astype(float)
    s = s.merge(prod[["sku", "unit_cost"]], on="sku", how="inner")
    s["revenue"] = s["qty"] * s["unit_price"]
    s["cogs"] = s["qty"] * s["unit_cost"]
    return s


def _prep_qty(df, cols, date_col, prod=None) -> pd.DataFrame:
    d = _frame(df, cols)
    d[date_col] = pd.to_datetime(d[date_col])
    d["qty"] = pd.to_numeric(d["qty"]).astype(float)
    if prod is not None:
        d = d.merge(prod[["sku", "unit_cost"]], on="sku", how="inner")
        d["cost"] = d["qty"] * d["unit_cost"]
    return d


# --------------------------------------------------------------------------- seasonality
def seasonal_window(cfg: Config):
    """Last 12 *complete* calendar months: [start, end)."""
    end = pd.Timestamp(cfg.as_of).replace(day=1)
    return end - pd.DateOffset(months=12), end


def build_seasonality(prod: pd.DataFrame, s: pd.DataFrame, cfg: Config):
    """Returns (units_by_month, seasonal_index, summary), all indexed by sku."""
    start, end = seasonal_window(cfg)
    skus = pd.Index(prod["sku"], name="sku")
    w = s[(s["sold_on"] >= start) & (s["sold_on"] < end)]
    units = pd.DataFrame(0.0, index=skus, columns=range(1, 13))
    if len(w):
        g = w.groupby(["sku", w["sold_on"].dt.month])["qty"].sum().unstack(fill_value=0.0)
        units = g.reindex(index=skus, columns=range(1, 13), fill_value=0.0).fillna(0.0)
    avg = units.sum(axis=1) / 12.0
    index = units.div(avg.replace(0, np.nan), axis=0).fillna(0.0)
    strength = index.max(axis=1) - index.min(axis=1)
    has = avg > 0
    summary = pd.DataFrame({
        "total_12m": units.sum(axis=1),
        "avg_month": avg,
        "peak_month": [MONTH_NAMES[int(units.loc[k].values.argmax())] if has[k] else "-" for k in skus],
        "low_month": [MONTH_NAMES[int(units.loc[k].values.argmin())] if has[k] else "-" for k in skus],
        "strength": strength.where(has, 0.0),
    }, index=skus)
    summary["pattern"] = np.select([summary["strength"] >= 1.0, summary["strength"] >= 0.5],
                                   ["Highly seasonal", "Moderate"], "Steady")
    return units, index, summary


# --------------------------------------------------------------------------- core analysis
def build_analysis(products, sales, receipts, losses, cfg: Config) -> pd.DataFrame:
    """One row per active product: stock, profit, velocity, reorder advice, flags."""
    prod = _prep_products(products)
    s = _prep_sales(prod, sales)
    r = _prep_qty(receipts, RECEIPT_COLS, "received_on")
    lo = _prep_qty(losses, LOSS_COLS, "lost_on", prod)
    as_of = pd.Timestamp(cfg.as_of)
    p = prod.set_index("sku")
    idx = p.index

    def by_sku(df, col, mask=None):
        d = df if mask is None else df[mask]
        return d.groupby("sku")[col].sum().reindex(idx).fillna(0.0)

    A = pd.DataFrame(index=idx)
    A["product"], A["category"], A["supplier"] = p["name"], p["category"], p["supplier"]
    A["unit_cost"], A["list_price"] = p["unit_cost"], p["list_price"]
    A["lead_time"], A["moq"], A["on_order"] = p["lead_time_days"], p["moq"], p["on_order"]

    # stock = opening + received - sold - lost
    A["on_hand"] = p["opening_stock"] + by_sku(r, "qty") - by_sku(s, "qty") - by_sku(lo, "qty")

    # lifetime sales & profit
    A["units_all"] = by_sku(s, "qty")
    A["rev_all"] = by_sku(s, "revenue")
    A["cogs_all"] = by_sku(s, "cogs")
    A["gp_all"] = A["rev_all"] - A["cogs_all"]
    A["margin"] = np.where(A["rev_all"] > 0, A["gp_all"] / A["rev_all"].replace(0, np.nan), 0.0)
    A["writeoff"] = by_sku(lo, "cost")
    A["net"] = A["gp_all"] - A["writeoff"]

    # recent momentum
    v = pd.Timedelta(days=cfg.velocity_days)
    in_win = (s["sold_on"] > as_of - v) & (s["sold_on"] <= as_of)
    in_prior = (s["sold_on"] > as_of - 2 * v) & (s["sold_on"] <= as_of - v)
    A["units_win"] = by_sku(s, "qty", in_win)
    A["units_prior"] = by_sku(s, "qty", in_prior)
    A["rev_win"] = by_sku(s, "revenue", in_win)
    A["trend"] = np.where(A["units_prior"] > 0, A["units_win"] / A["units_prior"].replace(0, np.nan) - 1, np.nan)
    A["rank"] = A["rev_win"].where(A["rev_win"] > 0).rank(ascending=False, method="min")

    # demand, seasonality, cover
    _, sidx, _ = build_seasonality(prod, s, cfg)
    A["avg_daily"] = A["units_win"] / cfg.velocity_days
    if cfg.seasonal_adjust and len(A):
        m_lead = np.array([(as_of + pd.Timedelta(days=int(d))).month for d in A["lead_time"]])
        arr = sidx.reindex(idx).to_numpy()
        i_now = arr[:, as_of.month - 1]
        i_lead = arr[np.arange(len(A)), m_lead - 1]
        ratio = np.divide(i_lead, i_now, out=np.ones(len(A)), where=i_now > 0)
        A["seasonal_factor"] = np.clip(ratio, 0.5, 2.0)
    else:
        A["seasonal_factor"] = 1.0
    A["adj_daily"] = A["avg_daily"] * A["seasonal_factor"]
    A["cover"] = np.where(A["avg_daily"] > 0, A["on_hand"].clip(lower=0) / A["avg_daily"].replace(0, np.nan), NO_COVER)
    A["stockout_date"] = (as_of + pd.to_timedelta(A["cover"].where(A["cover"] < NO_COVER), unit="D")).dt.normalize()
    last = s.groupby("sku")["sold_on"].max().reindex(idx)
    A["last_sale"] = last
    A["days_since"] = np.where(last.notna(), (as_of - last).dt.days, NO_COVER)

    # reorder planning
    A["reorder_point"] = np.ceil(A["adj_daily"] * (A["lead_time"] + cfg.safety_days))
    A["order_up_to"] = np.ceil(A["adj_daily"] * (A["lead_time"] + cfg.safety_days + cfg.order_cycle_days))
    position = A["on_hand"] + A["on_order"]
    active = (A["adj_daily"] > 0) & (A["days_since"] < cfg.dead_days)
    need = active & (position <= A["reorder_point"])
    A["order_qty"] = np.where(need, np.ceil(np.maximum(A["order_up_to"] - position, 1) / A["moq"]) * A["moq"], 0.0)
    days_to_rop = np.floor(np.maximum(0, (position - A["reorder_point"]) / A["adj_daily"].replace(0, np.nan)))
    A["reorder_by"] = (as_of + pd.to_timedelta(days_to_rop.where(active), unit="D")).dt.normalize()
    A["po_cost"] = A["order_qty"] * A["unit_cost"]

    # flags
    A["status"] = np.select(
        [(A["on_hand"] > 0) & (A["days_since"] >= cfg.dead_days),
         (A["on_hand"] <= 0) & (A["avg_daily"] > 0),
         A["order_qty"] > 0,
         (A["on_hand"] > 0) & (A["cover"] >= cfg.slow_cover_days)],
        ["DEAD STOCK", "OUT OF STOCK", "REORDER NOW", "SLOW MOVER"], "OK")
    A["run_out"] = (A["avg_daily"] > 0) & (A["cover"] <= cfg.stockout_warning_days)
    A["profit_status"] = np.select(
        [A["rev_all"] == 0, A["net"] < 0, A["margin"] < cfg.target_margin],
        ["NO SALES", "LOSING MONEY", "BELOW TARGET"], "PROFITABLE")

    def issues(row):
        out = []
        if row.gp_all < 0: out.append("Selling below cost.")
        elif row.rev_all > 0 and row.margin < cfg.target_margin: out.append("Margin below target.")
        if row.writeoff > cfg.writeoff_alert * row.rev_all: out.append("High write-offs.")
        if row.status == "DEAD STOCK": out.append("Cash tied up in dead stock.")
        if row.status == "OUT OF STOCK": out.append("Out of stock - losing sales.")
        return " ".join(out)
    A["issues"] = A.apply(issues, axis=1) if len(A) else ""

    A["stock_value"] = A["on_hand"] * A["unit_cost"]
    price = np.where(A["units_win"] > 0, A["rev_win"] / A["units_win"].replace(0, np.nan), A["list_price"])
    A["forecast_30d"] = A["adj_daily"] * 30 * price
    return A.reset_index()


# --------------------------------------------------------------------------- forecast & trend
def build_forecast(products, sales, analysis: pd.DataFrame, cfg: Config, months: int = 3) -> pd.DataFrame:
    """Long table: sku x next N months -> units, price, revenue, gross profit."""
    prod = _prep_products(products)
    s = _prep_sales(prod, sales)
    units, sidx, summ = build_seasonality(prod, s, cfg)
    start, end = seasonal_window(cfg)
    w = s[(s["sold_on"] >= start) & (s["sold_on"] < end)]
    rev = w.groupby("sku")["revenue"].sum().reindex(units.index).fillna(0.0)
    price = (rev / summ["total_12m"].replace(0, np.nan)).fillna(prod.set_index("sku")["list_price"])
    cost = prod.set_index("sku")["unit_cost"]
    dead = analysis.set_index("sku")["status"].eq("DEAD STOCK").reindex(units.index).fillna(False)
    first = pd.Timestamp(cfg.as_of).replace(day=1)
    rows = []
    for k in range(1, months + 1):
        m = first + pd.DateOffset(months=k)
        u = (summ["avg_month"] * sidx[m.month] * (1 + cfg.growth)).round().where(~dead, 0.0)
        rows.append(pd.DataFrame({"sku": units.index, "month": m, "units": u.values,
                                  "price": price.values, "revenue": (u * price).values,
                                  "gross_profit": (u * (price - cost.reindex(units.index))).values}))
    out = pd.concat(rows, ignore_index=True)
    names = prod.set_index("sku")["name"]
    out.insert(1, "product", out["sku"].map(names))
    return out


def monthly_trend(products, sales, forecast: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Last 12 complete months (actual) followed by forecast months."""
    prod = _prep_products(products)
    s = _prep_sales(prod, sales)
    start, end = seasonal_window(cfg)
    months = pd.date_range(start, periods=12, freq="MS")
    w = s[(s["sold_on"] >= start) & (s["sold_on"] < end)]
    g = w.groupby(w["sold_on"].dt.to_period("M").dt.to_timestamp()).agg(
        units=("qty", "sum"), revenue=("revenue", "sum"), cogs=("cogs", "sum")).reindex(months).fillna(0.0)
    act = pd.DataFrame({"month": months, "units": g["units"].values, "revenue_actual": g["revenue"].values,
                        "gross_profit": (g["revenue"] - g["cogs"]).values, "revenue_forecast": np.nan})
    cur = s[(s["sold_on"] >= end) & (s["sold_on"] <= pd.Timestamp(cfg.as_of))]      # month-to-date
    act.loc[len(act)] = [end, cur["qty"].sum(), cur["revenue"].sum(), cur["revenue"].sum() - cur["cogs"].sum(), np.nan]
    f = forecast.groupby("month").agg(units=("units", "sum"), revenue_forecast=("revenue", "sum"),
                                      gross_profit=("gross_profit", "sum")).reset_index()
    f["revenue_actual"] = np.nan
    out = pd.concat([act, f[act.columns]], ignore_index=True)
    out["label"] = out["month"].dt.strftime("%b %y")
    out.loc[out["month"] == end, "label"] += " (so far)"
    return out


# --------------------------------------------------------------------------- helpers for the UI / API
def kpis(a: pd.DataFrame) -> dict:
    rev = a["rev_all"].sum()
    return {
        "revenue_window": a["rev_win"].sum(),
        "gross_profit": a["gp_all"].sum(),
        "net_profit": a["net"].sum(),
        "gross_margin": (a["gp_all"].sum() / rev) if rev > 0 else 0.0,
        "inventory_value": a["stock_value"].sum(),
        "dead_stock_value": a.loc[a["status"] == "DEAD STOCK", "stock_value"].sum(),
        "writeoffs": a["writeoff"].sum(),
        "forecast_30d": a["forecast_30d"].sum(),
        "n_reorder": int(a["status"].isin(["REORDER NOW", "OUT OF STOCK"]).sum()),
        "n_run_out": int(a["run_out"].sum()),
        "n_dead_slow": int(a["status"].isin(["DEAD STOCK", "SLOW MOVER"]).sum()),
        "n_margin_problems": int(a["profit_status"].isin(["LOSING MONEY", "BELOW TARGET"]).sum()),
    }


def purchase_orders(a: pd.DataFrame) -> pd.DataFrame:
    """Suggested purchase orders: one line per product to reorder (grouped by supplier in the UI)."""
    po = a[a["order_qty"] > 0][["supplier", "sku", "product", "on_hand", "on_order", "cover",
                                "order_qty", "unit_cost", "po_cost", "reorder_by"]].copy()
    po["supplier"] = po["supplier"].fillna("(no supplier)")
    return po.sort_values(["supplier", "cover"]).reset_index(drop=True)


def stock_history(sku, products, sales, receipts, losses, cfg: Config) -> pd.DataFrame:
    """Daily on-hand units for one product, rebuilt from opening stock and the transaction logs."""
    prod = _prep_products(products)
    opening = float(prod.loc[prod["sku"] == sku, "opening_stock"].iloc[0])
    s = _prep_sales(prod, sales); s = s[s["sku"] == sku]
    r = _prep_qty(receipts, RECEIPT_COLS, "received_on"); r = r[r["sku"] == sku]
    lo = _prep_qty(losses, LOSS_COLS, "lost_on"); lo = lo[lo["sku"] == sku]
    parts = [r.groupby("received_on")["qty"].sum(),
             -s.groupby("sold_on")["qty"].sum(),
             -lo.groupby("lost_on")["qty"].sum()]
    parts = [x for x in parts if len(x)]
    if not parts:
        return pd.DataFrame({"date": [pd.Timestamp(cfg.as_of)], "on_hand": [opening]})
    net = pd.concat(parts).groupby(level=0).sum()
    days = pd.date_range(net.index.min(), max(net.index.max(), pd.Timestamp(cfg.as_of)), freq="D")
    stock = opening + net.reindex(days, fill_value=0.0).cumsum()
    return pd.DataFrame({"date": days, "on_hand": stock.values})


def compute_all(products, sales, receipts, losses, cfg: Config) -> dict:
    a = build_analysis(products, sales, receipts, losses, cfg)
    prod = _prep_products(products)
    s = _prep_sales(prod, sales)
    units, sidx, summ = build_seasonality(prod, s, cfg)
    fc = build_forecast(products, sales, a, cfg)
    return {"analysis": a, "seasonal_units": units, "seasonal_index": sidx, "seasonal_summary": summ,
            "forecast": fc, "trend": monthly_trend(products, sales, fc, cfg), "kpis": kpis(a),
            "purchase_orders": purchase_orders(a)}
