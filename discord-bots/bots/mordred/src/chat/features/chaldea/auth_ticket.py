from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time


TICKET_PREFIX = "chaldea"
TICKET_TTL_SECONDS = 4 * 60 * 60
_KEY_CONTEXT = b"odysseia-chaldea-browser-ticket-v1"


class TicketError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise TicketError("Malformed browser ticket") from exc


def _signing_key() -> bytes:
    secret = os.getenv("CHALDEA_SIGNING_SECRET") or os.getenv("DISCORD_CLIENT_SECRET")
    if not secret:
        raise RuntimeError("CHALDEA_SIGNING_SECRET or DISCORD_CLIENT_SECRET is required")
    return hmac.new(secret.encode("utf-8"), _KEY_CONTEXT, hashlib.sha256).digest()


def create_browser_ticket(
    user_id: int | str,
    *,
    scope: str = "player",
    battle_id: str | None = None,
    now: int | None = None,
    ttl_seconds: int = TICKET_TTL_SECONDS,
) -> str:
    if scope not in {"player", "admin", "spectator"}:
        raise ValueError("Unsupported browser ticket scope")
    if scope == "spectator" and not battle_id:
        raise ValueError("Spectator tickets require a battle ID")
    if battle_id and (len(battle_id) > 64 or "." in battle_id):
        raise ValueError("Invalid battle ID")
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + int(ttl_seconds)
    nonce = secrets.token_urlsafe(8)
    payload = f"{int(user_id)}.{issued_at}.{expires_at}.{nonce}.{scope}.{battle_id or '-'}".encode("ascii")
    signature = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    return f"{TICKET_PREFIX}.{_b64encode(payload)}.{_b64encode(signature)}"


def verify_browser_ticket_claims(ticket: str, *, now: int | None = None) -> dict[str, int | str]:
    try:
        prefix, encoded_payload, encoded_signature = ticket.split(".", 2)
    except ValueError as exc:
        raise TicketError("Malformed browser ticket") from exc
    if prefix != TICKET_PREFIX:
        raise TicketError("Unsupported browser ticket")

    payload = _b64decode(encoded_payload)
    signature = _b64decode(encoded_signature)
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise TicketError("Invalid browser ticket signature")

    try:
        parts = payload.decode("ascii").split(".")
        if len(parts) == 4:
            user_id, issued_at, expires_at, _nonce = parts
            scope = "player"
            battle_id = None
        elif len(parts) == 5:
            user_id, issued_at, expires_at, _nonce, scope = parts
            battle_id = None
        elif len(parts) == 6:
            user_id, issued_at, expires_at, _nonce, scope, raw_battle_id = parts
            battle_id = None if raw_battle_id == "-" else raw_battle_id
        else:
            raise ValueError("Invalid ticket fields")
        uid = int(user_id)
        issued = int(issued_at)
        expires = int(expires_at)
    except (UnicodeDecodeError, ValueError) as exc:
        raise TicketError("Malformed browser ticket payload") from exc

    current = int(time.time() if now is None else now)
    if issued > current + 60 or expires <= current:
        raise TicketError("Expired browser ticket")
    if expires - issued > TICKET_TTL_SECONDS or expires <= issued:
        raise TicketError("Invalid browser ticket lifetime")
    if scope not in {"player", "admin", "spectator"}:
        raise TicketError("Invalid browser ticket scope")
    if scope == "spectator" and not battle_id:
        raise TicketError("Spectator ticket is not bound to a battle")
    claims: dict[str, int | str] = {"user_id": uid, "scope": scope}
    if battle_id:
        claims["battle_id"] = battle_id
    return claims


def verify_browser_ticket(ticket: str, *, now: int | None = None) -> int:
    return int(verify_browser_ticket_claims(ticket, now=now)["user_id"])
