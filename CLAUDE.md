# ANNEMS AI MARKETING DEPARTMENT — MASTER BUILD INSTRUCTIONS

> **How to use this file (untuk Aiman):**
> Letak fail ini di root project folder dengan nama `CLAUDE.md`.
> Claude Code akan baca fail ini secara automatik setiap sesi.
> Bina ikut urutan MILESTONES di bawah — jangan langkau.
> Setiap milestone ada "starter prompt" — copy-paste terus ke Claude Code.

---

## 1. PROJECT OVERVIEW

**Company:** Annems Leadership Solution Sdn Bhd (annemsleadership.com)
**Product being marketed:** Sesi Diagnosis (lead product) → BSS Program (flagship, 5-month program for founders with RM2M+ revenue)
**Owner:** Ibu Hanim (approves direction). **Operator:** Aiman (runs and maintains this system).

**Objective:** Automate daily marketing operations so that marketing runs itself and humans only approve. Strategy stays with humans. AI does the repetitive work: read data, watch ads, produce creatives, record learnings.

**Scope V1:** Annems only. Single tenant. NOT multi-client, NOT SaaS.

---

## 2. NON-NEGOTIABLE PRINCIPLES

These override everything else. If any instruction elsewhere conflicts with these, these win.

1. **"Bina mata dulu, baru tangan."** Build data collection and analysis BEFORE creative production. Never build the creative factory first.
2. **LLMs never do math.** All metrics (CPL, CTR, CPM, CVR, CPQL, ROAS, baselines, moving averages, deltas) are computed in code (the Metric Engine). LLMs only interpret pre-computed numbers.
3. **Human approval is mandatory** for: publishing ads, pausing ads, budget changes, any message sent to customers. No exceptions, no auto-execute. AI may freely: generate reports, analysis, creative drafts, images, tags, alerts.
4. **Everything documented.** Every module gets a README section: what it does, how to run it, common failures. This system must not live only in Aiman's head.
5. **Simple over clever.** Fewer moving parts. Boring, reliable code. No premature abstraction for "future multi-tenant" — that is Phase 3 at earliest.
6. **Fail loudly.** If a data pull fails or an API breaks, send an alert to Aiman's WhatsApp/Telegram. Silent failure is the worst failure.

---

## 3. TECH STACK (fixed — do not substitute)

| Layer | Tool |
|---|---|
| Backend / agents | Python 3.11+, FastAPI |
| Agent framework | OpenAI Agents SDK (or plain OpenAI API calls if simpler) |
| Database | Supabase (Postgres) |
| Scheduler / plumbing | n8n (self-host) OR simple cron on Railway — pick whichever is simpler to maintain |
| Hosting | Railway |
| Ads data | Meta Marketing API (Insights) |
| CRM data | GoHighLevel (GHL) API |
| Notifications | Telegram Bot API (preferred — simpler than WhatsApp Business API). WhatsApp later if needed. |
| Image generation | OpenAI image API (latest model) |

**Model tiers (cost control):**
- **Cheap/fast model** (e.g. gpt-5.x mini-class): tagging, formatting, alerts, daily summaries, classification
- **Mid model**: analysis, creative briefs, copywriting
- **Top model**: ONLY monthly deep analysis. Not used in daily loops.

**Secrets:** all keys in environment variables (`.env` locally, Railway env vars in production). Never commit keys. Required vars:
```
OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY,
META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, GHL_API_KEY, GHL_LOCATION_ID,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_AIMAN, TELEGRAM_CHAT_ID_IBU
```

---

## 4. THE 7 AGENTS (staff roster)

### PHASE 1 (build now, in this order)

**AGENT 1 — Pengumpul Data (Data Collector)** — *not an LLM, pure code*
- Runs daily 06:00 MYT (plus every 3 hours for monitoring data)
- Pulls from Meta Insights API: campaign / adset / ad level — spend, impressions, clicks, reach, frequency, leads (conversions), video metrics
- Pulls from GHL API: new leads, pipeline stage changes (qualified / appointment / closed)
- Normalizes and writes to Supabase
- On failure: retry 3x with backoff, then Telegram alert

**METRIC ENGINE** — *pure code, part of Agent 1's pipeline*
- Computes and stores daily: CPL, CTR, CPM, CPC, CVR, CPQL, frequency, 7-day moving averages, % change vs 7d baseline
- CPQL = spend ÷ qualified leads (qualified = GHL stage "qualified" or later)

