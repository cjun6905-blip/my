#!/usr/bin/env python3
"""Create/reuse the Rain Witch Aesc custom emojis in the configured guild.

Credentials are read from the bot environment and never printed.  Existing
emojis with the same managed names are reused, so the operation is idempotent.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


API_ROOT = "https://discord.com/api/v10"


def api_request(method: str, path: str, token: str, payload: dict | None = None):
    body = None
    headers = {"Authorization": f"Bot {token}", "User-Agent": "AescEmojiSync/1.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    for attempt in range(6):
        request = urllib.request.Request(
            f"{API_ROOT}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429 and attempt < 5:
                try:
                    retry_after = float(json.loads(raw).get("retry_after", 1.0))
                except (ValueError, TypeError, json.JSONDecodeError):
                    retry_after = 1.0
                time.sleep(min(max(retry_after, 0.25), 15.0))
                continue
            raise RuntimeError(f"Discord API {method} {path} failed ({exc.code}): {raw[:300]}") from exc
    raise RuntimeError("Discord API retry limit exceeded")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=Path("/app/assets/aesc/emojis/manifest.json")
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    guild_id = next(
        (item.strip() for item in os.getenv("GUILD_ID", "").split(",") if item.strip()),
        "",
    )
    if not token or not guild_id.isdigit():
        raise SystemExit("DISCORD_TOKEN or numeric GUILD_ID is not configured")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    desired = manifest["emojis"]
    guild = api_request("GET", f"/guilds/{guild_id}", token)
    existing = api_request("GET", f"/guilds/{guild_id}/emojis", token)
    existing_by_name = {item["name"]: item for item in existing}

    print(f"guild_id={guild_id}")
    print(f"guild_name={guild.get('name', '')}")
    print(f"existing_emoji_count={len(existing)}")
    print(f"managed_existing_count={sum(1 for item in desired if item['discord_name'] in existing_by_name)}")
    if args.check:
        return

    result = {}
    for item in desired:
        name = item["discord_name"]
        emoji = existing_by_name.get(name)
        action = "reused"
        if emoji is None:
            image_path = args.manifest.parent / item["discord"]
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            emoji = api_request(
                "POST",
                f"/guilds/{guild_id}/emojis",
                token,
                {"name": name, "image": f"data:image/png;base64,{encoded}"},
            )
            existing_by_name[name] = emoji
            action = "created"
        result[name] = str(emoji["id"])
        print(f"emoji_{action}={name}:{emoji['id']}")

    print("mapping_json=" + json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
