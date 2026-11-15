"""Local synthetic upstream, no sockets to Amazon or login attempts."""

import tempfile
import unittest
from pathlib import Path


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_only_contacts_mock_after_human_request_and_clears_form_data(self):
        import httpx
        from aiohttp.test_utils import TestClient, TestServer

        from amazon_orders_ha.auth import ProxyAuthProvider

        calls = []

        def upstream(request):
            calls.append(request)
            return httpx.Response(
                200,
                request=request,
                headers={"Content-Type": "text/html"},
                text='<form action="?stage=password"><input name="password"></form>',
            )

        with tempfile.TemporaryDirectory() as d:
            p = ProxyAuthProvider(Path(d), "http://localhost:8098/", transport=httpx.MockTransport(upstream))
            url = p.start()
            client = TestClient(TestServer(p.create_app()))
            await client.start_server()
            try:
                self.assertEqual(calls, [])
                path = __import__("urllib.parse", fromlist=["urlsplit"]).urlsplit(url).path
                response = await client.get(path, headers={"Host": "localhost:8098", "Sec-Fetch-Mode": "navigate"})
                text = await response.text()
                self.assertIn(path + "ap/signin?stage=password", text)
                self.assertEqual(len(calls), 1)
                response = await client.post(
                    path + "ap/signin",
                    data={"password": "fake-password"},
                    headers={"Host": "localhost:8098", "Origin": "http://localhost:8098", "Sec-Fetch-Mode": "navigate"},
                )
                await response.read()
                self.assertEqual(p.proxy.data, {})
                self.assertEqual(p.proxy.query, {})
                denied = await client.get(path + "__amzn_host__127.0.0.1/private", headers={"Host": "localhost:8098"})
                self.assertEqual(denied.status, 403)
                self.assertEqual(len(calls), 2)
                self.assertNotIn("authorization", calls[0].headers)
                self.assertNotIn("x-ingress-path", calls[0].headers)
                denied = await client.post(
                    path + "ap/signin",
                    data={"password": "fake"},
                    headers={"Host": "localhost:8098", "Origin": "https://evil.test"},
                )
                self.assertEqual(denied.status, 403)
                self.assertEqual(len(calls), 2)
            finally:
                await client.close()
                await p.aclose()

    async def test_capture_saves_synthetic_jar_and_stops_proxy(self):
        from urllib.parse import urlsplit

        import httpx
        from aiohttp.test_utils import TestClient, TestServer

        from amazon_orders_ha.auth import ProxyAuthProvider

        def upstream(request):
            return httpx.Response(
                200,
                request=request,
                headers={
                    "Content-Type": "text/html",
                    "Set-Cookie": "x-acbit=synthetic; Domain=.amazon.it; Path=/; Secure",
                },
                text="ok",
            )

        with tempfile.TemporaryDirectory() as d:
            p = ProxyAuthProvider(Path(d), "http://localhost:8098/", transport=httpx.MockTransport(upstream))
            path = urlsplit(p.start()).path
            client = TestClient(TestServer(p.create_app()))
            await client.start_server()
            try:
                response = await client.get(path, headers={"Host": "localhost:8098", "Sec-Fetch-Mode": "navigate"})
                self.assertIn("captured", await response.text())
                self.assertTrue(p.captured.is_set())
                self.assertTrue(p.cookie_path.exists())
                response = await client.get(path, headers={"Host": "localhost:8098"})
                self.assertEqual(response.status, 410)
            finally:
                await client.close()
                await p.aclose()
