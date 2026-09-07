-- ANNEMS AI MARKETING DEPARTMENT — Supabase (Postgres) schema
-- Phase 1 tables only. Ref: CLAUDE.md section 5.
-- Run this once in the Supabase SQL editor, or: psql "$DATABASE_URL" -f db/schema.sql
-- Safe to re-run (idempotent).

-- ---------------------------------------------------------------
-- Core performance data
-- ---------------------------------------------------------------

create table if not exists campaigns (
    id                uuid primary key default gen_random_uuid(),
    meta_campaign_id  text unique not null,
    name              text not null,
    objective         text,
    status            text,
    created_at        timestamptz not null default now()
);

create table if not exists adsets (
    id             uuid primary key default gen_random_uuid(),
    meta_adset_id  text unique not null,
    campaign_id    text references campaigns(meta_campaign_id) on delete set null,
    name           text not null,
    audience_desc  text,
    status         text,
    created_at     timestamptz not null default now()
);

create table if not exists ads (
    id           uuid primary key default gen_random_uuid(),
    meta_ad_id   text unique not null,
    adset_id     text references adsets(meta_adset_id) on delete set null,
    name         text not null,
    status       text,
    creative_id  uuid,
    created_at   timestamptz not null default now()
);

create table if not exists creatives (
    id               uuid primary key default gen_random_uuid(),
    concept          text not null,
    angle            text not null,
    format           text not null,
    awareness_level  text not null,
    hook             text,
    primary_text     text,
    headline         text,
    cta              text,
    image_url        text,
    qa_score         numeric,
    qa_status        text,          -- PASS | FAIL | FLAGGED
    created_by       text,          -- agent_4 | aiman | tagging_log_import
    meta_ad_name     text,          -- links back to the manual Tagging Log
    created_at       timestamptz not null default now()
);

-- level: campaign | adset | ad
create table if not exists daily_metrics (
    id           uuid primary key default gen_random_uuid(),
    date         date not null,
    level        text not null,
    ref_id       text not null,
    spend        numeric not null default 0,
    impressions  bigint  not null default 0,
    clicks       bigint  not null default 0,
    reach        bigint  not null default 0,
    frequency    numeric not null default 0,
    leads        bigint  not null default 0,
    cpl          numeric,
    ctr          numeric,
    cpm          numeric,
    cpc          numeric,
    cvr          numeric,
    created_at   timestamptz not null default now(),
    unique (date, level, ref_id)
);

create table if not exists computed_baselines (
    id         uuid primary key default gen_random_uuid(),
    date       date not null,
    level      text not null,
    ref_id     text not null,
    metric     text not null,
    avg_7d     numeric,
    avg_14d    numeric,
    delta_pct  numeric,
    created_at timestamptz not null default now(),
    unique (date, level, ref_id, metric)
);

-- ---------------------------------------------------------------
-- CRM data
-- ---------------------------------------------------------------

-- stage: new | qualified | appointment | closed_won | closed_lost
create table if not exists leads (
    id               uuid primary key default gen_random_uuid(),
    ghl_contact_id   text unique not null,
    source_ad_id     text,
    stage            text not null default 'new',
    stage_updated_at timestamptz,
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------
-- System
-- ---------------------------------------------------------------

create table if not exists alerts (
    id            uuid primary key default gen_random_uuid(),
    rule          text not null,
    severity      text not null,       -- info | warn | critical
    message       text not null,
    ref_id        text,
    sent_at       timestamptz,
    acknowledged  boolean not null default false,
    created_at    timestamptz not null default now()
);

create table if not exists agent_runs (
    id              uuid primary key default gen_random_uuid(),
    agent           text not null,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    status          text not null default 'running',  -- running | ok | error
    error           text,
    output_summary  text
);

-- Every human decision required by the approval matrix (CLAUDE.md section 6)
create table if not exists approvals (
    id            uuid primary key default gen_random_uuid(),
    item_type     text not null,       -- creative | publish | pause | budget
    item_id       text not null,
    requested_at  timestamptz not null default now(),
    decided_at    timestamptz,
    decision      text,                -- approved | rejected
    decided_by    text
);

-- PHASE 2 ONLY — table created so the gate is visible, but nothing writes to it
-- until the Day-90 review passes. Do not build Agent 6 before then.
create table if not exists learnings (
    id               uuid primary key default gen_random_uuid(),
    creative_id      uuid references creatives(id) on delete cascade,
    hypothesis       text,
    result           text,
    why              text,
    next_hypothesis  text,
    created_at       timestamptz not null default now()
);

-- ---------------------------------------------------------------
-- Indexes (CLAUDE.md section 5)
-- ---------------------------------------------------------------

create index if not exists idx_daily_metrics_lookup
    on daily_metrics (date, level, ref_id);
create index if not exists idx_daily_metrics_ref_date
    on daily_metrics (level, ref_id, date desc);
create index if not exists idx_leads_source_stage
    on leads (source_ad_id, stage);
create index if not exists idx_baselines_lookup
    on computed_baselines (date, level, ref_id, metric);
create index if not exists idx_agent_runs_agent_started
    on agent_runs (agent, started_at desc);
create index if not exists idx_alerts_created
    on alerts (created_at desc);
