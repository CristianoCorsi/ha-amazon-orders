"""Device protocol payloads only, never Amazon HTTP."""

import unittest
from urllib.parse import parse_qs, urlsplit


class DeviceTests(unittest.TestCase):
    def test_pkce_url_and_registration_have_same_device_and_verifier(self):
        from amazon_orders_ha.auth.device import DeviceFlow

        f = DeviceFlow()
        query = parse_qs(urlsplit(f.signin_url).query)
        self.assertEqual(query["openid.oa2.scope"], ["device_auth_access"])
        self.assertEqual(query["openid.oa2.code_challenge_method"], ["S256"])
        body = f.registration_body("synthetic-code")
        self.assertEqual(body["auth_data"]["client_id"], f.client_id)
        self.assertEqual(body["auth_data"]["code_verifier"], f.verifier)
        self.assertIn("bearer", body["requested_token_type"])
        self.assertNotIn("password", str(body))

    def test_exchange_keeps_only_italian_cookie_domains(self):
        from amazon_orders_ha.auth.device import exchange_cookie_records

        result = exchange_cookie_records(
            {
                "response": {
                    "tokens": {
                        "cookies": {
                            ".amazon.it": [
                                {
                                    "Name": "session-token",
                                    "Value": '"synthetic"',
                                    "Path": "/",
                                    "Secure": True,
                                    "Expires": "Tue, 01 Jan 2030 00:00:00 GMT",
                                }
                            ],
                            ".amazon.com": [{"Name": "session-token", "Value": "other"}],
                        }
                    }
                }
            }
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["value"], "synthetic")
        self.assertIsInstance(result[0]["expires"], int)
        self.assertEqual(result[0]["domain"], ".amazon.it")