**AGENT 2 — Performance Analyst** — *LLM, mid model*
- Runs daily after data pull
- Input: pre-computed metrics (yesterday, 3d, 7d, 14d, baselines) as structured JSON
- Output: diagnosis in plain Bahasa Malaysia — WHAT happened, WHY (distinguish creative fatigue vs audience saturation vs landing page problem vs tracking issue), WHAT to do today
- Rules: never invent numbers; only reference numbers given in input; if data insufficient, say so

**AGENT 3 — Monitoring / Alert** — *rules in code + cheap LLM for message writing*
- Runs every 3 hours during ad-serving hours
- Alert rules (thresholds configurable in one config file):
  - spend > RM100 today AND leads = 0 → alert
  - CPL > 1.5× 7-day baseline → alert
  - CTR drop > 30% vs baseline → creative fatigue alert
  - Meta or GHL API pull failed → system alert
- Alert format: numbers + short diagnosis + recommendation. NEVER just "performance declined."

**AGENT 4 — Penulis Iklan (Ad Writer)** — *LLM, mid model + image API*
- Triggered manually by Aiman (Telegram command or simple endpoint), or suggested by Agent 2 when fatigue detected
- Input: winning/losing angle data from DB + brand kit + offer (Sesi Diagnosis)
- Output per request: 2–3 complete creative options, each = hook + primary text + headline + CTA + generated image (4:5 Meta format)
- Brand: navy + gold, premium corporate tone, Bahasa Malaysia copy targeting founders RM2M+ revenue
- Every creative is tagged on creation: concept, angle, format, awareness level (this metadata is mandatory — it feeds Phase 2)

**AGENT 5 — Creative QA** — *LLM with vision, cheap/mid model*
- Runs automatically on every generated creative before it reaches Aiman
- Checks: typos, brand compliance (colors/tone), weird AI artifacts, message clarity, mobile readability, obvious ad-policy risk
- Output: score per dimension + PASS/FAIL. FAIL → auto-regenerate once with feedback → if still FAIL, send to Aiman flagged
- Aiman only sees creatives that passed (or flagged fails)

