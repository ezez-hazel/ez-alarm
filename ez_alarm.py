#!/usr/bin/env python3
"""Check a Bilibili live room and send a Bark notification when it is live."""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOM_API = "https://api.live.bilibili.com/room/v1/Room/get_info"
USER_API = "https://api.bilibili.com/x/web-interface/card"
DEFAULT_LOCK_FILE = "/run/lock/ez-alarm.lock"
LOCK_TTL_SECONDS = 4 * 60 * 60
POLL_INTERVAL_SECONDS = 300
logger = logging.getLogger(__name__)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def lockfile_path() -> Path:
    state_directory = os.environ.get("STATE_DIRECTORY", "").strip()
    if state_directory:
        return Path(state_directory) / "ez-alarm.lock"
    return Path(DEFAULT_LOCK_FILE)


def set_lock() -> datetime:
    locked_at = datetime.now(timezone.utc)
    path = lockfile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(locked_at.isoformat(), encoding="utf-8")
    return locked_at


def check_lock() -> datetime | None:
    path = lockfile_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return datetime.fromisoformat(value)


def remove_lock() -> None:
    try:
        lockfile_path().unlink()
    except FileNotFoundError:
        pass


def get_json(url: str, query: dict[str, str]) -> dict:
    request_url = f"{url}?{urlencode(query)}"
    request = Request(request_url, headers={"User-Agent": "ez-alarm/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"HTTP request failed: {response.status}")
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Request failed: {request_url}: {error}") from error


def read_room(room_id: str) -> dict | None:
    response = get_json(ROOM_API, {"room_id": room_id})
    room = response.get("data")
    if not room or room.get("live_status") != 1:
        return None

    user_response = get_json(USER_API, {"mid": str(room["uid"])})
    card = user_response.get("data", {}).get("card")
    if not card:
        raise RuntimeError(f"Bilibili user card is missing for uid {room['uid']}")

    return {
        "rid": room_id,
        "uid": room["uid"],
        "live_status": room["live_status"],
        "title": room.get("title", ""),
        "name": card["name"],
        "face": card["face"],
    }


def read_device_keys() -> list[str]:
    account_id = required_env("CLOUDFLARE_ACCOUNT_ID")
    database_id = required_env("BARK_D1_DATABASE_ID")
    api_token = required_env("CLOUDFLARE_API_TOKEN")
    query_url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/d1/database/{database_id}/query"
    )
    payload = {
        "sql": """
            SELECT key
            FROM devices
            WHERE token IS NOT NULL
              AND token != ''
              AND token != 'deleted'
        """,
    }
    request = Request(
        query_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"D1 request failed: {response.status}")
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"D1 request failed: {error}") from error

    if not result.get("success"):
        raise RuntimeError(f"D1 query failed: {result.get('errors', result)}")

    query_results = result.get("result") or []
    rows = query_results[0].get("results", []) if query_results else []
    return [row["key"] for row in rows if row.get("key")]


def send_notification(room: dict, device_keys: list[str]) -> None:
    bark_url = required_env("BARK_URL").rstrip("/")
    payload = {
        "title": room["name"],
        "body": room["title"],
        "sound": "alarm",
        "level": "critical",
        "icon": room["face"],
        "url": f"bilibili://live/{room['rid']}",
        "call": "1",
        "volume": "1",
        "device_keys": device_keys,
    }
    request = Request(
        f"{bark_url}/post",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "ez-alarm/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Notification request failed: {response.status}")
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Notification request failed: {error}") from error


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    try:
        room_id = required_env("ROOM_ID")
        locked_at = check_lock()
        room = read_room(room_id)
        if room is None:
            # 无直播
            if locked_at is not None:
                # 有锁
                remove_lock()
                logger.info("Room %s is no longer live; removed lock", room_id)
            else:
                logger.info("Room %s is not live", room_id)
            return 0

        # 有直播
        if locked_at is not None:
            # 有锁
            lock_age = datetime.now(timezone.utc) - locked_at
            if lock_age.total_seconds() < LOCK_TTL_SECONDS:
                # 没超时
                logger.info("Room %s is locked at %s", room_id, locked_at.isoformat())
                time.sleep(POLL_INTERVAL_SECONDS)
                return 0

            # 超时
            remove_lock()
            logger.info("Lock expired after 4 hours; removed lock")

        device_keys = read_device_keys()
        send_notification(room, device_keys)
        locked_at = set_lock()
        logger.info("Set lock at %s", locked_at.isoformat())
        logger.info("Notification sent for room %s to %d device(s)", room_id, len(device_keys))
        time.sleep(POLL_INTERVAL_SECONDS)
        return 0
    except Exception:
        logger.exception("Failed to process room")
        return 1


if __name__ == "__main__":
    sys.exit(main())