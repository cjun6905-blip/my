from __future__ import annotations

import unittest
from unittest.mock import patch

from src.chat.features.chaldea.auth_ticket import (
    TicketError,
    create_browser_ticket,
    verify_browser_ticket,
    verify_browser_ticket_claims,
)


class BrowserTicketTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with patch.dict("os.environ", {"CHALDEA_SIGNING_SECRET": 'YOUR_CHALDEA_SIGNING_SECRET'}):
            ticket = create_browser_ticket(123456, now=1_000, ttl_seconds=600)
            self.assertEqual(verify_browser_ticket(ticket, now=1_001), 123456)

    def test_admin_scope_is_signed_and_returned(self) -> None:
        with patch.dict("os.environ", {"CHALDEA_SIGNING_SECRET": 'YOUR_CHALDEA_SIGNING_SECRET'}):
            ticket = create_browser_ticket(123456, scope="admin", now=1_000, ttl_seconds=600)
            self.assertEqual(
                verify_browser_ticket_claims(ticket, now=1_001),
                {"user_id": 123456, "scope": "admin"},
            )

    def test_rejects_expired_token(self) -> None:
        with patch.dict("os.environ", {"CHALDEA_SIGNING_SECRET": 'YOUR_CHALDEA_SIGNING_SECRET'}):
            ticket = create_browser_ticket(123456, now=1_000, ttl_seconds=60)
            with self.assertRaises(TicketError):
                verify_browser_ticket(ticket, now=1_060)

    def test_rejects_tampering(self) -> None:
        with patch.dict("os.environ", {"CHALDEA_SIGNING_SECRET": 'YOUR_CHALDEA_SIGNING_SECRET'}):
            ticket = create_browser_ticket(123456, now=1_000, ttl_seconds=600)
            prefix, payload, signature = ticket.split(".", 2)
            replacement = "A" if payload[0] != "A" else "B"
            ticket = f"{prefix}.{replacement}{payload[1:]}.{signature}"
            with self.assertRaises(TicketError):
                verify_browser_ticket(ticket, now=1_001)

    def test_rejects_wrong_secret(self) -> None:
        with patch.dict("os.environ", {"CHALDEA_SIGNING_SECRET": 'YOUR_CHALDEA_SIGNING_SECRET'}):
            ticket = create_browser_ticket(123456, now=1_000, ttl_seconds=600)
        with patch.dict("os.environ", {"CHALDEA_SIGNING_SECRET": 'YOUR_CHALDEA_SIGNING_SECRET'}):
            with self.assertRaises(TicketError):
                verify_browser_ticket(ticket, now=1_001)


if __name__ == "__main__":
    unittest.main()
