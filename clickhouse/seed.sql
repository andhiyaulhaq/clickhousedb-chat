-- Random but realistic CRM data spanning the last 2 years, so relative-date queries return rows.
-- Random bitmasks pick array subsets per row (arrayShuffle on a constant is evaluated once).
-- Distinct rand(N) arguments keep ClickHouse from reusing one random value across columns.

INSERT INTO customers SELECT
    concat('C', toString(number)),
    concat(['Budi','Siti','Andi','Dewi','Rina','Agus','Maya','Joko'][number % 8 + 1], ' ', ['Santoso','Wijaya','Halim','Pratama','Saputra'][intDiv(number, 8) % 5 + 1]),
    concat('user', toString(number), '@example.com'),
    concat(['PT Maju','PT Sinar','CV Abadi','PT Nusantara','PT Global','PT Mitra'][number % 6 + 1], ' ', ['Teknologi','Retail','Logistik','Finansial','Energi'][intDiv(number, 6) % 5 + 1]),
    ['lead','prospect','active','active','churned','blacklisted'][rand(1) % 6 + 1],
    ['Enterprise','Mid-Market','SMB'][rand(2) % 3 + 1],
    arrayFilter((x, i) -> bitTest(rand(3) % 63 + 1, i), ['high-value','tech','retail','finance','manufacturing','strategic'], range(6)),
    map('region', ['APAC','EMEA','NA','LATAM'][rand(4) % 4 + 1], 'tier', ['Gold','Silver','Bronze'][rand(5) % 3 + 1], 'industry', ['Technology','Retail','Finance','Manufacturing','Energy'][rand(6) % 5 + 1]),
    toDateTime64(now() - rand(7) % (730 * 86400), 3) AS created_at,
    created_at
FROM numbers(2000);

-- Newer versions of 300 customers: only visible correctly with FINAL.
INSERT INTO customers SELECT
    customer_id, name, email, company,
    ['active','churned'][rand(1) % 2 + 1],
    segment, tags, attributes, created_at,
    now64(3) - toIntervalSecond(rand(2) % 86400)
FROM customers WHERE toUInt32(substring(customer_id, 2)) < 300;

INSERT INTO sales_reps SELECT
    concat('R', toString(number)),
    concat(['Eko','Fitri','Hendra','Indah','Kevin','Lina','Rudi','Tari'][number % 8 + 1], ' ', ['Gunawan','Lestari','Kusuma','Hidayat','Nugroho'][intDiv(number, 8) % 5 + 1]),
    ['Inbound','Outbound-Enterprise','Account-Management'][number % 3 + 1],
    ['APAC','EMEA','NA','LATAM'][rand(1) % 4 + 1]
FROM numbers(40);

INSERT INTO deals SELECT
    concat('D', toString(number)),
    concat('C', toString(rand(1) % 2000)),
    concat('R', toString(rand(2) % 40)),
    concat(['Renewal','Expansion','New Logo','Upsell','Migration'][rand(3) % 5 + 1], ' #', toString(number)),
    -- A deal whose close date would be in the future is still open.
    if(rand(4) % 6 >= 3 AND created_date + toIntervalDay(rand(10) % 120) > now64(3), 'negotiation',
       ['qualification','proposal','negotiation','won','won','lost'][rand(4) % 6 + 1]) AS stage,
    round(1000 + rand(5) % 500000 + (rand(6) % 100) / 100, 2),
    multiIf(stage = 'won', 100, stage = 'lost', 0, rand(7) % 90 + 5),
    arrayFilter((x, i) -> bitTest(rand(8) % 31 + 1, i), ['Cloud-Storage-Pro','API-Gateway','Analytics-Suite','Security-Plus','CRM-Connect'], range(5)),
    toDateTime64(now() - rand(9) % (730 * 86400), 3) AS created_date,
    if(stage IN ('won','lost'), created_date + toIntervalDay(rand(10) % 120), NULL) AS closed_date,
    ifNull(closed_date, created_date)
FROM numbers(8000);

INSERT INTO activities SELECT
    concat('A', toString(number)),
    concat('C', toString(rand(1) % 2000)),
    concat('R', toString(rand(2) % 40)),
    ['call','email','meeting','demo','support_ticket'][rand(3) % 5 + 1],
    rand(4) % 120 + 1,
    ['positive','positive','neutral','negative'][rand(5) % 4 + 1],
    toDateTime64(now() - rand(6) % (730 * 86400), 3)
FROM numbers(30000);

INSERT INTO support_tickets SELECT
    concat('T', toString(number)),
    concat('C', toString(rand(1) % 2000)),
    ['low','medium','medium','high','urgent'][rand(2) % 5 + 1],
    ['open','in_progress','resolved','closed','closed'][rand(3) % 5 + 1] AS status,
    if(status IN ('resolved','closed'), toFloat32(rand(4) % 2000 / 10), NULL) AS resolution,
    toDateTime64(now() - rand(5) % (730 * 86400), 3) AS created_at,
    least(created_at + toIntervalSecond(toUInt32(ifNull(resolution, rand(6) % 72) * 3600)), now64(3))
FROM numbers(5000);
