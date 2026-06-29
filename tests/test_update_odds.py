import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "update_odds.py"
spec = importlib.util.spec_from_file_location("update_odds", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class OddsTests(unittest.TestCase):
    def test_decimal_to_american(self):
        self.assertEqual(mod.decimal_to_american(2.5), "+150")
        self.assertEqual(mod.decimal_to_american(1.5), "-200")

    def test_devig_sums_to_one(self):
        result = mod.devig({"home": 1.8, "draw": 3.5, "away": 5.0})
        self.assertAlmostEqual(sum(result.values()), 1.0, places=10)

    def test_alias_matching(self):
        matches = [{
            "teams": ["Países Bajos", "Marruecos"],
            "kickoff": "2026-06-29T19:00:00-06:00",
        }]
        event = {
            "home_team": "Netherlands",
            "away_team": "Morocco",
            "commence_time": "2026-06-30T01:00:00Z",
        }
        self.assertIs(mod.match_event(matches, event), matches[0])

    def test_event_summary(self):
        event = {
            "home_team": "Mexico",
            "away_team": "Ecuador",
            "bookmakers": [{
                "key": "pinnacle",
                "title": "Pinnacle",
                "last_update": "2026-06-29T10:00:00Z",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Mexico", "price": 2.10},
                        {"name": "Draw", "price": 3.10},
                        {"name": "Ecuador", "price": 3.80},
                    ],
                }],
            }],
        }
        summary = mod.summarize_event(event)
        self.assertEqual(summary["bookmakerCount"], 1)
        self.assertAlmostEqual(sum(summary["probability"].values()), 100.0, delta=0.2)
        self.assertEqual(summary["odds"][0]["book"], "Pinnacle")


if __name__ == "__main__":
    unittest.main()
