# From prototype to product

## Principle: keep the brain, replace the shell
`app/analytics.py` has no UI or database imports. In the final version FastAPI calls it unchanged;
only the layers around it get replaced.

| Prototype | Final |
|---|---|
| Streamlit pages (`views.py`) | HTML/CSS/JS front end + Plotly.js, calling a REST API |
| `db.py` (pandas + SQLAlchemy) | FastAPI + SQLAlchemy models/sessions + Alembic migrations |
| none | Authentication, roles, multi-tenancy |
| local Docker Postgres | Managed PostgreSQL (Neon / Supabase / RDS / Cloud SQL) |
| manual run | GitHub Actions CI (tests + lint) -> deploy to Render / Fly.io / Railway / AWS |

## Phases
1. **Prototype (this repo)** - validate that the answers are useful with real data. Load your own products and 3-6 months of sales.
2. **API** - FastAPI endpoints: `/products`, `/sales`, `/receipts`, `/losses`, `/analysis`, `/forecast`, `/purchase-orders`. Pydantic validation, pytest.
3. **Auth + tenancy** - add `organization_id` to every table, row-level filtering on every query. Use a hosted identity provider (Auth0, Clerk, Supabase Auth, Keycloak) or FastAPI-Users with JWT. Roles: owner, manager, staff (read-only / data-entry).
4. **Front end** - dashboard, tables, forms in HTML/CSS/JS with Plotly.js.
5. **Inventory depth** (what Zoho Inventory / Cin7 customers expect):
   - multiple warehouses/locations and stock transfers
   - purchase-order workflow (draft -> sent -> partially received -> closed) and supplier records
   - sales orders, returns, backorders
   - FIFO / weighted-average costing, batch/lot and expiry tracking
   - barcodes / SKU variants / bundles, stock counts and adjustments with audit trail
   - sales-channel and accounting integrations (Shopify, WooCommerce, Xero, QuickBooks), CSV/API import
6. **Production hardening** - backups, audit log, rate limiting, monitoring, background jobs for nightly recalculation, caching/materialised views once data grows.

## Decisions to make before phase 3
- Who are the first real users (your own shop, or a product for many businesses)? That decides multi-tenancy depth.
- Which sales channels do they use? That decides the first integration.
- Currency / tax / language requirements (e.g. Thai baht, VAT, Thai-language UI).
