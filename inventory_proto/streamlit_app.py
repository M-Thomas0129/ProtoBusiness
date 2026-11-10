"""Inventory & sales prototype.   Run:  streamlit run streamlit_app.py"""
import streamlit as st

from app import analytics as an
from app import db, views

st.set_page_config(page_title="Inventory Prototype", page_icon="📦", layout="wide")


@st.cache_data(ttl=60, show_spinner=False)
def load():
    return db.load_all(), db.load_settings()


@st.cache_data(ttl=60, show_spinner="Crunching numbers...")
def compute(data, cfg_dict):
    cfg = an.Config.from_dict(cfg_dict)
    return an.compute_all(data["products"], data["sales"], data["receipts"], data["losses"], cfg)


try:
    db.ping()
except Exception as e:                                   # noqa: BLE001
    st.error("Can't reach the database.")
    st.markdown("Start PostgreSQL and load sample data:\n```\ndocker compose up -d\npython -m app.seed\n```")
    st.caption(f"Details: {type(e).__name__}")
    st.stop()

@st.cache_resource
def _ensure_schema():
    db.init_schema()          # idempotent: CREATE TABLE IF NOT EXISTS


_ensure_schema()
data, settings = load()
cfg = an.Config.from_dict(settings)
bundle = compute(data, settings)

PAGES = {
    "📊 Dashboard": lambda: views.dashboard(bundle, cfg),
    "📦 Inventory": lambda: views.inventory(bundle),
    "🔎 Product detail": lambda: views.product_detail(bundle, data, cfg),
    "🧾 Purchase orders": lambda: views.purchase_orders(bundle),
    "🗓️ Seasonality & forecast": lambda: views.seasonality(bundle),
    "✍️ Record activity": lambda: views.transactions(data, cfg),
    "🏷️ Products": lambda: views.products_page(data),
    "⚙️ Settings": lambda: views.settings_page(cfg),
}
with st.sidebar:
    st.header("📦 Inventory")
    page = st.radio("Go to", list(PAGES), label_visibility="collapsed")
    st.divider()
    if st.button("Refresh data"):
        st.cache_data.clear(); st.rerun()
    st.caption("Prototype - single user, no login.")
PAGES[page]()
