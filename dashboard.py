"""
Taurus Are Us — Cloud Publish Dashboard

A password-protected view into what the worker is doing, plus a manual
"Run now" button — same idea as the local dashboard, but reading from
Postgres instead of a local file, since this runs on Render where the
worker's actual state lives in the database.

Unlike the local dashboard (safe by only listening on 127.0.0.1), this one
is reachable from the public internet the moment it's deployed on Render —
so it's protected with HTTP Basic Auth via the DASHBOARD_PASSWORD
environment variable. It refuses to serve anything at all if that
variable isn't set, rather than silently running unprotected.
"""

import os
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Flask, Response, render_template_string, request

from models import ScheduledPost, get_session
from worker import run as run_worker

app = Flask(__name__)
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
PACIFIC = ZoneInfo("America/Los_Angeles")


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not DASHBOARD_PASSWORD:
            return "DASHBOARD_PASSWORD is not set on this service — refusing to serve an unprotected dashboard.", 500
        auth = request.authorization
        if not auth or auth.password != DASHBOARD_PASSWORD:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Taurus Publish Console"'},
            )
        return f(*args, **kwargs)
    return decorated


PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Taurus Are Us — Cloud Publish Console</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#1D2016; --panel:#262A1C; --line:#3C4029;
    --gold:#C9A130; --gold-dim:#8A7327; --rose:#B8615A; --rose-dim:#7D453F;
    --ink:#EDE6D3; --ink-dim:#A6A186; --ink-faint:#6F6B54;
  }
  *{box-sizing:border-box;}
  body{background:var(--bg); color:var(--ink); font-family:'IBM Plex Sans',sans-serif; margin:0; padding:0;}
  .wrap{max-width:780px; margin:0 auto; padding:32px 20px 60px;}
  h1{font-family:'Fraunces',serif; font-weight:600; font-size:1.7rem; margin:0 0 4px 0;}
  .tagline{color:var(--ink-dim); font-size:0.88rem; margin:0 0 26px 0;}
  .stats{display:flex; gap:22px; margin-bottom:26px; flex-wrap:wrap;}
  .stat{font-family:'IBM Plex Mono',monospace; font-size:0.82rem; color:var(--ink-dim);}
  .stat b{color:var(--gold); font-size:1.1rem; display:block; font-weight:500;}
  .panel{background:var(--panel); border:1px solid var(--line); border-radius:4px; padding:18px 20px; margin-bottom:22px;}
  .panel h2{font-family:'Fraunces',serif; font-size:1.1rem; font-weight:600; margin:0 0 14px 0;}
  .row{display:flex; justify-content:space-between; align-items:baseline; padding:9px 0; border-bottom:1px solid var(--line); gap:12px;}
  .row:last-child{border-bottom:none;}
  .row .title{font-weight:500; font-size:0.9rem;}
  .row .meta{font-family:'IBM Plex Mono',monospace; font-size:0.72rem; color:var(--ink-faint); white-space:nowrap;}
  .pill{font-family:'IBM Plex Mono',monospace; font-size:0.68rem; padding:2px 8px; border-radius:10px; border:1px solid var(--line); color:var(--ink-dim);}
  .pill.fb{border-color:var(--gold-dim); color:var(--gold);}
  .pill.ig{border-color:var(--rose-dim); color:var(--rose);}
  .pill.err{border-color:var(--rose-dim); color:var(--rose);}
  .empty{color:var(--ink-faint); font-size:0.85rem; font-style:italic; padding:6px 0;}
  button.btn{
    font-family:'IBM Plex Sans',sans-serif; font-weight:500; font-size:0.92rem;
    background:var(--gold); color:#1D2016; border:none; padding:12px 22px;
    border-radius:3px; cursor:pointer; width:100%;
  }
  button.btn:hover{opacity:0.9;}
  .footnote{color:var(--ink-faint); font-size:0.74rem; margin-top:24px; font-family:'IBM Plex Mono',monospace;}
</style>
</head>
<body>
<div class="wrap">
  <h1>Taurus Are Us — Cloud Publish Console</h1>
  <p class="tagline">Running on Render · checks every 15 minutes against Pacific time</p>

  <div class="stats">
    <div class="stat"><b>{{ due|length }}</b>due now</div>
    <div class="stat"><b>{{ posted_count }}</b>posted total</div>
    <div class="stat"><b>{{ upcoming|length }}</b>upcoming</div>
  </div>

  <div class="panel">
    <h2>Due now</h2>
    {% for r in due %}
      <div class="row">
        <div>
          {% if 'fb' in (r.platforms or 'fb,ig').split(',') %}<span class="pill fb">FB{{ ' ✓' if r.fb_posted else '' }}</span>{% endif %}
          {% if 'ig' in (r.platforms or 'fb,ig').split(',') %}<span class="pill ig">IG{{ ' ✓' if r.ig_posted else '' }}</span>{% endif %}
          <span class="title">{{ r.title or 'Untitled' }}</span>
          {% if r.last_fb_error or r.last_ig_error %}<span class="pill err">error</span>{% endif %}
        </div>
        <span class="meta">{{ r.date }} {{ r.time_label or r.time }} · {{ r.media_type }}</span>
      </div>
      {% if r.last_fb_error %}<div class="empty">FB: {{ r.last_fb_error }}</div>{% endif %}
      {% if r.last_ig_error %}<div class="empty">IG: {{ r.last_ig_error }}</div>{% endif %}
    {% else %}
      <div class="empty">Nothing due right now.</div>
    {% endfor %}
    <form method="POST" action="/run" style="margin-top:16px;">
      <button class="btn" type="submit">Run check now</button>
    </form>
  </div>

  <div class="panel">
    <h2>Upcoming</h2>
    {% for r in upcoming %}
      <div class="row">
        <div>
          {% if 'fb' in (r.platforms or 'fb,ig').split(',') %}<span class="pill fb">FB</span>{% endif %}{% if 'ig' in (r.platforms or 'fb,ig').split(',') %}<span class="pill ig">IG</span>{% endif %}
          <span class="title">{{ r.title or 'Untitled' }}</span>
        </div>
        <span class="meta">{{ r.date }} {{ r.time_label or r.time }} · {{ r.media_type }}</span>
      </div>
    {% else %}
      <div class="empty">Nothing queued past today.</div>
    {% endfor %}
  </div>

  <p class="footnote">schedule.json syncs from this repo on every deploy · status lives in Postgres</p>
</div>
</body>
</html>
"""


def _rows():
    session = get_session()
    all_rows = session.query(ScheduledPost).order_by(ScheduledPost.date, ScheduledPost.time).all()
    session.close()

    now_pacific = datetime.now(PACIFIC)
    today_str = now_pacific.strftime("%Y-%m-%d")
    now_time_str = now_pacific.strftime("%H:%M")

    pending = [r for r in all_rows if r.status != "posted"]
    due = [r for r in pending if r.date < today_str or (r.date == today_str and r.time <= now_time_str)]
    upcoming = [r for r in pending if r not in due]
    posted_count = sum(1 for r in all_rows if r.status == "posted")
    return due, upcoming, posted_count


@app.route("/", methods=["GET"])
@requires_auth
def index():
    due, upcoming, posted_count = _rows()
    return render_template_string(PAGE, due=due, upcoming=upcoming, posted_count=posted_count)


@app.route("/run", methods=["POST"])
@requires_auth
def run_now():
    run_worker()
    due, upcoming, posted_count = _rows()
    return render_template_string(PAGE, due=due, upcoming=upcoming, posted_count=posted_count)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5050)))
