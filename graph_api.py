"""
Facebook/Instagram publish calls — same Graph API logic as the local
taurus_publish.py, adapted to read credentials from environment variables
(set in the Render dashboard) instead of a local config.json, since a
config.json containing a live access token has no business being committed
to a git repo, even a private one.
"""

import os
import time

import requests

API_VERSION = "v26.0"
GRAPH_URL = f"https://graph.facebook.com/{API_VERSION}"

PAGE_ID = os.environ["PAGE_ID"]
IG_USER_ID = os.environ["IG_USER_ID"]
PAGE_ACCESS_TOKEN = os.environ["PAGE_ACCESS_TOKEN"]

CONTAINER_TIMEOUT_SECONDS = 180
CONTAINER_POLL_SECONDS = 5


def publish_facebook(row):
    if row.media_type == "image":
        endpoint = f"{GRAPH_URL}/{PAGE_ID}/photos"
        payload = {"url": row.url, "caption": row.caption or "", "access_token": PAGE_ACCESS_TOKEN}
    else:  # video or reel -> posted as a Page video
        endpoint = f"{GRAPH_URL}/{PAGE_ID}/videos"
        payload = {"file_url": row.url, "description": row.caption or "", "access_token": PAGE_ACCESS_TOKEN}

    resp = requests.post(endpoint, data=payload, timeout=60)
    data = resp.json()
    if resp.status_code != 200 or "error" in data:
        raise RuntimeError(f"Facebook publish failed: {data}")
    return data


def create_ig_container(row):
    payload = {"caption": row.caption or "", "access_token": PAGE_ACCESS_TOKEN}
    if row.media_type == "image":
        payload["image_url"] = row.url
    elif row.media_type == "reel":
        payload["media_type"] = "REELS"
        payload["video_url"] = row.url
        payload["share_to_feed"] = "true"
    else:  # video
        payload["media_type"] = "VIDEO"
        payload["video_url"] = row.url

    resp = requests.post(f"{GRAPH_URL}/{IG_USER_ID}/media", data=payload, timeout=60)
    data = resp.json()
    if resp.status_code != 200 or "error" in data:
        raise RuntimeError(f"Instagram container creation failed: {data}")
    return data["id"]


def wait_for_container(container_id):
    waited = 0
    while waited < CONTAINER_TIMEOUT_SECONDS:
        resp = requests.get(
            f"{GRAPH_URL}/{container_id}",
            params={"fields": "status_code", "access_token": PAGE_ACCESS_TOKEN},
            timeout=30,
        )
        data = resp.json()
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Instagram container processing failed: {data}")
        time.sleep(CONTAINER_POLL_SECONDS)
        waited += CONTAINER_POLL_SECONDS
    raise TimeoutError(f"Container {container_id} did not finish processing within {CONTAINER_TIMEOUT_SECONDS}s")


def publish_instagram(row):
    container_id = create_ig_container(row)
    if row.media_type in ("video", "reel"):
        wait_for_container(container_id)
    resp = requests.post(
        f"{GRAPH_URL}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": PAGE_ACCESS_TOKEN},
        timeout=60,
    )
    data = resp.json()
    if resp.status_code != 200 or "error" in data:
        raise RuntimeError(f"Instagram publish failed: {data}")
    return data
