"""SQLite schemas of the ESP event stores.

ESP reads these files; collectors and the synthetic sample write them. The
earnings and econ tables match the production Benzinga and Nasdaq collectors.
"""

NEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id TEXT PRIMARY KEY,
    published_utc TEXT NOT NULL,          -- ISO 8601 UTC, e.g. 2025-03-24T20:05:00+00:00
    title TEXT NOT NULL,
    description TEXT,
    article_url TEXT,
    author TEXT,
    publisher TEXT,
    tickers TEXT NOT NULL DEFAULT '[]',   -- JSON array of upper-case symbols
    keywords TEXT NOT NULL DEFAULT '[]',  -- JSON array
    image_url TEXT,
    insights TEXT,                        -- JSON (optional)
    source TEXT
);
CREATE INDEX IF NOT EXISTS ix_news_published ON news(published_utc);
CREATE TABLE IF NOT EXISTS news_tickers (news_id TEXT NOT NULL, ticker TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_news_tickers ON news_tickers(ticker, news_id);
"""

EARNINGS_SCHEMA = """
CREATE TABLE earnings (
    benzinga_id TEXT PRIMARY KEY,
    ticker TEXT, company_name TEXT, currency TEXT,
    fiscal_year INTEGER, fiscal_period TEXT,
    date TEXT, time TEXT, date_status TEXT, last_updated TEXT,
    actual_eps REAL, estimated_eps REAL, previous_eps REAL,
    eps_surprise REAL, eps_surprise_percent REAL,
    actual_revenue REAL, estimated_revenue REAL,
    revenue_surprise REAL, revenue_surprise_percent REAL,
    importance INTEGER, raw_json TEXT
);
CREATE INDEX idx_earnings_ticker ON earnings(ticker);
CREATE INDEX idx_earnings_date ON earnings(date);
CREATE INDEX idx_earnings_updated ON earnings(last_updated);
"""

ECON_SCHEMA = """
CREATE TABLE econ_events (
    event_id TEXT PRIMARY KEY,
    date TEXT NOT NULL, country TEXT, event_name TEXT,
    gmt_raw TEXT, gmt_time TEXT,
    actual TEXT, consensus TEXT, previous TEXT,
    description TEXT, description_raw TEXT,
    fetched_at TEXT NOT NULL, raw_json TEXT
);
CREATE INDEX idx_econ_date ON econ_events(date);
CREATE INDEX idx_econ_date_country ON econ_events(date, country);
"""
