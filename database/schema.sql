PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS indicators (
    indicator_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    indicator_group TEXT NOT NULL,
    panel TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    region TEXT NOT NULL,
    frequency TEXT NOT NULL,
    unit TEXT NOT NULL,
    direction TEXT NOT NULL,
    collection_method TEXT NOT NULL,
    api_params_status TEXT NOT NULL,
    api_note TEXT,
    dashboard_role TEXT NOT NULL,
    confidence TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_id TEXT NOT NULL,
    base_period TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    region TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    collection_method TEXT NOT NULL,
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_updated_at TEXT,
    note TEXT,
    UNIQUE(indicator_id, base_period, region),
    FOREIGN KEY(indicator_id) REFERENCES indicators(indicator_id)
);

CREATE TABLE IF NOT EXISTS manual_credit_guarantee_monthly (
    base_month TEXT PRIMARY KEY,
    guarantee_supply_amount_krw INTEGER,
    guarantee_supply_count INTEGER,
    guarantee_balance_krw INTEGER,
    source_org TEXT NOT NULL,
    source_file_name TEXT,
    input_user TEXT NOT NULL,
    input_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(guarantee_supply_amount_krw IS NULL OR guarantee_supply_amount_krw >= 0),
    CHECK(guarantee_supply_count IS NULL OR guarantee_supply_count >= 0),
    CHECK(guarantee_balance_krw IS NULL OR guarantee_balance_krw >= 0)
);

CREATE TABLE IF NOT EXISTS manual_policy_fund_monthly (
    base_month TEXT PRIMARY KEY,
    program_name TEXT NOT NULL,
    total_plan_amount_krw INTEGER NOT NULL,
    cumulative_support_amount_krw INTEGER,
    cumulative_support_count INTEGER,
    execution_rate_pct REAL,
    source_org TEXT NOT NULL,
    source_url TEXT,
    source_file_name TEXT,
    input_user TEXT NOT NULL,
    input_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(total_plan_amount_krw >= 0),
    CHECK(cumulative_support_amount_krw IS NULL OR cumulative_support_amount_krw >= 0),
    CHECK(cumulative_support_count IS NULL OR cumulative_support_count >= 0),
    CHECK(execution_rate_pct IS NULL OR execution_rate_pct >= 0)
);

CREATE TABLE IF NOT EXISTS import_runs (
    import_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_ref TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    rows_read INTEGER NOT NULL DEFAULT 0,
    rows_written INTEGER NOT NULL DEFAULT 0,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_observations_indicator_period
ON observations(indicator_id, base_period);