**REPORTER (part of Agent 2's daily run):**
- 07:00 MYT daily Telegram message: spend, leads, CPL, qualified, CPQL, best ad, worst ad, 3-line diagnosis, today's recommended actions
- Weekly (Monday): 7-day summary with trends

### PHASE 2 (build ONLY after Day-90 review passes)

**AGENT 6 — Learning Memory**
- After any experiment/creative concludes (paused or 14+ days run): auto-write a learning record — what was tested, result, why, next hypothesis
- Retrievable by Agent 4 when generating new creatives

**AGENT 7 — CRM Agent**
- Connects ad → lead → qualified → appointment → sale → revenue per ad/angle
- Precondition (hard gate): GHL pipeline discipline verified — every lead consistently staged. If GHL data is messy, DO NOT build this; it will confidently produce wrong answers.

---

## 5. DATABASE SCHEMA (Supabase — Phase 1 tables only)

```sql
-- Core performance data
campaigns(id, meta_campaign_id, name, objective, status, created_at)
adsets(id, meta_adset_id, campaign_id, name, audience_desc, status)
ads(id, meta_ad_id, adset_id, name, status, creative_id)
creatives(id, concept, angle, format, awareness_level, hook, primary_text,
          headline, cta, image_url, qa_score, qa_status, created_by, created_at)
daily_metrics(id, date, level, ref_id,  -- level: campaign|adset|ad
          spend, impressions, clicks, reach, frequency, leads,
          cpl, ctr, cpm, cpc, cvr, created_at)
computed_baselines(id, date, level, ref_id, metric, avg_7d, avg_14d, delta_pct)

-- CRM data
leads(id, ghl_contact_id, source_ad_id, stage, stage_updated_at, created_at)
-- stage: new|qualified|appointment|closed_won|closed_lost

-- System
alerts(id, rule, severity, message, sent_at, acknowledged)
agent_runs(id, agent, started_at, finished_at, status, error, output_summary)
approvals(id, item_type, item_id, requested_at, decided_at, decision, decided_by)
learnings(id, creative_id, hypothesis, result, why, next_hypothesis, created_at)  -- Phase 2
```

Add indexes on `daily_metrics(date, level, ref_id)` and `leads(source_ad_id, stage)`.

---

## 6. APPROVAL MATRIX (enforce in code)

| Action | Approval |
|---|---|
| Generate report / analysis / alert | AUTO |
| Generate creative draft + image | AUTO |
| Tag / classify / store data | AUTO |
| Publish ad to Meta | HUMAN (Aiman) |
| Pause ad | HUMAN (Aiman) |
| Change budget | HUMAN (Aiman) |
| Send any message to a customer/lead | HUMAN — not in scope for V1 at all |

V1 does NOT write to Meta at all (read-only API). Publishing stays manual in Ads Manager. Write-access is a Phase 2 decision.

---

## 7. MILESTONES & STARTER PROMPTS

Build in this exact order. Do not start a milestone until the previous one's "Definition of Done" is met.

### MILESTONE 1 (Bulan 1, minggu 1–2): Foundation
**Definition of Done:** Meta + GHL data lands in Supabase daily, automatically, with failure alerts to Telegram.

Starter prompt for Claude Code:
> "Read CLAUDE.md. Build Milestone 1: a Python project with (a) Supabase schema from section 5, (b) a Meta Insights daily pull for campaign/adset/ad levels, (c) a GHL leads pull, (d) the Metric Engine computing all metrics in section 4, (e) a Telegram alert on any pull failure, (f) deployment config for Railway with a daily 06:00 MYT schedule. Include a README explaining setup and env vars."

### MILESTONE 2 (Bulan 1, minggu 3–4): Morning Report
**Definition of Done:** Ibu and Aiman receive a daily 07:00 Telegram report with real numbers and a short diagnosis, in Bahasa Malaysia.

Starter prompt:
> "Read CLAUDE.md. Build Milestone 2: the daily Reporter. After the 06:00 data pull, compose the 07:00 Telegram report per section 4 (Reporter spec) using the mid-tier model to write the diagnosis from pre-computed metrics only. Add the Monday weekly summary."

### MILESTONE 3 (Bulan 2): Analyst + Monitoring
**Definition of Done:** Alerts fire correctly on threshold breaches (test with simulated data), and daily diagnosis correctly distinguishes creative fatigue vs landing page issues.

Starter prompt:
> "Read CLAUDE.md. Build Milestone 3: (a) full Performance Analyst per Agent 2 spec, (b) Monitoring Agent with the alert rules in Agent 3 spec, running every 3 hours, thresholds in a single config file. Write tests that simulate threshold breaches."

### MILESTONE 4 (Bulan 3): Creative Factory
**Definition of Done:** One Telegram command produces 2–3 QA-passed creative options (copy + image + tags) that Aiman can download and publish manually.

Starter prompt:
> "Read CLAUDE.md. Build Milestone 4: (a) Penulis Iklan per Agent 4 spec, triggered by a Telegram command, (b) Creative QA per Agent 5 spec with the regenerate-once loop, (c) mandatory tagging of every creative (concept/angle/format/awareness) stored in the creatives table."

### MILESTONE 5 (Day-90 review — HUMAN decision, not code)
Criteria: (1) morning report used daily, (2) ≥3 creative decisions changed because of system data, (3) CPQL trend measurable.
All pass → proceed to Phase 2 (Agents 6–7). Any fail → stop and reassess. Kill criteria are real.

---

## 8. CODING STANDARDS

- Python: type hints, one module per agent, config in one `config.py` / `.env`
- Every agent run logged to `agent_runs` table
- Timezone: everything in Asia/Kuala_Lumpur (MYT) for scheduling and reports
- Currency: RM. Reports in Bahasa Malaysia. Code comments in English.
- Small commits, descriptive messages
- Before marking any milestone done: run it end-to-end with real API data at least 3 consecutive days

## 9. WHAT NOT TO BUILD (guard against scope creep)

- No AI CMO / orchestrator agent
- No Marketing Strategist agent (strategy = humans)
- No multi-tenant / client onboarding
- No dashboard/frontend in V1 (Telegram is the interface)
- No auto-publish, auto-pause, or auto-budget
- No CRM messaging automation

If Claude Code suggests any of these, decline and refer to this section.
