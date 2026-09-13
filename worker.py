#!/usr/bin/env python3
"""
Taurus Are Us — Cloud Publish Worker

This is what Render runs as a Cron Job, on a frequent fixed schedule
(every 15 minutes, in render.yaml) — deliberately NOT scheduled at the
exact PST posting times. Render's Cron Jobs are UTC-only with no timezone
option, so a schedule written for "8am PST" would silently drift an hour
off every time Daylight Saving starts or ends. Instead, this runs often
and checks "is it actually time yet?" itself, in Python, against real
Pacific time via zoneinfo — which handles DST automatically, permanently.

Each run:
  1. Syncs in whatever schedule.json currently sits in this repo (updated
     by you exporting from the scheduler artifact, committing, and
     pushing — Render auto-deploys on push, which is what gets a new
     schedule.json onto this service in the first place).
  2. Publishes every row whose Pacific-time slot has already passed today
     (or is dated earlier and got missed) and isn't fully posted to both
     platforms yet.

Per-platform status lives in Postgres, not a local file, and is checked
independently — if Facebook succeeds and Instagram fails on one run,
the next run only retries Instagram, never re-posts to Facebook.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from graph_api import publish_facebook, publish_instagram
from models import ScheduledPost, get_session
from sync_schedule import sync

PACIFIC = ZoneInfo("America/Los_Angeles")


def run():
    sync()

    session = get_session()
    now_pacific = datetime.now(PACIFIC)
    today_str = now_pacific.strftime("%Y-%m-%d")
    now_time_str = now_pacific.strftime("%H:%M")

    candidates = (
        session.query(ScheduledPost)
        .filter(ScheduledPost.date <= today_str)
        .filter(ScheduledPost.status != "posted")
        .all()
    )
    # A slot dated earlier than today is due regardless of its time (it was
    # missed). A slot dated today is only due once its clock time has
    # actually passed in Pacific time right now.
    due = [r for r in candidates if r.date < today_str or r.time <= now_time_str]

    if not due:
        print(f"[{now_pacific.isoformat()}] Nothing due.")
        session.close()
        return

    print(f"[{now_pacific.isoformat()}] {len(due)} slot(s) due.")

    for row in due:
        if not row.url:
            print(f"  ✗ {row.id} — no url set, skipping")
            continue

        row_platforms = (row.platforms or "fb,ig").split(",")
        for platform, already_done, publish_fn in (
            ("fb", row.fb_posted, publish_facebook),
            ("ig", row.ig_posted, publish_instagram),
        ):
            if platform not in row_platforms or already_done:
                continue
            try:
                publish_fn(row)
                if platform == "fb":
                    row.fb_posted = True
                    row.last_fb_error = None
                else:
                    row.ig_posted = True
                    row.last_ig_error = None
                print(f"  ✓ {row.id} · {platform}")
            except Exception as e:
                if platform == "fb":
                    row.last_fb_error = str(e)
                else:
                    row.last_ig_error = str(e)
                print(f"  ✗ {row.id} · {platform} — {e}")

        # Only the platforms this row actually targets need to be done —
        # a Facebook-skipped, Instagram-only row shouldn't wait forever on
        # an fb_posted flag that was never going to be set.
        targets_met = all(
            (row.fb_posted if p == "fb" else row.ig_posted)
            for p in row_platforms
        )
        if targets_met:
            row.status = "posted"
            row.posted_at = datetime.utcnow()

        session.commit()

    session.close()


if __name__ == "__main__":
    run()
