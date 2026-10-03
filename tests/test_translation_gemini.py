"""Gemini HTTP/cache and local budget checks, without a key or a network call."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler

from radar import translation_gemini as gemini
from radar.translation_budget import reserve


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cache.json"
        guard = patch("socket.create_connection", side_effect=AssertionError("network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)

    def test_key_and_exact_confirmation_are_both_explicit(self):
        for value in (None, "", "true", "yes", "0", "1"):
            env = {"GEMINI_API_KEY": "offline-sentinel"}
            if value is not None:
                env["RADAR_GEMINI_FREE_TIER_CONFIRMED"] = value
            config = gemini.config_from_env(env)
            self.assertEqual(config.confirmed, value == "1")
            self.assertNotIn("offline-sentinel", repr(config))
        self.assertEqual(gemini.config_from_env({}).api_key, "")

    def test_config_can_lower_but_never_raise_application_caps(self):
        caps = dict(max_requests=1, daily_limit=12, batch_size=24, max_chars=12000, timeout=45)
        config = gemini.Config(**{key: value * 10 for key, value in caps.items()})
        for key, ceiling in caps.items():
            self.assertLessEqual(getattr(config, key), ceiling)
            lowered = gemini.config_from_env({"RADAR_GEMINI_" + key.upper(): "0"})
            self.assertEqual(getattr(lowered, key), 0)
            invalid = gemini.config_from_env({"RADAR_GEMINI_" + key.upper(): "invalid"})
            self.assertEqual(getattr(invalid, key), 0)

    def test_transport_uses_fixed_https_header_without_proxy_or_redirect(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"candidates": []}'
        opener = Mock()
        opener.open.return_value = response
        body = gemini.request_body([{"id": "0", "text": "Source data", "roles": ["title"],
                                     "protected_names": []}])
        with patch.object(gemini.urllib.request, "build_opener", return_value=opener) as build:
            self.assertEqual(gemini.transport(body, "offline-sentinel", 3.25), {"candidates": []})
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("X-goog-api-key"), "offline-sentinel")
        self.assertNotIn("offline-sentinel", request.full_url + request.data.decode())
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 3.25)
        handlers = build.call_args.args
        proxies = next(handler for handler in handlers if isinstance(handler, ProxyHandler))
        redirect = next(handler for handler in handlers if isinstance(handler, HTTPRedirectHandler))
        self.assertEqual(proxies.proxies, {})
        self.assertIsNone(redirect.redirect_request(request, None, 302, "redirect", {}, "https://example.test/"))
        response.read.assert_called_once_with(gemini.MAX_RESPONSE_BYTES + 1)

    def test_http_failures_are_safe_codes_and_never_retried(self):
        for status in (301, 401, 403, 429, 500):
            with self.subTest(status=status):
                error = HTTPError("https://example.test/offline-sentinel", status,
                                  "offline-sentinel", {}, io.BytesIO(b"offline-sentinel"))
                opener = Mock()
                opener.open.side_effect = error
                with patch.object(gemini.urllib.request, "build_opener", return_value=opener):
                    with self.assertRaises(gemini.ProviderError) as caught:
                        gemini.transport({}, "offline-sentinel", 1)
                self.assertNotIn("offline-sentinel", str(caught.exception))
                self.assertEqual(opener.open.call_count, 1)

    def http_error_code(self, status, body):
        error = HTTPError("https://example.test/", status, "offline-sentinel", {}, io.BytesIO(body))
        opener = Mock()
        opener.open.side_effect = error
        with patch.object(gemini.urllib.request, "build_opener", return_value=opener):
            with self.assertRaises(gemini.ProviderError) as caught:
                gemini.transport({}, "offline-sentinel", 1)
        self.assertEqual(opener.open.call_count, 1)
        self.assertNotIn("offline-sentinel", str(caught.exception))
        return str(caught.exception)

    def test_http_error_names_numeric_code_and_enum_status_only(self):
        body = json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                     "message": "offline-sentinel echoed request text"}}).encode()
        self.assertEqual(self.http_error_code(400, body), "http_400:INVALID_ARGUMENT")
        self.assertEqual(self.http_error_code(404, b'{"error": {"code": 404}}'), "http_404")
        self.assertEqual(self.http_error_code(404, json.dumps(
            {"error": {"status": "NOT_FOUND"}}).encode()), "http_404:NOT_FOUND")

    def test_http_error_falls_back_for_unusable_bodies(self):
        oversize = json.dumps({"error": {"status": "INVALID_ARGUMENT", "pad": "x" * gemini.MAX_ERROR_BODY_BYTES}}).encode()
        for raw in (b"<html>offline-sentinel</html>", b"", oversize, b"[1, 2]", b'{"error": "offline-sentinel"}',
                    b'{"error": {"status": "invalid-offline-sentinel"}}',
                    b'{"error": {"status": "' + b"A" * 41 + b'"}}',
                    b'{"error": {"status": "INVALID_ARGUMENT\\n"}}', b'{"error": {"status": 400}}'):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(self.http_error_code(400, raw), "http_400")

    def test_http_error_code_helper_rejects_out_of_range_codes(self):
        for code in (None, True, 99, 600, "400"):
            self.assertEqual(gemini.http_error_code(code, "INVALID_ARGUMENT"), "http_error")

    def test_response_must_be_complete_unique_and_structured(self):
        def response(rows, finish="STOP"):
            return {"candidates": [{"finishReason": finish, "content": {"parts": [
                {"text": json.dumps({"translations": rows})}]}}]}
        valid = [{"id": "b", "text": "Bản dịch B"}, {"id": "a", "text": "Bản dịch A"}]
        self.assertEqual(gemini.parse_response(response(valid), ["a", "b"]),
                         {"a": "Bản dịch A", "b": "Bản dịch B"})
        malformed = [response(valid, "MAX_TOKENS"), response(valid[:1]),
                     response([valid[0], valid[0]]), response([*valid, {"id": "c", "text": "extra"}]),
                     response([{"id": "a", "text": 123}, valid[0]]),
                     {"promptFeedback": {"blockReason": "SAFETY"}}, {}, [], None]
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(gemini.ProviderError):
                gemini.parse_response(value, ["a", "b"])

    def test_final_text_with_thought_signature_is_accepted_but_thoughts_are_not_output(self):
        final = json.dumps({"translations": [{"id": "0", "text": "Bản dịch hợp lệ"}]})
        parts = [{"text": "private reasoning that is not JSON", "thought": True},
                 {"text": final[:12], "thoughtSignature": "opaque-signature"},
                 {"text": final[12:], "thought": False}]
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": parts}}]}
        self.assertEqual(gemini.parse_response(response, ["0"]), {"0": "Bản dịch hợp lệ"})
        for invalid in ([{"text": final, "thought": True}],
                        [{"functionCall": {"name": "unexpected", "args": {}}}],
                        [{"text": final, "thought": "true"}]):
            response["candidates"][0]["content"]["parts"] = invalid
            with self.subTest(parts=invalid), self.assertRaises(gemini.ProviderError):
                gemini.parse_response(response, ["0"])

    def test_malformed_or_oversized_http_body_is_rejected_without_raw_diagnostics(self):
        for raw in (b"offline-sentinel", b"x" * (gemini.MAX_RESPONSE_BYTES + 1)):
            response = Mock()
            response.__enter__ = Mock(return_value=response)
            response.__exit__ = Mock(return_value=False)
            response.read.return_value = raw
            opener = Mock()
            opener.open.return_value = response
            with patch.object(gemini.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(gemini.ProviderError) as caught:
                    gemini.transport({}, "offline-sentinel", 1)
            self.assertNotIn("offline-sentinel", str(caught.exception))

    def test_cache_round_trip_separates_provider_model_and_prompt(self):
        entries = {"Hello world": "Xin chào thế giới"}
        gemini.save_cache(self.path, entries)
        self.assertEqual(gemini.load_cache(self.path), entries)
        original = json.loads(self.path.read_text(encoding="utf-8"))
        for key in ("provider", "model", "prompt_version"):
            changed = {**original, key: "other"}
            self.path.write_bytes(json.dumps(changed).encode())
            self.assertEqual(gemini.load_cache(self.path), {})
        self.path.write_bytes(b"{not json")
        self.assertEqual(gemini.load_cache(self.path), {})
        self.assertEqual(gemini.load_cache(self.path.with_name("missing.json")), {})

    def test_rolling_day_limit_counts_reservations_and_expires_conservatively(self):
        now = 100000.0
        for _ in range(12):
            self.assertIsNone(reserve(self.path, 999, now))
        self.assertEqual(reserve(self.path, 999, now + 86399), "daily_limit")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["attempts"], [now] * 12)
        self.assertIsNone(reserve(self.path, 12, now + 86400))
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["attempts"], [now + 86400])

    def test_lowered_daily_limit_and_invalid_ledger_fail_closed(self):
        self.assertIsNone(reserve(self.path, 1, 100))
        self.assertEqual(reserve(self.path, 1, 101), "daily_limit")
        for raw in (b"not json", b'{}', b'{"version":1,"attempts":[999]}'):
            self.path.write_bytes(raw)
            self.assertIsNotNone(reserve(self.path, 12, 100))
            self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(reserve(None, 12, 100), "ledger_unavailable")


if __name__ == "__main__":
    unittest.main()
