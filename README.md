# Taurus Are Us — Cloud Publish (Render)

This is the always-on version of the local publish pipeline — it runs on
Render, checking every 15 minutes whether anything is due, so nothing
depends on your computer being on. The scheduler artifact (where you
curate the Library and build the Queue) doesn't move — it still lives in
Claude, exactly as before. What moves is the last step: actually firing
the posts.

## One-time setup

### 1. Push this folder to a new GitHub repo
Create a new repo (private is fine), and push everything in this folder to
it — including `render.yaml`, but **not** anything you might later add
like a real `config.json` (there isn't one here; see below for how
credentials work instead).

### 2. Create the Blueprint on Render
In the Render dashboard: **New +** → **Blueprint** → connect the repo you
just created. Render reads `render.yaml` and sets up three things at once:
a free Postgres database, a cron job (`taurus-publish-worker`), and a web
service (`taurus-publish-dashboard`).

### 3. Fill in the environment variables Render asks for
The blueprint marks four values as `sync: false`, meaning Render will
prompt you to type them in rather than storing them in the repo:
- `PAGE_ID` — `100496031903229`
- `IG_USER_ID` — `17841444820305316`
- `PAGE_ACCESS_TOKEN` — the never-expiring Page token you already have
- `DASHBOARD_PASSWORD` — pick anything; this locks the web dashboard,
  since unlike the local one, this one is reachable from the internet

Set all four on **both** the cron job and the dashboard service — the
dashboard needs them too, since its "Run check now" button calls the same
publish code the cron job does.

### 4. Deploy
Render builds and starts both services automatically. The cron job won't
find anything to post yet, since `schedule.json` in this repo starts as an
empty `[]`.

## The ongoing workflow

Every time you rebuild the Queue in the scheduler artifact:

1. **Export schedule** in the artifact, same as always.
2. Save that over `schedule.json` in this repo folder.
3. `git add schedule.json`, `git commit -m "update schedule"`, `git push`.
4. Render auto-deploys on push (same as the Japan IG project). Within 15
   minutes, the worker's next run syncs the new file into the database.

That's the entire day-to-day loop — no SSH, no manual server work.

## Checking on it

Visit your dashboard service's Render-provided URL
(`https://taurus-publish-dashboard.onrender.com`, or whatever Render named
it) — it'll prompt for a username (leave blank) and the
`DASHBOARD_PASSWORD` you set. It shows what's due, what's posted, what's
upcoming, and any per-platform errors, plus a manual "Run check now"
button if you don't want to wait for the next 15-minute cycle.

## Why this looks different from the local version

- **Postgres instead of a local file for status** — Render's Cron Jobs
  have no persistent disk; a local file's changes vanish the moment each
  run's container exits. A database row is what actually survives between
  runs.
- **Checks every 15 minutes instead of running once at each exact time** —
  Render's Cron Jobs only understand UTC, with no timezone setting. A
  fixed UTC time written to mean "8am Pacific" would silently drift by an
  hour every time Daylight Saving starts or ends. Instead, the worker runs
  often and checks real Pacific time itself in Python (via `zoneinfo`),
  which adjusts for DST automatically and never needs touching again.
- **`git push` instead of copying a file into a folder** — this is the
  actual mechanism for getting an updated schedule from the artifact onto
  an always-on server you don't have direct file access to.
