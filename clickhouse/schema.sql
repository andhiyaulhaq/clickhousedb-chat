-- DDL extracted from docs/schema.md (copied from slm-text2sql-clickhouse). Run after CREATE DATABASE crm.
CREATE TABLE customers (
    customer_id String,
    name String,
    email String,
    company String,
    status LowCardinality(String),      -- 'lead','prospect','active','churned','blacklisted'
    segment LowCardinality(String),     -- 'Enterprise','Mid-Market','SMB'
    tags Array(String),                 -- values: 'high-value','tech','retail','finance','manufacturing','strategic'
    attributes Map(String, String),     -- keys: 'region' ('APAC','EMEA','NA','LATAM'), 'tier' ('Gold','Silver','Bronze'), 'industry' ('Technology','Retail','Finance','Manufacturing','Energy')
    created_at DateTime64(3),
    updated_at DateTime64(3)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY customer_id;

CREATE TABLE sales_reps (
    rep_id String,
    name String,
    team LowCardinality(String),        -- 'Inbound','Outbound-Enterprise','Account-Management'
    region LowCardinality(String)       -- 'APAC','EMEA','NA','LATAM'
) ENGINE = MergeTree ORDER BY rep_id;

CREATE TABLE deals (
    deal_id String,
    customer_id String,
    rep_id String,
    title String,
    stage LowCardinality(String),       -- 'qualification','proposal','negotiation','won','lost'
    value Float64,
    probability UInt8,                  -- 0..100
    products_involved Array(String),    -- values: 'Cloud-Storage-Pro','API-Gateway','Analytics-Suite','Security-Plus','CRM-Connect'
    created_date DateTime64(3),
    closed_date Nullable(DateTime64(3)),-- NULL while the deal is open
    updated_at DateTime64(3)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY deal_id;

CREATE TABLE activities (
    activity_id String,
    customer_id String,
    rep_id String,
    type LowCardinality(String),        -- 'call','email','meeting','demo','support_ticket'
    duration_minutes UInt16,
    sentiment LowCardinality(String),   -- 'positive','neutral','negative'
    timestamp DateTime64(3)
) ENGINE = MergeTree ORDER BY (customer_id, timestamp);

CREATE TABLE support_tickets (
    ticket_id String,
    customer_id String,
    priority LowCardinality(String),    -- 'low','medium','high','urgent'
    status LowCardinality(String),      -- 'open','in_progress','resolved','closed'
    resolution_time_hours Nullable(Float32), -- NULL until resolved
    created_at DateTime64(3),
    updated_at DateTime64(3)
) ENGINE = ReplacingMergeTree(updated_at) ORDER BY ticket_id;
