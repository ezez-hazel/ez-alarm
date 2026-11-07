#!/usr/bin/env python3
"""Check a Bilibili live room and send a Bark notification when it is live."""

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOM_API = "https://api.live.bilibili.com/room/v1/Room/get_info"
USER_API = "https://api.bilibili.com/x/web-interface/card"
DEFAULT_LOCK_FILE = "/run/lock/ez-alarm.lock"
LOCK_TTL_SECONDS = int(os.environ.get("LOCK_TTL", "14400"))
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
    locked_at = datetime.now(UTC)
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


async def get_json(client: httpx.AsyncClient, url: str, query: dict[str, str]) -> dict:
    try:
        response = await client.get(url, params=query)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        raise RuntimeError(f"Request failed: {url}: {error}") from error


async def read_room(client: httpx.AsyncClient, room_id: str) -> dict | None:
    response = await get_json(client, ROOM_API, {"room_id": room_id})
    room = response.get("data")
    if not room or room.get("live_status") != 1:
        return None

    user_response = await get_json(client, USER_API, {"mid": str(room["uid"])})
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


async def read_device_keys(client: httpx.AsyncClient) -> list[str]:
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
    try:
        response = await client.post(
            query_url,
            json=payload,
            headers={"Authorization": f"Bearer {api_token}"},
        )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPError as error:
        raise RuntimeError(f"D1 request failed: {error}") from error

    if not result.get("success"):
        raise RuntimeError(f"D1 query failed: {result.get('errors', result)}")

    query_results = result.get("result") or []
    rows = query_results[0].get("results", []) if query_results else []
    return [row["key"] for row in rows if row.get("key")]


async def send_notification(
    room: dict, device_keys: list[str], client: httpx.AsyncClient
) -> None:
    bark_url = required_env("BARK_URL").rstrip("/")
    payload = {
        "title": room["name"],
        "body": room["title"],
        "sound": os.environ.get("BARK_SOUND", "alarm"),
        "level": "critical",
        "icon": room["face"],
        "url": f"bilibili://live/{room['rid']}",
        "call": "1",
        "volume": os.environ.get("BARK_VOLUME", "5"),
        "device_keys": device_keys,
    }
    try:
        response = await client.post(f"{bark_url}/post", json=payload)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError(f"Notification request failed: {error}") from error


async def send_notifications(
    room: dict, device_keys_chunks: list[list[str]], client: httpx.AsyncClient
) -> None:
    await asyncio.gather(
        *(
            send_notification(room, device_keys, client)
            for device_keys in device_keys_chunks
        )
    )


async def run() -> int:
    room_id = required_env("ROOM_ID")
    locked_at = check_lock()
    async with httpx.AsyncClient(
        timeout=20, headers={"User-Agent": "ez-alarm/1.0"}
    ) as client:
        room = await read_room(client, room_id)
        if room is None:
            if locked_at is not None:
                remove_lock()
                logger.info("Room %s is no longer live; removed lock", room_id)
            else:
                logger.info("Room %s is not live", room_id)
            return 0

        if locked_at is not None:
            lock_age = datetime.now(UTC) - locked_at
            if lock_age.total_seconds() < LOCK_TTL_SECONDS:
                logger.info("Room %s is locked at %s", room_id, locked_at.isoformat())
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                return 0

            remove_lock()
            logger.info("Lock expired after 4 hours; removed lock")

        max_concurrency = int(os.environ.get("MAX_CONCURRENCY", "50"))
        device_keys = await read_device_keys(client)
        device_keys_chunks = [
            device_keys[i : i + max_concurrency]
            for i in range(0, len(device_keys), max_concurrency)
        ]
        await send_notifications(room, device_keys_chunks, client)

    locked_at = set_lock()
    logger.info("Set lock at %s", locked_at.isoformat())
    logger.info(
        "Notification sent for room %s to %d device(s)", room_id, len(device_keys)
    )

    await asyncio.sleep(POLL_INTERVAL_SECONDS)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    try:
        return asyncio.run(run())
    except Exception:
        logger.exception("Failed to process room")
        return 1


if __name__ == "__main__":
    sys.exit(main())
