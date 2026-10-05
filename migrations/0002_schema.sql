-- 0002_schema.sql
-- Domain tables. Manual reference data is loaded by the operator; this file only creates schema.
-- inventory_movements.op_date is GENERATED ALWAYS from op_ts, so INSERT and COPY must omit it.
-- receipt_lines.discount_pct and clearance_flag default to 0 because the simulation logic never sets them.
-- daily_opening_stock.quantity cannot be negative.

CREATE TABLE storage_locations (
    id BIGSERIAL PRIMARY KEY,
    location_type VARCHAR(50) NOT NULL,
    CONSTRAINT storage_locations_location_type_check CHECK (
        location_type IN ('склад', 'магазин')
    )
);

CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    category_l1 VARCHAR(100) NOT NULL,
    category_l2 VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    purchase_price NUMERIC(28, 2) NOT NULL,
    retail_price NUMERIC(28, 2) NOT NULL,
    avg_daily_sales NUMERIC(28, 2) NOT NULL,
    CONSTRAINT products_purchase_price_check CHECK (purchase_price >= 0),
    CONSTRAINT products_retail_price_check CHECK (retail_price >= 0),
    CONSTRAINT products_avg_daily_sales_check CHECK (avg_daily_sales >= 0)
);

CREATE INDEX idx_products_category_l2 ON products (category_l2);

CREATE TABLE warehouses (
    id BIGSERIAL PRIMARY KEY,
    storage_location_id BIGINT NOT NULL UNIQUE REFERENCES storage_locations (id),
    name VARCHAR(100) NOT NULL
);

CREATE TABLE stores (
    id BIGSERIAL PRIMARY KEY,
    storage_location_id BIGINT NOT NULL UNIQUE REFERENCES storage_locations (id),
    warehouse_id BIGINT NOT NULL REFERENCES warehouses (id),
    name VARCHAR(100) NOT NULL UNIQUE,
    avg_receipts_per_day NUMERIC(28, 2) NOT NULL,
    sku_capacity INT NOT NULL,
    open_from TIME NOT NULL,
    open_to TIME NOT NULL,
    optimization_flag INT NOT NULL DEFAULT 0,
    CONSTRAINT stores_sku_capacity_check CHECK (sku_capacity >= 0),
    CONSTRAINT stores_open_hours_check CHECK (open_from < open_to),
    CONSTRAINT stores_optimization_flag_check CHECK (optimization_flag IN (0, 1, 2))
);

CREATE TABLE store_name_pool (
    name VARCHAR(100) PRIMARY KEY
);

CREATE TABLE calculation_parameters (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    avg_receipts_per_day BIGINT NOT NULL,
    avg_receipt_amount NUMERIC(28, 2) NOT NULL,
    avg_sku_capacity BIGINT NOT NULL,
    min_receipt_amount NUMERIC(28, 2) NOT NULL,
    max_receipt_amount NUMERIC(28, 2) NOT NULL,
    target_stock_days_warehouse INT NOT NULL,
    target_stock_days_store INT NOT NULL,
    CONSTRAINT calculation_parameters_id_check CHECK (id = 1),
    CONSTRAINT calculation_parameters_receipt_bounds_check CHECK (
        min_receipt_amount <= max_receipt_amount
    ),
    CONSTRAINT calculation_parameters_warehouse_days_check CHECK (
        target_stock_days_warehouse > 0
    ),
    CONSTRAINT calculation_parameters_store_days_check CHECK (target_stock_days_store > 0)
);

CREATE TABLE store_assortment (
    store_id BIGINT NOT NULL REFERENCES stores (id),
    product_id BIGINT NOT NULL REFERENCES products (id),
    avg_daily_sales NUMERIC(28, 2) NOT NULL,
    PRIMARY KEY (store_id, product_id)
);

CREATE TABLE daily_opening_stock (
    stock_date DATE NOT NULL,
    storage_location_id BIGINT NOT NULL REFERENCES storage_locations (id),
    product_id BIGINT NOT NULL REFERENCES products (id),
    quantity BIGINT NOT NULL,
    PRIMARY KEY (stock_date, storage_location_id, product_id),
    CONSTRAINT daily_opening_stock_quantity_check CHECK (quantity >= 0)
);

CREATE TABLE inventory_movements (
    id BIGSERIAL PRIMARY KEY,
    op_ts TIMESTAMP NOT NULL,
    op_date DATE GENERATED ALWAYS AS (op_ts::date) STORED,
    product_id BIGINT NOT NULL REFERENCES products (id),
    storage_location_id BIGINT NOT NULL REFERENCES storage_locations (id),
    sender_location_id BIGINT REFERENCES storage_locations (id),
    receiver_location_id BIGINT REFERENCES storage_locations (id),
    quantity BIGINT NOT NULL,
    op_type VARCHAR(50) NOT NULL,
    CONSTRAINT inventory_movements_quantity_check CHECK (quantity <> 0),
    CONSTRAINT inventory_movements_op_type_check CHECK (
        op_type IN ('приход', 'перемещение', 'продажа')
    )
);

CREATE INDEX idx_inventory_movements_op_date_location_product
    ON inventory_movements (op_date, storage_location_id, product_id);

CREATE TABLE receipts (
    id BIGSERIAL PRIMARY KEY,
    store_id BIGINT NOT NULL REFERENCES stores (id),
    receipt_ts TIMESTAMP NOT NULL
);

CREATE INDEX idx_receipts_store_ts ON receipts (store_id, receipt_ts);

CREATE TABLE receipt_lines (
    receipt_id BIGINT NOT NULL REFERENCES receipts (id),
    product_id BIGINT NOT NULL REFERENCES products (id),
    quantity INT NOT NULL,
    sale_price NUMERIC(28, 2) NOT NULL,
    discount_pct NUMERIC(28, 2) NOT NULL DEFAULT 0,
    clearance_flag INT NOT NULL DEFAULT 0,
    PRIMARY KEY (receipt_id, product_id),
    CONSTRAINT receipt_lines_quantity_check CHECK (quantity > 0),
    CONSTRAINT receipt_lines_clearance_flag_check CHECK (clearance_flag IN (0, 1))
);
