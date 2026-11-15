"""Offline contract tests for auth providers; no user configuration is read."""

import json
import tempfile
import unittest
from pathlib import Path


class ProviderTests(unittest.TestCase):
    def test_missing_session_raises_and_start_retains_ingress_prefix(self):
        from amazon_orders_ha.auth import AuthRequired, ProxyAuthProvider

        with tempfile.TemporaryDirectory() as d:
            p = ProxyAuthProvider(Path(d), "http://localhost:8098/ingress/fake/")
            self.assertEqual(p.status()["state"], "auth_required")
            with self.assertRaises(AuthRequired):
                p.get_session()
            self.assertIn("/ingress/fake/auth/proxy/", p.start())
            self.assertEqual(p.status()["state"], "in_progress")
            p.logout()
            self.assertEqual(p.status()["state"], "auth_required")

    def test_import_uses_isolated_jar_and_does_not_claim_verified(self):
        from amazon_orders_ha.auth import AuthRequired, CookieAuthProvider

        with tempfile.TemporaryDirectory() as d:
            p = CookieAuthProvider(Path(d))
            p.import_cookies(
                [
                    {
                        "name": "session-token",
                        "value": "synthetic",
                        "domain": ".amazon.it",
                        "path": "/",
                        "secure": True,
                        "expires": None,
                    }
                ]
            )
            self.assertEqual(p.status()["state"], "auth_required")
            with self.assertRaises(AuthRequired):
                p.get_session()
            records = json.loads(p.cookie_path.read_text())
            self.assertEqual(records[0]["value"], "synthetic")
            self.assertEqual(p.cookie_path.stat().st_mode & 0o777, 0o600)
            p.logout()
            self.assertFalse(p.cookie_path.exists())

    def test_environment_cannot_redirect_cookie_jar(self):
        import os
        from unittest.mock import patch

        from amazon_orders_ha.auth import CookieAuthProvider

        with tempfile.TemporaryDirectory() as d:
            with patch.dict(
                os.environ, {"AMAZON_COOKIE_JAR_PATH": "/forbidden-cookie.json", "AMAZON_DOMAIN": "amazon.com"}
            ):
                p = CookieAuthProvider(Path(d))
                session = p.new_session()
                self.assertEqual(session.config.cookie_jar_path, str(p.cookie_path))
                self.assertEqual(session.config.site, "amazon.it")
                session.session.close()
