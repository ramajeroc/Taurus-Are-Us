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

Each due row is locked (SELECT ... FOR UPDATE SKIP LOCKED) for the brief
moment it's actually being published, so if two runs ever overlap — a
manual "Trigger Run" landing close to a real scheduled tick, say — the
second one backs off that row instead of racing the first and posting a
duplicate.

Facebook posting can be paused entirely via the DISABLE_FACEBOOK
environment variable, independent of what any individual row's platforms
field says — see the constant below.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

from graph_api import publish_facebook, publish_instagram
from models import ScheduledPost, get_session
from sync_schedule import sync

PACIFIC = ZoneInfo("America/Los_Angeles")

# Global kill switch — set DISABLE_FACEBOOK=true in Render's Environment tab
# (on both the worker and dashboard services) to stop all Facebook posting
# immediately, regardless of what any individual row's platforms field
# says. Instagram is unaffected. Flip it back to unset/false to resume —
# no code change needed either way, just the environment variable.
DISABLE_FACEBOOK = os.environ.get("DISABLE_FACEBOOK", "").lower() in ("true", "1", "yes")


def run():
    sync()

    session = get_session()
    now_pacific = datetime.now(PACIFIC)
    today_str = now_pacific.strftime("%Y-%m-%d")
    now_time_str = now_pacific.strftime("%H:%M")

    # First pass: figure out which row IDs are due. No lock needed just to
    # look — we only need the lock at the moment we're about to act on one.
    candidates = (
        session.query(ScheduledPost.id, ScheduledPost.date, ScheduledPost.time)
        .filter(ScheduledPost.date <= today_str)
        .filter(ScheduledPost.status != "posted")
        .all()
    )
    due_ids = [c.id for c in candidates if c.date < today_str or c.time <= now_time_str]

    if not due_ids:
        print(f"[{now_pacific.isoformat()}] Nothing due.")
        session.close()
        return

    print(f"[{now_pacific.isoformat()}] {len(due_ids)} slot(s) due.")
    if DISABLE_FACEBOOK:
        print("  (DISABLE_FACEBOOK is on — skipping Facebook for every row this run)")

    for row_id in due_ids:
        # Lock this one row for the duration of processing it, and only
        # this one — skip_locked means if a concurrent run (an overlapping
        # manual trigger, say) already grabbed this exact row, we back off
        # instead of racing it and posting a duplicate. Each row gets its
        # own short-lived lock, released the moment we commit, so this
        # never blocks a run from moving on to the next due row.
        row = (
            session.query(ScheduledPost)
            .filter(ScheduledPost.id == row_id)
            .with_for_update(skip_locked=True)
            .one_or_none()
        )
        if row is None or row.status == "posted":
            # Either another run already claimed and finished this one,
            # or it's currently locked by a run that's mid-publish right
            # now. Either way, not ours to touch this pass.
            session.rollback()
            continue

        if not row.url:
            print(f"  ✗ {row.id} — no url set, skipping")
            session.rollback()
            continue

        row_platforms = (row.platforms or "fb,ig").split(",")
        for platform, already_done, publish_fn in (
            ("fb", row.fb_posted, publish_facebook),
            ("ig", row.ig_posted, publish_instagram),
        ):
            if platform not in row_platforms or already_done:
                continue
            if platform == "fb" and DISABLE_FACEBOOK:
                print(f"  ⏸ {row.id} · fb — skipped (DISABLE_FACEBOOK is on)")
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
            row.posted_at = datetime.now(timezone.utc)

        session.commit()  # releases this row's lock immediately

    session.close()


if __name__ == "__main__":
    run()
