-- 0005_sale_periods.sql
-- Operator-entered sale periods. A store-day uses the smallest price_factor
-- among periods that include that day. price_factor is the share of the retail price.

CREATE TABLE sale_periods (
    id BIGSERIAL PRIMARY KEY,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    price_factor NUMERIC(8, 4) NOT NULL,
    CONSTRAINT sale_periods_dates_check CHECK (date_from <= date_to),
    CONSTRAINT sale_periods_factor_check CHECK (price_factor > 0 AND price_factor < 1)
);

CREATE TABLE sale_period_stores (
    sale_period_id BIGINT NOT NULL REFERENCES sale_periods (id),
    store_id BIGINT NOT NULL REFERENCES stores (id),
    PRIMARY KEY (sale_period_id, store_id)
);

CREATE INDEX idx_sale_period_stores_store ON sale_period_stores (store_id);
