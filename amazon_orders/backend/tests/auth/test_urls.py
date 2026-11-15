"""URL/path security and Ingress prefix fixtures."""

import unittest


class URLTests(unittest.TestCase):
    def test_query_only_action_preserves_page_and_ingress_prefix(self):
        from amazon_orders_ha.auth.urls import rewrite_url

        self.assertEqual(
            rewrite_url(
                "?stage=password&x=1",
                "https://www.amazon.it/ax/claim?old=1",
                "http://localhost:8098/api/hassio_ingress/fake/auth/proxy/token/",
            ),
            "http://localhost:8098/api/hassio_ingress/fake/auth/proxy/token/ax/claim?stage=password&x=1",
        )

    def test_external_and_credential_urls_are_rejected(self):
        from amazon_orders_ha.auth.urls import rewrite_url

        for target in (
            "https://amazon.it.evil.test/ap/signin",
            "https://x@www.amazon.it/ap/signin",
            "http://www.amazon.it/ap/signin",
            "//evil.test/path",
            "javascript:alert(1)",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                rewrite_url(target, "https://www.amazon.it/ap/signin", "http://localhost:8098/proxy/")

    def test_proxy_prefix_cannot_be_removed_or_encoded(self):
        from amazon_orders_ha.auth.urls import upstream_url

        base = "http://localhost:8098/ingress/prefix/proxy/token/"
        self.assertEqual(
            upstream_url("/ingress/prefix/proxy/token/ap/signin?a=1", base, "amazon.it"),
            "https://www.amazon.it/ap/signin?a=1",
        )
        for path in (
            "/ap/signin",
            "/ingress/prefix/proxy/token/../api/status",
            "/ingress/prefix/proxy/token/%2e%2e/api",
            "/ingress/prefix/proxy/token/__amzn_host__127.0.0.1/a",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                upstream_url(path, base, "amazon.it")


class HostTests(unittest.TestCase):
    def test_split_host_strips_port_and_validates(self):
        from amazon_orders_ha.auth.urls import is_lan_host, split_host

        self.assertEqual(split_host("HA.local:8123"), ("ha.local", 8123))
        self.assertEqual(split_host("[fd00::1]:8123"), ("fd00::1", 8123))
        self.assertEqual(split_host("a.lan, b.example.org"), ("a.lan", None))
        for bad in ("", "a b", "a/b", "u@h", "h?x", "h:99999999", "-bad-.lan"):
            with self.subTest(bad), self.assertRaises(ValueError):
                split_host(bad)
        for lan in ("localhost", "ha.local", "192.168.0.4", "10.1.2.3", "127.0.0.1", "fd00::1", "nas", "x.home.arpa"):
            self.assertTrue(is_lan_host(lan), lan)
        for wan in ("example.com", "8.8.8.8", "2606:4700::1"):
            self.assertFalse(is_lan_host(wan), wan)

