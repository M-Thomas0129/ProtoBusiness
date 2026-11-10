# Inventory & Sales Prototype

Answers, per product: *what is selling, what/when/how much to reorder, where we lose money,
what runs out next week, what is dead or slow, is it profitable, and how sales flow by season.*

**Stack (prototype):** Python · PostgreSQL · pandas · Streamlit (+ SQLAlchemy, Plotly)

## Quick start

```bash
docker compose up -d                      # PostgreSQL 16 on :5432
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                      # Windows: copy .env.example .env
python -m app.seed                        # creates tables + loads fictional sample data (ends today)
streamlit run streamlit_app.py
```

Run the logic tests (no database needed): `python tests/test_analytics.py` (or `pytest`).
Re-load sample data from scratch: `python -m app.seed --reset`.

## Layout

```
app/analytics.py   ALL business rules (pure pandas, no DB/UI imports)  <- reused as-is by FastAPI later
app/db.py          PostgreSQL access (SQLAlchemy) - the only file that talks to the database
app/seed.py        Schema creation + sample-data generator
app/views.py       Streamlit screens (thin: display only)
streamlit_app.py   Navigation, caching, DB-connection check
sql/schema.sql     Tables: products, sales, receipts, losses, settings
tests/             Unit tests for the analytics rules
docs/ROADMAP.md    Path from this prototype to the final product
```

## How the numbers are decided (all configurable on the Settings page)

| Concept | Rule |
|---|---|
| On hand | opening stock + receipts - sales - losses |
| Current demand | units sold in the last *N* days (default 30) / N |
| Days of cover | on hand / current demand |
| Seasonal factor | seasonal index of the month the order will arrive / index of this month, clamped 0.5x-2x |
| Reorder point | expected daily demand x (lead time + safety days) |
| Reorder when | on hand + on order <= reorder point |
| Order quantity | (daily demand x (lead + safety + order-cycle days)) - on hand - on order, rounded **up** to the MOQ |
| Dead stock | in stock, no sale for 90+ days |
| Slow mover | stock covers 120+ days at the current rate |
| Profit | revenue - (qty x unit cost) - write-offs; LOSING MONEY if negative, BELOW TARGET if margin < target |
| Seasonal index | month units / average month, over the last 12 complete months |
| Forecast | avg monthly units x seasonal index x (1 + growth); dead stock = 0 |

## Known prototype limitations (by design)

- **Single user, single location, no login.** Anyone who can open the app sees everything.
- **Costing:** margin uses each product's *current* unit cost for all history (no FIFO / weighted average).
- **Seasonality** needs ~12 months of history per product; newer products show distorted patterns.
- Forecasts don't know about promotions, price changes or supplier problems you haven't logged.
- Lost sales during stock-outs can't be measured.
- Analysis recomputes on every refresh (cached 60 s) - fine for thousands of products, not millions of rows.
- The Streamlit screens were written without being run in the authoring environment (no Streamlit/PostgreSQL there);
  the analytics engine is unit-tested. Expect to fix small UI/API-version issues on first run.
