"""
Pulls schedule.json (the file you export from the scheduler artifact and
commit to this repo) into the database.

Upsert, not replace: a slot's posting status (fb_posted, ig_posted,
status, posted_at) is only ever set on first insert, and on first insert
it's taken from whatever the export already says — so a slot marked
"posted" (already sent out via the local script, or manually marked
posted in the artifact) arrives already marked done, and the cloud worker
won't post it again. Every re-sync after that only ever updates the
content fields (title, url, caption) on rows that haven't posted yet;
existing posting status is never touched again once a row exists.
"""

import json
from datetime import datetime
from pathlib import Path

from models import ScheduledPost, get_session

SCHEDULE_PATH = Path(__file__).parent / "schedule.json"


def sync():
    if not SCHEDULE_PATH.exists():
        print(f"No {SCHEDULE_PATH.name} found in the repo yet — nothing to sync.")
        return

    entries = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    session = get_session()

    for entry in entries:
        date = entry.get("date")
        time_ = entry.get("time", "00:00")
        if not date:
            continue
        row_id = f"{date}_{time_}"

        row = session.get(ScheduledPost, row_id)
        if row is None:
            # If this slot already shows "posted" in the export — because it
            # went out earlier via the local publish script, or you manually
            # marked it posted in the artifact — respect that on arrival.
            # Otherwise a slot you already posted locally would look
            # brand-new to the cloud worker and get posted a second time.
            already_posted = entry.get("status") == "posted"
            row = ScheduledPost(
                id=row_id, date=date, time=time_,
                fb_posted=already_posted, ig_posted=already_posted,
                status=entry.get("status", "assigned"),
            )
            if already_posted:
                row.posted_at = datetime.utcnow()
            session.add(row)

        # Content fields always refresh from the latest export. Posting
        # status fields are untouched here on purpose — see module docstring.
        row.time_label = entry.get("timeLabel", "")
        row.title = entry.get("title", "")
        row.media_type = entry.get("mediaType", "")
        row.url = entry.get("url", "")
        row.caption = entry.get("caption", "")
        row.platforms = ",".join(entry.get("platforms", ["fb", "ig"]))

    session.commit()
    count = len(entries)
    session.close()
    print(f"Synced {count} entr{'y' if count == 1 else 'ies'} from {SCHEDULE_PATH.name}.")


if __name__ == "__main__":
    sync()
