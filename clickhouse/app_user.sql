-- The only account the chat app connects as (docs/guide.md rule 2). Run by `pipeline.py setup`; {password} comes from APP_CH_PASSWORD.
-- readonly = 1: SELECT only, and the user cannot change any setting from a query.
DROP USER IF EXISTS app;

CREATE USER app IDENTIFIED BY '{password}' SETTINGS
    readonly = 1,
    max_execution_time = 10,
    max_result_rows = 10000,
    result_overflow_mode = 'break',
    max_memory_usage = 1000000000,
    output_format_json_quote_64bit_integers = 0;

GRANT SELECT ON crm.customers TO app;
GRANT SELECT ON crm.sales_reps TO app;
GRANT SELECT ON crm.deals TO app;
GRANT SELECT ON crm.activities TO app;
GRANT SELECT ON crm.support_tickets TO app;
