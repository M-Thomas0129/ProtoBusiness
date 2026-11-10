"""Run with:  pytest   (or)   python tests/test_analytics.py"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from datetime import date, timedelta
import pandas as pd
from app import analytics as an

AS_OF = date(2026, 6, 30)
CFG = an.Config(as_of=AS_OF, velocity_days=30, safety_days=7, order_cycle_days=30,
                stockout_warning_days=7, dead_days=90, slow_cover_days=120,
                target_margin=0.30, seasonal_adjust=True, growth=0.0)


def products():
    rows = [
        # sku, name, cat, supplier, cost, price, lead, moq, opening, on_order
        ("FAST", "Fast mover", "A", "S1", 10, 20, 10, 12, 100, 0),
        ("DEAD", "Dead item", "A", "S1", 10, 20, 10, 1, 50, 0),
        ("LOSS", "Loss maker", "B", "S2", 50, 60, 10, 1, 500, 0),
        ("SLOW", "Slow item", "B", "S2", 10, 20, 10, 1, 500, 0),
        ("ONORD", "Covered by open PO", "B", "S2", 10, 20, 10, 12, 20, 200),
    ]
    return pd.DataFrame(rows, columns=["sku", "name", "category", "supplier", "unit_cost", "list_price",
                                       "lead_time_days", "moq", "opening_stock", "on_order"]).assign(is_active=True)


def daily(sku, start, end, qty, price):
    d, out = start, []
    while d <= end:
        out.append((d, sku, qty, price)); d += timedelta(days=1)
    return out


def sales():
    recent = (AS_OF - timedelta(days=29), AS_OF)       # exactly the 30-day window
    rows = daily("FAST", *recent, 3, 20)               # 90 units
    rows += daily("DEAD", AS_OF - timedelta(days=200), AS_OF - timedelta(days=120), 1, 20)
    rows += daily("LOSS", *recent, 1, 40)              # sells below its cost of 50
    rows += daily("SLOW", *recent, 1, 20)              # 30 units, 470 left
    rows += daily("ONORD", *recent, 1, 20)             # 30 units, stock goes negative
    return pd.DataFrame(rows, columns=["sold_on", "sku", "qty", "unit_price"])


def losses():
    return pd.DataFrame([(AS_OF - timedelta(days=5), "FAST", 2, "Damaged")], columns=["lost_on", "sku", "qty", "reason"])


def run():
    return an.build_analysis(products(), sales(), pd.DataFrame(), losses(), CFG).set_index("sku")


def test_on_hand_includes_sales_and_losses():
    a = run()
    assert a.loc["FAST", "on_hand"] == 100 - 90 - 2
    assert a.loc["DEAD", "on_hand"] == 50 - 81


def test_fast_mover_reorder_quantity_rounds_up_to_moq():
    f = run().loc["FAST"]
    assert f["avg_daily"] == 3.0
    assert f["reorder_point"] == 51                      # 3 * (10 + 7)
    assert f["order_up_to"] == 141                       # 3 * (10 + 7 + 30)
    assert f["status"] == "REORDER NOW"
    assert f["order_qty"] == 144                         # ceil((141 - 8) / 12) * 12 = 12 * 12
    assert bool(f["run_out"]) is True                    # 8 / 3 = 2.7 days of cover


def test_dead_stock_detected_and_not_reordered():
    d = pd.DataFrame(run()).loc["SLOW"]
    # DEAD has negative on-hand in this fixture, so give it stock and re-run
    p = products(); p.loc[p.sku == "DEAD", "opening_stock"] = 500
    a = an.build_analysis(p, sales(), None, losses(), CFG).set_index("sku")
    assert a.loc["DEAD", "status"] == "DEAD STOCK"
    assert a.loc["DEAD", "order_qty"] == 0
    assert a.loc["DEAD", "stock_value"] == (500 - 81) * 10


def test_slow_mover():
    a = run()
    assert a.loc["SLOW", "status"] == "SLOW MOVER"       # 470 units / 1 per day


def test_loss_maker_profit_status_and_issue_text():
    a = run().loc["LOSS"]
    assert a["gp_all"] == 30 * (40 - 50)
    assert a["profit_status"] == "LOSING MONEY"
    assert "below cost" in a["issues"]


def test_open_purchase_order_suppresses_reorder():
    p = products(); p.loc[p.sku == "ONORD", "opening_stock"] = 100
    a = an.build_analysis(p, sales(), None, None, CFG).set_index("sku")
    assert a.loc["ONORD", "on_hand"] == 70
    assert a.loc["ONORD", "order_qty"] == 0              # 70 + 200 on order is above the reorder point of 17


def test_seasonal_index_and_forecast():
    # 12 complete months of history, December sells 3x a normal month
    rows = []
    for m in pd.date_range("2025-07-01", periods=12, freq="MS"):
        rows.append((m.date() + timedelta(days=1), "FAST", 30 if m.month != 12 else 90, 20))
    s = pd.DataFrame(rows, columns=["sold_on", "sku", "qty", "unit_price"])
    cfg = an.Config(as_of=date(2026, 7, 15), growth=0.0)
    a = an.build_analysis(products(), s, None, None, cfg)
    fc = an.build_forecast(products(), s, a, cfg)
    prod = an._prep_products(products())
    _, idx, summ = an.build_seasonality(prod, an._prep_sales(prod, s), cfg)
    assert summ.loc["FAST", "peak_month"] == "Dec"
    assert round(idx.loc["FAST", 12], 2) == round(90 / (420 / 12), 2)
    assert fc[fc.sku == "FAST"]["units"].tolist() == [30.0, 30.0, 30.0]   # Aug, Sep, Oct = normal months


def test_empty_data_does_not_crash():
    out = an.compute_all(products(), None, None, None, CFG)
    assert len(out["analysis"]) == 5
    assert out["kpis"]["revenue_window"] == 0


def test_kpis_and_purchase_orders():
    out = an.compute_all(products(), sales(), None, losses(), CFG)
    po = out["purchase_orders"]
    assert "FAST" in po["sku"].tolist()
    assert out["kpis"]["n_reorder"] >= 1


if __name__ == "__main__":
    ok = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); ok += 1; print("PASS", name)
    print(f"{ok} tests passed")
