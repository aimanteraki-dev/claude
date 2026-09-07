"""The Creative Factory — Agent 4 + Agent 5 wired together (Milestone 4).

Flow, per CLAUDE.md Agent 5 spec:
    generate -> render image -> QA -> (FAIL: revise once, re-render, re-QA)
             -> PASS reaches Aiman, second FAIL reaches Aiman flagged
             -> store in `creatives` with mandatory tags
             -> open an approval record (publishing stays manual in Ads Manager)

Nothing here writes to Meta. Ever.
"""

from __future__ import annotations

import logging
from datetime import date

from .. import db, notify
from ..config import today_myt
from . import ad_writer, creative_qa
from .ad_writer import Creative

log = logging.getLogger(__name__)


def process_one(creative: Creative, with_image: bool = True) -> Creative:
    """Run the QA loop for a single creative. Returns the version to deliver."""
    image = None
    if with_image:
        try:
            image = ad_writer.render_image(creative)
        except Exception as exc:
            log.exception("Image generation failed")
            creative.qa_notes = f"Gambar gagal dijana: {exc}"

    result = creative_qa.review(creative, image)

    if result.status == "FAIL":
        log.info("QA FAIL (%s) — one revision attempt", ", ".join(result.failing))
        try:
            revised = ad_writer.revise(creative, result.feedback_for_regeneration())
            revised_image = None
            if with_image:
                try:
                    revised_image = ad_writer.render_image(revised)
                except Exception:
                    log.exception("Image regeneration failed; keeping first image")
                    revised_image = image

            second = creative_qa.review(revised, revised_image)
            if second.status == "PASS":
                creative, image, result = revised, revised_image, second
            else:
                # Still failing. Deliver the revised version, clearly flagged —
                # Aiman decides, nothing is thrown away.
                second.status = "FLAGGED"
                creative, image, result = revised, revised_image, second
        except Exception as exc:
            log.exception("Revision pass failed")
            result.status = "FLAGGED"
            result.summary = f"{result.summary} (percubaan pembetulan gagal: {exc})".strip()

    creative.image_bytes = image
    creative.qa_score = result.average
    creative.qa_status = result.status
    creative.qa_notes = result.to_telegram()
    return creative


def deliver(creative: Creative, index: int, total: int) -> None:
    """Send one finished option to Aiman and open its approval record."""
    creative_id = None
    try:
        creative_id = db.insert_creative(creative.to_db())
    except Exception:
        log.exception("Could not store creative in DB — still delivering to Aiman")

    header = f"*PILIHAN {index}/{total}*\n\n"
    body = header + creative.to_telegram() + "\n\n" + creative.qa_notes

    if creative.image_bytes:
        notify.send_photo(creative.image_bytes, caption=f"Pilihan {index}/{total}")
    notify.send(body, to=notify.Recipient.AIMAN)

    if creative_id:
        try:
            db.request_approval("creative", creative_id)
        except Exception:
            log.exception("Could not open approval record for creative %s", creative_id)


def run(n: int = 3, concept: str | None = None, as_of: date | None = None,
        with_image: bool = True) -> list[Creative]:
    """Produce n QA'd creative options and send them to Aiman."""
    as_of = as_of or today_myt()
    with db.agent_run("agent_4_5_creative_factory") as run_rec:
        notify.send(
            f"🎨 Menjana {n} pilihan creative"
            + (f" untuk concept *{concept}*" if concept else "")
            + "… (1-2 minit)",
            to=notify.Recipient.AIMAN,
        )

        drafts = ad_writer.generate(as_of, n=n, concept=concept)
        finished: list[Creative] = []
        for i, draft in enumerate(drafts, start=1):
            finished.append(process_one(draft, with_image=with_image))

        passed = [c for c in finished if c.qa_status == "PASS"]
        flagged = [c for c in finished if c.qa_status != "PASS"]

        for i, c in enumerate(passed + flagged, start=1):
            deliver(c, i, len(finished))

        notify.send(
            f"Siap: {len(passed)} lulus QA, {len(flagged)} bertanda.\n"
            "Publish manual dalam Ads Manager — sistem ini tak sentuh Meta.",
            to=notify.Recipient.AIMAN,
        )
        run_rec["summary"] = f"{len(passed)} pass, {len(flagged)} flagged"
    return finished
