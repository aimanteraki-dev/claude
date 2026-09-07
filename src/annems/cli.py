"""Command-line entrypoints. Every scheduled job on Railway calls one of these.

    python -m annems collect          # 06:00 MYT — Agent 1 daily pull
    python -m annems report           # 07:00 MYT — morning report
    python -m annems weekly           # Monday 07:15 MYT — weekly summary
    python -m annems monitor          # every 3h — Agent 3
    python -m annems creative -n 3    # manual — Agents 4+5
    python -m annems healthcheck
    python -m annems import-tagging-log docs/Creative_Tagging_Log_Annems.xlsx
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

from . import logging_setup


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="annems", description="Annems AI Marketing Department")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="Agent 1: daily Meta + GHL pull (06:00 MYT)")
    c.add_argument("--date", help="YYYY-MM-DD (default: yesterday)")
    c.add_argument("--skip-entities", action="store_true")

    b = sub.add_parser("backfill", help="Agent 1: pull a range of past days")
    b.add_argument("--days", type=int, default=14)

    m = sub.add_parser("monitor-pull", help="Agent 1: light pull of today's ad data")
    m.add_argument("--date", help="YYYY-MM-DD (default: today)")

    r = sub.add_parser("report", help="Morning report (07:00 MYT)")
    r.add_argument("--date", help="YYYY-MM-DD (default: yesterday)")
    r.add_argument("--to", choices=["aiman", "ibu", "both"], default="both")
    r.add_argument("--print-only", action="store_true", help="Print, do not send")

    w = sub.add_parser("weekly", help="Weekly summary (Mondays)")
    w.add_argument("--date", help="YYYY-MM-DD (default: yesterday)")
    w.add_argument("--to", choices=["aiman", "ibu", "both"], default="both")

    mo = sub.add_parser("monitor", help="Agent 3: evaluate alert rules")
    mo.add_argument("--date", help="YYYY-MM-DD (default: today)")
    mo.add_argument("--force", action="store_true", help="Ignore ad-serving hours")

    cr = sub.add_parser("creative", help="Agents 4+5: generate QA'd creative options")
    cr.add_argument("-n", type=int, default=3)
    cr.add_argument("--concept", help="Force a concept from config/brand.yaml")
    cr.add_argument("--no-image", action="store_true", help="Copy only, skip image API")

    it = sub.add_parser("import-tagging-log", help="Load the manual xlsx into `creatives`")
    it.add_argument("path")
    it.add_argument("--dry-run", action="store_true")

    sub.add_parser("healthcheck", help="Check Supabase, Meta, GHL and Telegram")
    sub.add_parser("serve", help="Run the Telegram webhook server")
    return p


def main(argv: list[str] | None = None) -> int:
    logging_setup.setup()
    args = build_parser().parse_args(argv)

    # Imported lazily so `--help` works without a populated .env.
    if args.command == "collect":
        from .pipeline import run_daily

        print(run_daily(_parse_date(args.date), sync_entities_first=not args.skip_entities))

    elif args.command == "backfill":
        from .config import today_myt
        from .pipeline import run_daily

        end = today_myt() - timedelta(days=1)
        for i in range(args.days - 1, -1, -1):
            day = end - timedelta(days=i)
            print(run_daily(day, sync_entities_first=(i == args.days - 1)))

    elif args.command == "monitor-pull":
        from .pipeline import run_monitoring_pull

        print(run_monitoring_pull(_parse_date(args.date)))

    elif args.command == "report":
        from .agents import reporter

        if args.print_only:
            from .agents.analyst import analyse
            from .config import today_myt

            as_of = _parse_date(args.date) or (today_myt() - timedelta(days=1))
            diagnosis, pack = analyse(as_of)
            print(reporter.build_daily_report(as_of, diagnosis, pack))
        else:
            print(reporter.run_daily(_parse_date(args.date), to=args.to))

    elif args.command == "weekly":
        from .agents import reporter

        print(reporter.run_weekly(_parse_date(args.date), to=args.to))

    elif args.command == "monitor":
        from .agents import monitor

        alerts = monitor.run(_parse_date(args.date), force=args.force)
        print(f"{len(alerts)} alert(s) raised")

    elif args.command == "creative":
        from .agents import creative_factory

        creatives = creative_factory.run(
            n=args.n, concept=args.concept, with_image=not args.no_image
        )
        print(f"{len(creatives)} creative(s) produced")

    elif args.command == "import-tagging-log":
        from .tagging_log import import_file

        print(import_file(args.path, dry_run=args.dry_run))

    elif args.command == "healthcheck":
        from .pipeline import healthcheck

        results = healthcheck()
        for k, v in results.items():
            print(f"{k:10s} {v}")
        return 0 if all(v == "ok" for v in results.values()) else 1

    elif args.command == "serve":
        import uvicorn

        uvicorn.run("annems.bot:app", host="0.0.0.0", port=_port())

    return 0


def _port() -> int:
    import os

    return int(os.getenv("PORT", "8000"))


if __name__ == "__main__":
    sys.exit(main())
