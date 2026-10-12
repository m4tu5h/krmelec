import unittest
from datetime import date
from unittest.mock import patch

from menu_agent import Dish, Menu, public_url, validate_menu


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.target = date(2026, 10, 12)
        self.records = [{"url": "https://example.com/menu", "resolved_url": "https://example.com/menu"}]
        self.menu = Menu(status="ok", menu_date=self.target, date_evidence="12.10.2026",
            dishes=[Dish(name="Testovací obed", category="main", price_eur=8.5,
                         soup_included=None, source_url="https://example.com/menu", evidence="Testovací obed 8,50 €")], notes=[])

    def test_dated_menu(self):
        self.assertEqual(validate_menu(self.menu, self.target, self.records).status, "ok")

    def test_stale_menu_never_has_publishable_dishes(self):
        self.menu.menu_date = date(2026, 10, 11)
        result = validate_menu(self.menu, self.target, self.records)
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.dishes, [])

    def test_undated_menu_needs_review(self):
        self.menu.menu_date = None
        self.assertEqual(validate_menu(self.menu, self.target, self.records).status, "needs_review")

    def test_missing_price_stays_unknown(self):
        self.menu.dishes[0].price_eur = None
        result = validate_menu(self.menu, self.target, self.records)
        self.assertEqual(result.status, "needs_review")
        self.assertIsNone(result.dishes[0].price_eur)

    def test_unfetched_citation_needs_review(self):
        self.menu.dishes[0].source_url = "https://invented.example/menu"
        self.assertEqual(validate_menu(self.menu, self.target, self.records).status, "needs_review")

    def test_empty_menu_unavailable(self):
        self.menu.dishes = []
        self.assertEqual(validate_menu(self.menu, self.target, self.records).status, "unavailable")

    def test_private_urls_rejected(self):
        with patch("menu_agent.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError):
                public_url("https://localhost/menu")


if __name__ == "__main__":
    unittest.main()
