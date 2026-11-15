"""Synthetic cookies only; never inspect the user's browser or home jar."""

import http.cookiejar
import unittest


class CookieConversionTests(unittest.TestCase):
    def test_cookiejar_preserves_scope_and_filters_other_sites(self):
        from amazon_orders_ha.auth.cookies import cookiejar_records

        jar = http.cookiejar.CookieJar()
        for domain in (".amazon.it", "www.amazon.it", ".amazon.com", ".amazon.it.evil.test"):
            jar.set_cookie(
                http.cookiejar.Cookie(
                    0,
                    "session-token",
                    "synthetic",
                    None,
                    False,
                    domain,
                    True,
                    domain.startswith("."),
                    "/ap",
                    True,
                    True,
                    2000000000,
                    False,
                    None,
                    None,
                    {},
                    False,
                )
            )
        records = cookiejar_records(jar, "amazon.it")
        self.assertEqual({r["domain"] for r in records}, {".amazon.it", "www.amazon.it"})
        self.assertTrue(all(r["secure"] and r["path"] == "/ap" for r in records))
        self.assertEqual(records[0]["expires"], 2000000000)


if __name__ == "__main__":
    unittest.main()
