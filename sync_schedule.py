"""
Pulls schedule.json (the file you export from the scheduler artifact and
commit to this repo) into the database.

Upsert, not replace: a slot's posting status (fb_posted, ig_posted,
status, posted_at) is only ever set on first insert. Re-running this after
re-exporting an updated schedule.json — which happens on every deploy,
automatically — never resets or duplicates something that's already gone
out; it only ever updates the content fields (title, url, caption) on
rows that haven't posted yet.
"""

import json
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
            row = ScheduledPost(
                id=row_id, date=date, time=time_,
                fb_posted=False, ig_posted=False, status="assigned",
            )
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
