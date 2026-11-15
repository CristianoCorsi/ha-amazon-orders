"""Exercise the real order parser against synthetic HTTP responses only."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DemoTests(unittest.TestCase):
    def test_count_empty_history_and_reject_challenge(self):
        from requests import Response

        from amazon_orders_ha.auth import AuthRequired, CookieStore

        script = Path(__file__).resolve().parents[2] / "scripts" / "auth_proxy_demo.py"
        spec = importlib.util.spec_from_file_location("auth_demo_under_test", script)
        assert spec is not None and spec.loader is not None
        demo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(demo)
        calls = []
        html = '<div class="js-yo-container"><span class="num-orders">0 orders</span></div>'

        def synthetic_request(_session, method, url, **kwargs):
            calls.append((method, url))
            response = Response()
            response.status_code = 200
            response.url = url
            response._content = html.encode()
            return response

        with tempfile.TemporaryDirectory() as directory:
            provider = CookieStore(Path(directory))
            provider.import_cookies([{"name": "x-acbit", "value": "synthetic", "domain": ".amazon.it"}])
            with patch("requests.sessions.Session.request", synthetic_request):
                self.assertEqual(demo.count_recent_orders(provider), 0)
                self.assertEqual(len(calls), 1)
                self.assertIn("last30", calls[0][1])
                html = '<form id="challenge">Enable JavaScript</form>'
                with self.assertRaises(AuthRequired):
                    demo.count_recent_orders(provider)
            provider.clear()
