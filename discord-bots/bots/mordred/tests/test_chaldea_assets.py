from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image

from src.chat.features.chaldea.catalog import SERVANTS


PUBLIC_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "chat"
    / "features"
    / "chaldea"
    / "web"
    / "public"
)


class ChaldeaAssetTests(unittest.TestCase):
    def test_every_servant_has_transparent_portrait_and_skill_sheet(self) -> None:
        self.assertEqual(len(SERVANTS), len(set(SERVANTS)))
        for servant in SERVANTS.values():
            for key in ("art_url", "skill_art_url"):
                path = PUBLIC_ROOT / servant[key]
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as image:
                    self.assertIn("A", image.mode, path)
                    self.assertGreater(image.width, 500)
                    self.assertGreater(image.height, 300)

    def test_servants_with_noble_phantasm_quotes_have_cinematic_art(self) -> None:
        cinematic = [servant for servant in SERVANTS.values() if servant["np"].get("quote")]
        self.assertEqual(len(cinematic), len(SERVANTS))
        for servant in cinematic:
            path = PUBLIC_ROOT / servant["np"]["cg_url"]
            self.assertTrue(path.is_file(), path)
            with Image.open(path) as image:
                self.assertGreaterEqual(image.width, 1200)
                self.assertGreaterEqual(image.height, 600)


if __name__ == "__main__":
    unittest.main()
