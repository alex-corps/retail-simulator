-- 0003_receipts_ts_index.sql
-- Day rollback deletes receipts by receipt_ts. idx_receipts_store_ts starts with store_id
-- and does not serve a range over the whole day.

CREATE INDEX idx_receipts_ts ON receipts (receipt_ts);
