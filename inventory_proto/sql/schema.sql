-- Inventory prototype schema (PostgreSQL). Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS products (
    sku            TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT,
    supplier       TEXT,
    unit_cost      NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (unit_cost >= 0),
    list_price     NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (list_price >= 0),
    lead_time_days INTEGER       NOT NULL DEFAULT 14 CHECK (lead_time_days >= 0),
    moq            INTEGER       NOT NULL DEFAULT 1  CHECK (moq >= 1),
    opening_stock  INTEGER       NOT NULL DEFAULT 0,  -- units on hand before the first transaction
    on_order       INTEGER       NOT NULL DEFAULT 0 CHECK (on_order >= 0),
    is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales (
    id         BIGSERIAL PRIMARY KEY,
    sold_on    DATE    NOT NULL,
    sku        TEXT    NOT NULL REFERENCES products(sku) ON UPDATE CASCADE,
    qty        INTEGER NOT NULL CHECK (qty > 0),
    unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE IF NOT EXISTS receipts (
    id          BIGSERIAL PRIMARY KEY,
    received_on DATE    NOT NULL,
    sku         TEXT    NOT NULL REFERENCES products(sku) ON UPDATE CASCADE,
    qty         INTEGER NOT NULL CHECK (qty > 0),
    reference   TEXT
);

CREATE TABLE IF NOT EXISTS losses (
    id      BIGSERIAL PRIMARY KEY,
    lost_on DATE    NOT NULL,
    sku     TEXT    NOT NULL REFERENCES products(sku) ON UPDATE CASCADE,
    qty     INTEGER NOT NULL CHECK (qty > 0),
    reason  TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_sales_sku_date    ON sales (sku, sold_on);
CREATE INDEX IF NOT EXISTS idx_sales_date        ON sales (sold_on);
CREATE INDEX IF NOT EXISTS idx_receipts_sku_date ON receipts (sku, received_on);
CREATE INDEX IF NOT EXISTS idx_losses_sku_date   ON losses (sku, lost_on);
