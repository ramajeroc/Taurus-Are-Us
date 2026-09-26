"""
Database model for the cloud publish worker.

Why Postgres instead of a local schedule.json: Render's Cron Jobs have no
persistent disk — each run is a fresh container that disappears afterward.
A database row is what actually survives between runs.
"""

import os

from sqlalchemy import Boolean, Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    # Natural key: one row per date+time slot, since the scheduler artifact
    # only ever allows one assignment per time slot per day. This makes
    # re-syncing the same schedule.json safe to repeat — it's an upsert,
    # never a duplicate insert.
    id = Column(String, primary_key=True)  # "YYYY-MM-DD_HH:MM"

    date = Column(String, nullable=False)
    time = Column(String, nullable=False)       # 24h "HH:MM", Pacific time
    time_label = Column(String)                 # "8:00 AM" — display only

    title = Column(String)
    media_type = Column(String)                 # image | video | reel
    url = Column(Text)
    caption = Column(Text)

    fb_posted = Column(Boolean, default=False, nullable=False)
    ig_posted = Column(Boolean, default=False, nullable=False)
    platforms = Column(String, default="fb,ig", nullable=False)  # comma-separated: which platforms this slot actually targets
    status = Column(String, default="assigned", nullable=False)  # assigned | posted
    posted_at = Column(DateTime, nullable=True)

    last_fb_error = Column(Text, nullable=True)
    last_ig_error = Column(Text, nullable=True)


def _normalized_db_url():
    db_url = os.environ["DATABASE_URL"]
    # Render's Postgres connection strings start with postgres://, which
    # SQLAlchemy's newer versions reject outright — has to be postgresql://.
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    # Force the psycopg2 driver explicitly. Left unqualified, a newer
    # SQLAlchemy release can resolve the plain "postgresql://" scheme to
    # the psycopg (v3) dialect instead of psycopg2 — but requirements.txt
    # only installs psycopg2-binary, so that resolution crashes at import
    # time with "ModuleNotFoundError: No module named 'psycopg'". Naming
    # the driver here removes the ambiguity for good.
    if db_url.startswith("postgresql://") and "+psycopg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return db_url


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(_normalized_db_url())
        Base.metadata.create_all(_engine)
    return _engine


def get_session():
    return sessionmaker(bind=get_engine())()
