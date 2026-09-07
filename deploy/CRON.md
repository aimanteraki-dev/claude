# Scheduled jobs (Railway cron)

Railway cron expressions run in **UTC**. Malaysia is **UTC+8**, so every local
time below is shifted back 8 hours — and anything before 08:00 MYT lands on the
*previous* UTC day. The code itself always works in `Asia/Kuala_Lumpur`
(`config.now_myt`), so only these cron strings need the conversion.

Create one Railway **Cron Service** per row, all pointing at this same repo.

| Job | Local time (MYT) | Cron (UTC) | Command |
|---|---|---|---|
| Agent 1 — daily pull | 06:00 daily | `0 22 * * *` | `python -m annems collect` |
| Morning report | 07:00 daily | `0 23 * * *` | `python -m annems report` |
| Weekly summary | Mon 07:15 | `15 23 * * 0` | `python -m annems weekly` |
| Monitoring pull | every 3h | `0 */3 * * *` | `python -m annems monitor-pull` |
| Agent 3 — alerts | every 3h, +5 min | `5 */3 * * *` | `python -m annems monitor` |

Notes:

- **Weekly is `* * 0` (Sunday UTC), not Monday.** Monday 07:15 MYT is Sunday
  23:15 UTC. Setting it to Monday UTC would send the report a day late.
- The monitoring pull runs before the alert job so Agent 3 judges fresh numbers.
  Agent 3 itself skips runs outside `active_hours_start`/`end` in
  `config/thresholds.yaml`, so the `*/3` schedule is safe to leave running all
  night — it will simply no-op.
- `collect` defaults to **yesterday**. Meta's figures for the current day are
  still moving, and a report built on a half-finished day misleads.

## First deploy

```bash
# 1. Create the schema (Supabase SQL editor, or psql)
psql "$DATABASE_URL" -f db/schema.sql

# 2. Set every variable from .env.example in Railway → Variables

# 3. Verify connectivity before scheduling anything
python -m annems healthcheck

# 4. Seed history so baselines are not empty on day one
python -m annems backfill --days 14

# 5. Register the Telegram webhook (replace the domain with your Railway URL)
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://<your-app>.up.railway.app/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## Getting the Telegram chat IDs

1. Create the bot with [@BotFather](https://t.me/BotFather), copy the token.
2. Send the bot a message from Aiman's account, then from Ibu's.
3. `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` — each `message.chat.id`
   is the value for `TELEGRAM_CHAT_ID_AIMAN` / `TELEGRAM_CHAT_ID_IBU`.
