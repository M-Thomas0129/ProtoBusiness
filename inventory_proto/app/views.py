"""Streamlit screens. Thin: they only display what analytics.py computes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from . import analytics as an
from . import db

STATUS_COLORS = {
    "REORDER NOW": "#F8CBAD", "OUT OF STOCK": "#FF9999", "DEAD STOCK": "#D9D2E9", "SLOW MOVER": "#FFF2CC",
    "OK": "#E2EFDA", "LOSING MONEY": "#FF9999", "BELOW TARGET": "#FFF2CC", "PROFITABLE": "#E2EFDA",
}
LABELS = {
    "sku": "SKU", "product": "Product", "category": "Category", "supplier": "Supplier", "status": "Status",
    "on_hand": "On hand", "on_order": "On order", "cover": "Days of cover", "avg_daily": "Avg daily sales",
    "units_win": "Units (recent)", "rev_win": "Revenue (recent)", "trend": "Trend vs prior", "margin": "Gross margin",
    "reorder_by": "Reorder by", "order_qty": "Order qty", "po_cost": "Est. PO cost", "stockout_date": "Stock-out date",
    "days_since": "Days since last sale", "stock_value": "Cash tied up", "rev_all": "Revenue (all)",
    "writeoff": "Write-offs", "net": "Net profit", "profit_status": "Profit status", "issues": "Why",
    "reorder_point": "Reorder point", "order_up_to": "Order-up-to", "seasonal_factor": "Seasonal factor",
    "lead_time": "Lead time (d)", "moq": "MOQ", "gp_all": "Gross profit", "unit_cost": "Unit cost",
    "list_price": "List price", "last_sale": "Last sale", "units_all": "Units (all)", "forecast_30d": "Forecast 30d",
}
FORMATS = {
    "on_hand": "{:,.0f}", "on_order": "{:,.0f}", "cover": "{:,.1f}", "avg_daily": "{:,.1f}", "units_win": "{:,.0f}",
    "rev_win": "{:,.0f}", "trend": "{:+.0%}", "margin": "{:.1%}", "reorder_by": "{:%d %b %Y}", "order_qty": "{:,.0f}",
    "po_cost": "{:,.0f}", "stockout_date": "{:%d %b %Y}", "days_since": "{:,.0f}", "stock_value": "{:,.0f}",
    "rev_all": "{:,.0f}", "writeoff": "{:,.0f}", "net": "{:,.0f}", "reorder_point": "{:,.0f}", "order_up_to": "{:,.0f}",
    "seasonal_factor": "{:.2f}", "lead_time": "{:,.0f}", "moq": "{:,.0f}", "gp_all": "{:,.0f}", "unit_cost": "{:,.2f}",
    "list_price": "{:,.2f}", "last_sale": "{:%d %b %Y}", "units_all": "{:,.0f}", "forecast_30d": "{:,.0f}",
}


def show(df: pd.DataFrame, cols: list[str], key: str | None = None):  # key kept for API symmetry
    """Display a table with friendly headers, number formats and status colours."""
    d = df[cols].copy()
    for c in ("cover", "days_since"):
        if c in d:
            d[c] = d[c].where(d[c] < an.NO_COVER)           # 9999 sentinel -> blank
    d = d.rename(columns=LABELS)
    fmt = {LABELS[c]: FORMATS[c] for c in cols if c in FORMATS}
    sty = d.style.format(fmt, na_rep="–")
    status_cols = [LABELS[c] for c in ("status", "profit_status") if c in cols]
    if status_cols:
        paint = lambda v: f"background-color: {STATUS_COLORS.get(v, '')}; font-weight: 600" if v in STATUS_COLORS else ""
        sty = (sty.map if hasattr(sty, "map") else sty.applymap)(paint, subset=status_cols)
    st.dataframe(sty, hide_index=True)


def money(x: float) -> str:
    return f"{x:,.0f}"


# ------------------------------------------------------------------------------------------ dashboard
def dashboard(b: dict, cfg: an.Config):
    a, k = b["analysis"], b["kpis"]
    st.title("Dashboard")
    st.caption(f"As of {cfg.as_of:%d %b %Y} · amounts in your own currency")
    if a.empty:
        st.info("No products yet. Add some on the **Products** page or run `python -m app.seed` for sample data.")
        return

    c = st.columns(4)
    c[0].metric(f"Revenue (last {cfg.velocity_days} days)", money(k["revenue_window"]))
    c[1].metric("Gross profit (all data)", money(k["gross_profit"]))
    c[2].metric("Net profit after write-offs", money(k["net_profit"]))
    c[3].metric("Gross margin", f"{k['gross_margin']:.1%}")
    c = st.columns(4)
    c[0].metric("Inventory value (cost)", money(k["inventory_value"]))
    c[1].metric("Cash tied up in dead stock", money(k["dead_stock_value"]))
    c[2].metric("Write-offs (cost)", money(k["writeoffs"]))
    c[3].metric("Forecast revenue, next 30 days", money(k["forecast_30d"]))
    c = st.columns(4)
    c[0].metric("To reorder now", k["n_reorder"])
    c[1].metric(f"Running out ≤ {cfg.stockout_warning_days} days", k["n_run_out"])
    c[2].metric("Dead + slow-moving", k["n_dead_slow"])
    c[3].metric("Margin problems", k["n_margin_problems"])

    left, right = st.columns([3, 2])
    with left:
        t = b["trend"]
        fig = go.Figure()
        fig.add_bar(x=t["label"], y=t["revenue_actual"], name="Actual", marker_color="#2F5597")
        fig.add_bar(x=t["label"], y=t["revenue_forecast"], name="Forecast", marker_color="#ED7D31")
        fig.update_layout(title="Monthly revenue: last 12 months + 3-month forecast", barmode="overlay",
                          margin=dict(t=50, b=10), legend=dict(orientation="h", y=-0.15), yaxis_tickformat=",")
        st.plotly_chart(fig)
    with right:
        top = a[a["rev_win"] > 0].nlargest(5, "rev_win").sort_values("rev_win")
        fig = px.bar(top, x="rev_win", y="product", orientation="h",
                     title=f"What is selling - top 5 (last {cfg.velocity_days} days)")
        fig.update_layout(margin=dict(t=50, b=10), yaxis_title=None, xaxis_title=None, xaxis_tickformat=",")
        st.plotly_chart(fig)

    tabs = st.tabs(["Reorder", "Running out", "Dead & slow", "Losing money", "Top sellers"])
    with tabs[0]:
        d = a[a["status"].isin(["REORDER NOW", "OUT OF STOCK"])].sort_values("cover")
        st.write(f"**{len(d)}** products at or below their reorder point.") if len(d) else st.success("Nothing to reorder.")
        if len(d):
            show(d, ["sku", "product", "status", "on_hand", "on_order", "cover", "reorder_by", "order_qty", "po_cost"])
    with tabs[1]:
        d = a[a["run_out"]].sort_values("cover")
        if len(d):
            show(d, ["sku", "product", "on_hand", "avg_daily", "cover", "stockout_date", "on_order", "status"])
        else:
            st.success(f"Nothing expected to run out within {cfg.stockout_warning_days} days.")
    with tabs[2]:
        d = a[a["status"].isin(["DEAD STOCK", "SLOW MOVER"])].sort_values("stock_value", ascending=False)
        if len(d):
            d = d.assign(action=np.where(d["status"] == "DEAD STOCK", "Clearance / stop buying", "Pause reorders, promote"))
            LABELS["action"] = "Suggested action"
            show(d, ["sku", "product", "status", "on_hand", "days_since", "stock_value", "cover", "action"])
        else:
            st.success("No dead or slow-moving stock.")
    with tabs[3]:
        d = a[a["profit_status"].isin(["LOSING MONEY", "BELOW TARGET"])].sort_values("net")
        if len(d):
            show(d, ["sku", "product", "rev_all", "margin", "writeoff", "net", "profit_status", "issues"])
        else:
            st.success("Every product is at or above target margin.")
    with tabs[4]:
        d = a[a["rev_win"] > 0].sort_values("rev_win", ascending=False)
        show(d, ["sku", "product", "units_win", "rev_win", "trend", "margin", "on_hand", "cover"])


# ------------------------------------------------------------------------------------------ inventory
def inventory(b: dict):
    a = b["analysis"]
    st.title("Inventory")
    if a.empty:
        st.info("No products yet."); return
    f1, f2, f3 = st.columns(3)
    status = f1.multiselect("Stock status", sorted(a["status"].unique()))
    cat = f2.multiselect("Category", sorted(a["category"].dropna().unique()))
    q = f3.text_input("Search SKU or product")
    d = a
    if status: d = d[d["status"].isin(status)]
    if cat: d = d[d["category"].isin(cat)]
    if q: d = d[d["sku"].str.contains(q, case=False) | d["product"].str.contains(q, case=False)]
    show(d, ["sku", "product", "category", "status", "on_hand", "on_order", "avg_daily", "cover", "reorder_point",
             "order_qty", "margin", "net", "profit_status", "stock_value"])
    st.download_button("Download CSV", d.to_csv(index=False).encode(), "inventory_analysis.csv", "text/csv")


def product_detail(b: dict, data: dict, cfg: an.Config):
    a = b["analysis"]
    st.title("Product detail")
    if a.empty:
        st.info("No products yet."); return
    sku = st.selectbox("Product", a["sku"], format_func=lambda s: f"{s} - {a.set_index('sku').loc[s, 'product']}")
    r = a.set_index("sku").loc[sku]
    c = st.columns(5)
    c[0].metric("Status", r["status"]); c[1].metric("On hand", f"{r['on_hand']:,.0f}")
    c[2].metric("Days of cover", "–" if r["cover"] >= an.NO_COVER else f"{r['cover']:.1f}")
    c[3].metric("Gross margin", f"{r['margin']:.1%}"); c[4].metric("Suggested order", f"{r['order_qty']:,.0f}")
    if r["issues"]:
        st.warning(r["issues"])
    h = an.stock_history(sku, data["products"], data["sales"], data["receipts"], data["losses"], cfg)
    fig = px.line(h, x="date", y="on_hand", title="Stock level over time")
    fig.add_hline(y=r["reorder_point"], line_dash="dash", line_color="#C00000", annotation_text="Reorder point")
    fig.update_layout(margin=dict(t=50, b=10))
    st.plotly_chart(fig)
    s = data["sales"]
    s = s[s["sku"] == sku].copy()
    if len(s):
        s["sold_on"] = pd.to_datetime(s["sold_on"]); s["qty"] = s["qty"].astype(float)
        w = s.set_index("sold_on")["qty"].resample("W").sum().reset_index()
        st.plotly_chart(px.bar(w, x="sold_on", y="qty", title="Units sold per week").update_layout(margin=dict(t=50, b=10)))
    idx = b["seasonal_index"].loc[sku]
    st.plotly_chart(px.bar(x=an.MONTH_NAMES, y=idx.values, title="Seasonal index (1.0 = average month)")
                    .update_layout(margin=dict(t=50, b=10), xaxis_title=None, yaxis_title=None))


# ------------------------------------------------------------------------------------------ purchase orders
def purchase_orders(b: dict):
    st.title("Suggested purchase orders")
    po = b["purchase_orders"]
    if po.empty:
        st.success("Nothing needs ordering right now."); return
    st.caption("Grouped by supplier. Quantities are rounded up to each product's minimum order quantity.")
    st.metric("Total suggested spend", money(po["po_cost"].sum()))
    for sup, g in po.groupby("supplier"):
        with st.expander(f"{sup} - {len(g)} line(s) - {money(g['po_cost'].sum())}", expanded=True):
            show(g, ["sku", "product", "on_hand", "on_order", "cover", "reorder_by", "order_qty", "unit_cost", "po_cost"],
                 key=f"po_{sup}")
            st.download_button("Download this PO (CSV)", g.to_csv(index=False).encode(), f"PO_{sup}.csv", "text/csv", key=f"dl_{sup}")
    st.download_button("Download all lines (CSV)", po.to_csv(index=False).encode(), "purchase_orders.csv", "text/csv")


# ------------------------------------------------------------------------------------------ seasonality
def seasonality(b: dict):
    st.title("Seasonality & forecast")
    a = b["analysis"]
    if a.empty:
        st.info("No products yet."); return
    names = a.set_index("sku")["product"]
    idx = b["seasonal_index"]
    fig = px.imshow(idx.values, x=an.MONTH_NAMES, y=[f"{s} {names.get(s, '')}" for s in idx.index],
                    color_continuous_scale="RdBu_r", zmin=0, zmax=2, aspect="auto",
                    title="Seasonal index by product (1.0 = average month; needs ~12 months of history)")
    fig.update_layout(margin=dict(t=50, b=10), height=max(300, 28 * len(idx) + 120))
    st.plotly_chart(fig)
    sm = b["seasonal_summary"].reset_index()
    sm["product"] = sm["sku"].map(names)
    sm = sm.rename(columns={"peak_month": "Peak", "low_month": "Low", "pattern": "Pattern", "strength": "Strength",
                            "total_12m": "Units (12 mo)", "product": "Product", "sku": "SKU"})
    st.dataframe(sm[["SKU", "Product", "Units (12 mo)", "Peak", "Low", "Strength", "Pattern"]]
                 .style.format({"Units (12 mo)": "{:,.0f}", "Strength": "{:.2f}"}), hide_index=True)
    st.subheader("Revenue forecast - next 3 months")
    st.caption("Forecast = average monthly units × seasonal index × (1 + growth assumption). Dead stock is forecast at 0.")
    fc = b["forecast"]
    p = fc.pivot_table(index=["sku", "product"], columns="month", values="revenue", aggfunc="sum")
    p.columns = [c.strftime("%b %Y") for c in p.columns]
    p.loc[("", "TOTAL"), :] = p.sum()
    st.dataframe(p.reset_index().rename(columns={"sku": "SKU", "product": "Product"})
                 .style.format({c: "{:,.0f}" for c in p.columns}), hide_index=True)


# ------------------------------------------------------------------------------------------ data entry
def products_page(data: dict):
    st.title("Products")
    st.caption("Edit in place, add rows at the bottom, then Save. Untick **Active** to retire a product "
               "(products with history can't be deleted).")
    df = data["products"].drop(columns=["created_at"], errors="ignore")
    for c in ("unit_cost", "list_price"):
        df[c] = df[c].astype(float)
    edited = st.data_editor(
        df, num_rows="dynamic", hide_index=True, key="products_editor",
        column_config={
            "sku": st.column_config.TextColumn("SKU", required=True),
            "name": st.column_config.TextColumn("Product", required=True),
            "unit_cost": st.column_config.NumberColumn("Unit cost", min_value=0.0, format="%.2f"),
            "list_price": st.column_config.NumberColumn("List price", min_value=0.0, format="%.2f"),
            "lead_time_days": st.column_config.NumberColumn("Lead time (d)", min_value=0, step=1),
            "moq": st.column_config.NumberColumn("MOQ", min_value=1, step=1),
            "opening_stock": st.column_config.NumberColumn("Opening stock", step=1,
                                                           help="Units on hand BEFORE the first logged transaction"),
            "on_order": st.column_config.NumberColumn("On order", min_value=0, step=1,
                                                      help="Units ordered but not yet received"),
            "is_active": st.column_config.CheckboxColumn("Active", default=True),
        })
    if st.button("Save products", type="primary"):
        n = db.upsert_products(edited)
        st.cache_data.clear()
        st.success(f"Saved {n} product(s)."); st.rerun()


TXN = {
    "sales": dict(date="sold_on", label="sale"),
    "receipts": dict(date="received_on", label="delivery"),
    "losses": dict(date="lost_on", label="write-off"),
}
LOSS_REASONS = ["Damaged", "Expired / defective", "Theft / shrinkage", "Returned - unsellable", "Other"]


def _txn_tab(kind: str, data: dict, today):
    spec = TXN[kind]; dcol = spec["date"]
    prods = data["products"]
    prods = prods[prods["is_active"]] if len(prods) else prods
    if prods.empty:
        st.info("Add products first."); return
    lookup = prods.set_index("sku")
    with st.form(f"add_{kind}", clear_on_submit=True):
        c = st.columns(4)
        d = c[0].date_input("Date", today)
        sku = c[1].selectbox("SKU", prods["sku"], format_func=lambda s: f"{s} - {lookup.loc[s, 'name']}")
        qty = c[2].number_input("Quantity", min_value=1, value=1, step=1)
        row = {dcol: d, "sku": sku, "qty": int(qty)}
        if kind == "sales":
            row["unit_price"] = c[3].number_input("Unit price sold", min_value=0.0, value=float(lookup.loc[sku, "list_price"]))
        elif kind == "receipts":
            row["reference"] = c[3].text_input("PO / reference")
        else:
            row["reason"] = c[3].selectbox("Reason", LOSS_REASONS)
        if st.form_submit_button(f"Add {spec['label']}", type="primary"):
            db.insert_row(kind, row); st.cache_data.clear()
            st.success(f"Added {spec['label']}."); st.rerun()

    with st.expander("Bulk import from CSV"):
        need = db.TABLES[kind][1]
        st.caption("Required columns: " + ", ".join(need if kind != "receipts" else need[:3]) +
                   (" (reference optional)" if kind == "receipts" else ""))
        up = st.file_uploader("CSV file", type="csv", key=f"up_{kind}")
        if up is not None:
            df = pd.read_csv(up)
            required = [c for c in need if c not in ("reference", "reason")]
            missing = [c for c in required if c not in df.columns]
            if missing:
                st.error(f"Missing columns: {missing}")
            else:
                df[dcol] = pd.to_datetime(df[dcol], errors="coerce").dt.date
                for opt in ("reference", "reason"):
                    if opt in need and opt not in df.columns: df[opt] = None
                bad = df[df[dcol].isna() | ~df["sku"].isin(lookup.index) | (pd.to_numeric(df["qty"], errors="coerce").fillna(0) <= 0)]
                if len(bad):
                    st.error(f"{len(bad)} row(s) have a bad date, unknown SKU or non-positive qty. Fix these and re-upload:")
                    st.dataframe(bad)
                else:
                    st.dataframe(df.head(10))
                    if st.button(f"Import {len(df)} rows", key=f"imp_{kind}"):
                        db.insert_df(kind, df); st.cache_data.clear()
                        st.success(f"Imported {len(df)} rows."); st.rerun()

    st.subheader("Recent entries")
    recent = data[kind].head(100)
    st.dataframe(recent, hide_index=True)
    with st.expander("Delete entries"):
        ids = st.multiselect("Select entry IDs to delete", recent["id"].tolist() if len(recent) else [], key=f"del_{kind}")
        if ids and st.button("Delete selected", key=f"delbtn_{kind}"):
            db.delete_ids(kind, ids); st.cache_data.clear(); st.rerun()


def transactions(data: dict, cfg: an.Config):
    st.title("Record activity")
    t1, t2, t3 = st.tabs(["Sales", "Deliveries (receipts)", "Write-offs (losses)"])
    for tab, kind in zip((t1, t2, t3), ("sales", "receipts", "losses")):
        with tab:
            _txn_tab(kind, data, cfg.as_of)


# ------------------------------------------------------------------------------------------ settings
def settings_page(cfg: an.Config):
    st.title("Settings")
    st.caption("These rules drive every flag and suggestion in the app.")
    with st.form("settings"):
        c = st.columns(2)
        use_today = c[0].checkbox("Use today's date as 'as of'", value=True)
        as_of = c[1].date_input("As-of date (if not using today)", cfg.as_of)
        v = c[0].number_input("Velocity window (days)", 7, 180, cfg.velocity_days)
        sf = c[1].number_input("Safety stock (days)", 0, 90, cfg.safety_days)
        oc = c[0].number_input("Order cycle (days of stock per order)", 1, 180, cfg.order_cycle_days)
        sw = c[1].number_input("Stock-out warning (days)", 1, 60, cfg.stockout_warning_days)
        dd = c[0].number_input("Dead stock: no sales for (days)", 14, 730, cfg.dead_days)
        sc = c[1].number_input("Slow mover: days of cover at least", 30, 730, cfg.slow_cover_days)
        tm = c[0].number_input("Target gross margin (%)", 0.0, 95.0, cfg.target_margin * 100)
        wo = c[1].number_input("Write-off alert (% of revenue)", 0.0, 50.0, cfg.writeoff_alert * 100)
        sa = c[0].checkbox("Use seasonal adjustment", value=cfg.seasonal_adjust)
        gr = c[1].number_input("Forecast growth vs last year (%)", -50.0, 200.0, cfg.growth * 100)
        if st.form_submit_button("Save settings", type="primary"):
            new = an.Config(as_of=as_of, velocity_days=int(v), safety_days=int(sf), order_cycle_days=int(oc),
                            stockout_warning_days=int(sw), dead_days=int(dd), slow_cover_days=int(sc),
                            target_margin=tm / 100, writeoff_alert=wo / 100, seasonal_adjust=sa, growth=gr / 100)
            db.save_settings(new.to_dict(store_as_of=not use_today))
            st.cache_data.clear(); st.success("Saved."); st.rerun()
