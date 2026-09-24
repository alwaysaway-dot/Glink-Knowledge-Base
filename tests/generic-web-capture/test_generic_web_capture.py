#!/usr/bin/env python3
"""Deterministic AU-A1 contract, adapter, routing and temporary E2E tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "capture-provider-router"))

from generic_web_capture import COMPLETION, capture  # noqa: E402
from providers.generic_web_contract import FailureClass, GenericWebCaptureRequest  # noqa: E402
from providers.scrapling_static_adapter import fetch_static, provider_version  # noqa: E402
from providers.web_content_extract import extract  # noqa: E402


ARTICLE = """<!doctype html><html><head><title>测试文章</title>
<meta name="author" content="明确作者"><meta property="article:published_time" content="2026-09-17">
</head><body><nav>导航噪音</nav><article><h1>测试文章</h1><p>这是第一段忠实事实内容，用于验证静态网页采集。</p><p>这是第二段，保留限定条件，不做摘要或改写。</p></article><footer>页脚噪音</footer></body></html>"""
ENGLISH = """<html><head><title>English Article</title></head><body><main><h1>English Article</h1><p>This is faithful public source text for deterministic capture.</p><p>No summary or semantic rewriting is performed.</p></main></body></html>"""


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        return

    def send(self, status: int, body: bytes, content_type: str = "text/html; charset=utf-8", headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        routes = {
            "/article": (200, ARTICLE.encode(), "text/html; charset=utf-8"),
            "/english": (200, ENGLISH.encode(), "text/html; charset=utf-8"),
            "/404": (404, b"not found", "text/html"),
            "/429": (429, b"slow down", "text/html"),
            "/500": (500, b"server error", "text/html"),
            "/empty": (200, b"", "text/html"),
            "/js": (200, b'<html><body><div id="root"></div><script src="app.js"></script></body></html>', "text/html"),
            "/login": (200, '<html><body><form>登录 用户名 password</form></body></html>'.encode(), "text/html"),
            "/challenge": (200, b'<html><body>Cloudflare verify you are human captcha</body></html>', "text/html"),
            "/pdf": (200, b"%PDF-1.7", "application/pdf"),
            "/image": (200, b"PNG", "image/png"),
            "/audio": (200, b"audio", "audio/mpeg"),
            "/video": (200, b"video", "video/mp4"),
            "/no-title": (200, '<html><body><article><p>没有标题但正文足够完整，不应阻断事实采集流程。</p></article></body></html>'.encode(), "text/html"),
            "/malformed": (200, '<html><title>未闭合<title><body><main><p>即使标签不完整，仍提取这一段真实正文内容并保持顺序。'.encode(), "text/html"),
            "/short": (200, b"<html><body>short</body></html>", "text/html"),
        }
        if self.path == "/redirect":
            self.send(302, b"", headers={"Location": "/article"})
            return
        if self.path == "/redirect-two":
            self.send(301, b"", headers={"Location": "/redirect"})
            return
        if self.path == "/loop-a":
            self.send(302, b"", headers={"Location": "/loop-b"})
            return
        if self.path == "/loop-b":
            self.send(302, b"", headers={"Location": "/loop-a"})
            return
        if self.path == "/timeout":
            time.sleep(0.25)
            self.send(200, ARTICLE.encode())
            return
        status, body, media = routes.get(self.path, routes["/404"])
        self.send(status, body, media)


class FakeResponse:
    def __init__(self, *, status=200, body=ARTICLE.encode(), content_type="text/html; charset=utf-8", url="https://example.test/article", history=()):
        self.status = status
        self.body = body
        self.headers = {"Content-Type": content_type, "Set-Cookie": "secret=must-not-leak", "ETag": "fixture"}
        self.url = url
        self.history = list(history)


def request(url="https://example.test/article", **values):
    return GenericWebCaptureRequest(
        capture_request_id=values.pop("capture_request_id", "capture_fixture_001"),
        url=url,
        requested_at=values.pop("requested_at", "2026-09-17T00:00:00Z"),
        timeout_seconds=values.pop("timeout_seconds", 2.0),
        language_hint=values.pop("language_hint", None),
        allow_private_test=values.pop("allow_private_test", True),
        **values,
    )


class GenericWebCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)

    def fake(self, response: FakeResponse):
        return lambda _request: response

    def test_A01_static_article(self):
        result = fetch_static(request(), self.fake(FakeResponse()))
        self.assertTrue(result.succeeded); self.assertIn("第一段忠实事实", result.readable_text)

    def test_A02_chinese(self):
        self.assertIn("限定条件", extract(ARTICLE.encode())["readable_text"])

    def test_A03_english(self):
        self.assertIn("No summary", extract(ENGLISH.encode())["readable_text"])

    def test_A04_redirect(self):
        result = fetch_static(request(), self.fake(FakeResponse(url="https://example.test/final", history=[object()])))
        self.assertEqual((result.final_url, result.redirect_count), ("https://example.test/final", 1))

    def test_A05_multi_redirect(self):
        result = fetch_static(request(), self.fake(FakeResponse(history=[object(), object()])))
        self.assertEqual(result.redirect_count, 2)

    def test_A06_redirect_loop(self):
        result = fetch_static(request(), lambda _: (_ for _ in ()).throw(RuntimeError("too many redirects")))
        self.assertEqual(result.failure_class, FailureClass.REDIRECT_ERROR)

    def test_A07_404(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(status=404))).failure_class, FailureClass.HTTP_4XX)

    def test_A08_429(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(status=429))).failure_class, FailureClass.HTTP_429)

    def test_A09_500(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(status=500))).failure_class, FailureClass.HTTP_5XX)

    def test_A10_timeout(self):
        result = fetch_static(request(), lambda _: (_ for _ in ()).throw(TimeoutError("timed out")))
        self.assertEqual(result.failure_class, FailureClass.TIMEOUT)

    def test_A11_network_failure(self):
        result = fetch_static(request(), lambda _: (_ for _ in ()).throw(ConnectionError("connection refused")))
        self.assertEqual(result.failure_class, FailureClass.NETWORK_ERROR)

    def test_A12_dns_failure(self):
        result = fetch_static(request("https://does-not-exist.invalid", allow_private_test=False))
        self.assertEqual(result.failure_class, FailureClass.DNS_ERROR)

    def test_A13_invalid_url(self):
        self.assertEqual(fetch_static(request("file:///tmp/a"), self.fake(FakeResponse())).failure_class, FailureClass.INVALID_URL)

    def test_A14_credentials_rejected(self):
        self.assertEqual(fetch_static(request("https://user:pass@example.test/a"), self.fake(FakeResponse())).failure_class, FailureClass.INVALID_URL)

    def test_A15_empty_html(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(body=b""))).failure_class, FailureClass.EMPTY_HTML)

    def test_A16_no_readable_text(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(body=b"<html>short</html>"))).failure_class, FailureClass.NO_READABLE_CONTENT)

    def test_A17_js_shell(self):
        body=b'<html><body><div id="root"></div><script src="app.js"></script></body></html>'
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(body=body))).failure_class, FailureClass.JAVASCRIPT_REQUIRED)

    def test_A18_login_required(self):
        body='<html><body>请登录 用户名 password</body></html>'.encode()
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(body=body))).failure_class, FailureClass.AUTHENTICATION_REQUIRED)

    def test_A19_challenge(self):
        body=b"<html><body>Cloudflare verify you are human captcha</body></html>"
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(body=body))).failure_class, FailureClass.CHALLENGE_PAGE)

    def test_A20_pdf_handoff(self):
        result=fetch_static(request(), self.fake(FakeResponse(body=b"%PDF", content_type="application/pdf")))
        self.assertEqual((result.failure_class, result.handoff_kind), (FailureClass.UNSUPPORTED_CONTENT_TYPE, "pdf"))

    def test_A21_image_handoff(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse(content_type="image/png"))).handoff_kind, "image")

    def test_A22_audio_video_handoff(self):
        audio=fetch_static(request(), self.fake(FakeResponse(content_type="audio/mpeg")))
        video=fetch_static(request(), self.fake(FakeResponse(content_type="video/mp4")))
        self.assertEqual((audio.handoff_kind, video.handoff_kind), ("audio", "video"))

    def test_A23_title_exists(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse())).title, "测试文章")

    def test_A24_title_absent(self):
        body='<html><body><article><p>没有标题但正文足够完整，不应阻断事实采集流程。</p></article></body></html>'.encode()
        self.assertIsNone(fetch_static(request(), self.fake(FakeResponse(body=body))).title)

    def test_A25_author_explicit(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse())).author, "明确作者")

    def test_A26_author_absent(self):
        self.assertIsNone(fetch_static(request(), self.fake(FakeResponse(body=ENGLISH.encode()))).author)

    def test_A27_published_explicit(self):
        self.assertEqual(fetch_static(request(), self.fake(FakeResponse())).published_at, "2026-09-17")

    def test_A28_published_absent(self):
        self.assertIsNone(fetch_static(request(), self.fake(FakeResponse(body=ENGLISH.encode()))).published_at)

    def test_A29_raw_html_retained_and_headers_sanitized(self):
        result=fetch_static(request(), self.fake(FakeResponse()))
        self.assertEqual(result.raw_html, ARTICLE.encode()); self.assertNotIn("set-cookie", result.response_headers_subset)

    def test_A30_no_ai_rewriting(self):
        result=fetch_static(request(), self.fake(FakeResponse()))
        self.assertIn("保留限定条件，不做摘要或改写", result.readable_text)

    def route(self, url: str) -> dict:
        output=Path(tempfile.mkdtemp(dir="/private/tmp"))/"route.json"
        subprocess.run([sys.executable, ROOT/"capture-provider-router/source_router.py", "--url", url, "--output", output], check=True)
        return json.loads(output.read_text())

    def test_A31_specific_provider_precedence(self):
        self.assertEqual(self.route("https://www.youtube.com/watch?v=x")["provider"], "youtube_yt_dlp")
        self.assertEqual(self.route("https://www.douyin.com/video/123456")["provider"], "douyin")

    def test_A32_generic_fallback(self):
        self.assertEqual(self.route("https://example.org/article")["provider"], "generic_web_static")

    def test_A33_localhost_not_routed_in_production(self):
        self.assertEqual(self.route("http://127.0.0.1/article")["status"], "blocked")

    def test_A34_actual_scrapling_static_fetcher(self):
        result=fetch_static(request(self.base_url+"/article", allow_private_test=True))
        self.assertTrue(result.succeeded); self.assertEqual(result.http_status, 200); self.assertNotEqual(provider_version(), "unavailable")

    def test_A35_temp_pipeline_source_manifest_inbox(self):
        base=Path(tempfile.mkdtemp(prefix="guanlan-web-e2e-", dir="/private/tmp"))
        try:
            asset_root=base/"asset-library"; material_dir=base/"materials/web"; inbox=base/"vault/00 收件箱"; inbox.mkdir(parents=True)
            result, code=capture(
                request=request(), asset_root=asset_root, material_dir=material_dir,
                inbox=inbox, projection=inbox/"2026-09-17_采集_网页.md", scope="test",
                transport=self.fake(FakeResponse()),
            )
            self.assertEqual(code, 0); self.assertTrue(Path(result["source_material"]).is_file()); self.assertTrue(Path(result["manifest"]).is_file())
            projection=next(inbox.glob("*.md")); text=projection.read_text()
            self.assertIn("当前可读内容", text); self.assertNotIn("初步摘要", text); self.assertNotIn("核心观点", text)
        finally:
            shutil.rmtree(base)

    def test_A36_duplicate_capture_uses_downstream_identity(self):
        base=Path(tempfile.mkdtemp(prefix="guanlan-web-dedupe-", dir="/private/tmp"))
        try:
            values=dict(request=request(),asset_root=base/"assets",material_dir=base/"material",scope="test",transport=self.fake(FakeResponse()))
            first, code1=capture(**values); second, code2=capture(**values)
            self.assertEqual((code1,code2),(0,0)); self.assertEqual(first["material_id"],second["material_id"]); self.assertEqual(first["revision_id"],second["revision_id"])
            self.assertEqual(second["capture_action"],"already_captured")
            self.assertEqual(len(list((base/"assets/objects/sha256").rglob("*"))), 4)
        finally:
            shutil.rmtree(base)

    def test_A37_identity_is_not_provider_output(self):
        payload=fetch_static(request(), self.fake(FakeResponse())).serializable()
        self.assertFalse({"material_id","revision_id","asset_id","workflow_state"} & payload.keys())

    def test_A38_malformed_html(self):
        body='<html><title>未闭合<title><body><main><p>即使标签不完整，仍提取这一段真实正文内容并保持顺序。'.encode()
        self.assertIn("真实正文", fetch_static(request(), self.fake(FakeResponse(body=body))).readable_text)

    def test_A39_content_objects_match_hashes(self):
        base=Path(tempfile.mkdtemp(prefix="guanlan-web-hash-", dir="/private/tmp"))
        try:
            result,code=capture(request=request(),asset_root=base/"assets",material_dir=base/"material",scope="test",transport=self.fake(FakeResponse()))
            self.assertEqual(code,0); manifest=json.loads(Path(result["manifest"]).read_text())
            for entry in manifest["entries"]:
                data=(base/"assets"/entry["storage_relative_path"]).read_bytes()
                self.assertEqual("sha256:"+hashlib.sha256(data).hexdigest(),entry["content_hash"])
        finally:
            shutil.rmtree(base)

    def test_A40_403_challenge_is_typed(self):
        body=b"<html><body>Cloudflare verify you are human captcha</body></html>"
        result=fetch_static(request(),self.fake(FakeResponse(status=403,body=body)))
        self.assertEqual(result.failure_class,FailureClass.CHALLENGE_PAGE)

    def test_A41_missing_content_type_binary_fails_closed(self):
        result=fetch_static(request(),self.fake(FakeResponse(body=b"binary-data",content_type="")))
        self.assertEqual((result.failure_class,result.handoff_kind),(FailureClass.UNSUPPORTED_CONTENT_TYPE,"binary"))

    def test_A42_production_requires_inbox_before_fetch(self):
        asset_root=ROOT/"asset-library"
        existed_before=asset_root.exists()
        called=[]
        def transport(_request):
            called.append(True)
            return FakeResponse()
        with self.assertRaisesRegex(ValueError,"requires a 00 inbox projection"):
            capture(request=request(allow_private_test=False),asset_root=asset_root,material_dir=asset_root/"materials"/"fixture",scope="production",transport=transport)
        self.assertEqual(called,[])
        self.assertEqual(asset_root.exists(),existed_before)

    def test_A43_production_rejects_foreign_root_before_fetch(self):
        base=Path(tempfile.mkdtemp(prefix="guanlan-web-foreign-",dir="/private/tmp"))
        try:
            called=[]
            with self.assertRaisesRegex(ValueError,"production asset root"):
                capture(
                    request=request(),asset_root=base/"foreign",material_dir=base/"foreign"/"materials"/"fixture",
                    inbox=base/"00 收件箱",projection=base/"00 收件箱"/"capture.md",scope="production",
                    transport=lambda _: called.append(True),
                )
            self.assertEqual(called,[])
            self.assertFalse((base/"foreign").exists())
        finally:
            shutil.rmtree(base)

    def test_A44_production_rejects_test_target_bypass(self):
        asset_root=ROOT/"asset-library"
        inbox=Path("/private/tmp/guanlan-public-test-vault/00 收件箱")
        called=[]
        with patch.dict(os.environ, {"GUANLAN_VAULT_ROOT": "/private/tmp/guanlan-public-test-vault"}):
            with self.assertRaisesRegex(ValueError,"cannot bypass public-target"):
                capture(
                    request=request(allow_private_test=True),asset_root=asset_root,
                    material_dir=asset_root/"materials"/"fixture",inbox=inbox,
                    projection=inbox/"2026-09-17_采集_网页.md",scope="production",
                    transport=lambda _: called.append(True),
                )
        self.assertEqual(called,[])


if __name__ == "__main__":
    unittest.main(verbosity=2)
