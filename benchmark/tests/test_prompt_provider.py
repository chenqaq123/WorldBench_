"""Offline provider isolation, request compatibility, and retry safety tests."""

import io
import json
import tempfile
import unittest
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from generate_core_v3 import main, next_attempt_number
from test_core_v3 import mock_constructor
from worldline.core_v3 import plan_mixed_core
from worldline.openrouter import OpenRouterClient, PermanentOpenRouterError
from worldline.pipeline import PipelineOptions, build_prompt_pipeline


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


def complete(client, trace):
    return client.complete(stage="connection_test", model="gpt-5.6-sol", schema_name="connection_test",
                           schema=SCHEMA, system="Return an object.", input_value={"ok": True},
                           temperature=0, trace=trace)


class PromptProviderTest(unittest.TestCase):
    def test_vapi_request_and_trace_do_not_include_openrouter_settings_or_key(self):
        client = OpenRouterClient("test-vapi-key", provider="vapi", site_url="https://example.com")
        response = {"id": "test-response", "model": "gpt-5.6-sol", "usage": {"total_tokens": 10},
                    "choices": [{"message": {"content": '{"ok":true}'}}]}
        with patch("worldline.openrouter.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as send:
            trace = []
            self.assertEqual(complete(client, trace), {"ok": True})
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.gpt.ge/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-vapi-key")
        self.assertEqual(body["max_completion_tokens"], 5000)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("provider", body)
        self.assertNotIn("X-title", request.headers)
        self.assertNotIn("Http-referer", request.headers)
        self.assertEqual(body["response_format"]["json_schema"]["schema"], SCHEMA)
        self.assertEqual(trace[0]["provider"], "vapi")
        self.assertNotIn("test-vapi-key", json.dumps(trace))

    def test_openrouter_request_remains_compatible(self):
        client = OpenRouterClient("test-or-key")
        with patch("worldline.openrouter.urlopen", return_value=io.BytesIO(b'{}')) as send:
            client._request(model="openai/gpt-5.6-luna", schema_name="test", schema=SCHEMA,
                            system="Test", input_value={}, temperature=0)
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(body["provider"], {"require_parameters": True})
        self.assertEqual(body["max_tokens"], 5000)
        self.assertNotIn("max_completion_tokens", body)

    def test_missing_vapi_key_does_not_fall_back_to_openrouter_key(self):
        with self.assertRaisesRegex(ValueError, "VAPI_API_KEY"):
            build_prompt_pipeline(PipelineOptions(), environ={"PROMPT_PROVIDER": "vapi",
                                                              "OPENROUTER_API_KEY": "test-or-key"})

    def test_pipeline_constructs_vapi_client_with_configured_timeout(self):
        with patch("worldline.pipeline.OpenRouterClient") as factory:
            factory.return_value.complete.side_effect = PermanentOpenRouterError("offline stop")
            with self.assertRaises(PermanentOpenRouterError):
                build_prompt_pipeline(PipelineOptions(), environ={"PROMPT_PROVIDER": "vapi",
                    "VAPI_API_KEY": "test-vapi-key", "VAPI_TIMEOUT_SECONDS": "240",
                    "OPENROUTER_API_KEY": "must-not-use"})
        self.assertEqual(factory.call_args.args, ("test-vapi-key",))
        self.assertEqual(factory.call_args.kwargs["timeout"], 240)
        self.assertEqual(factory.call_args.kwargs["provider"], "vapi")

    def test_credentials_cannot_be_rerouted_by_accident(self):
        for provider, url in [("openrouter", "https://api.gpt.ge/v1"),
                              ("vapi", "https://openrouter.ai/api/v1"),
                              ("vapi", "http://api.gpt.ge/v1"),
                              ("vapi", "https://user:password@api.gpt.ge/v1"),
                              ("vapi", "https://api.gpt.ge/v1?key=secret")]:
            with self.subTest(provider=provider, url=url), self.assertRaises(ValueError):
                OpenRouterClient("test-key", provider=provider, base_url=url)

    def test_vapi_preserves_five_stages_and_audit_tier_ignoring_old_model_overrides(self):
        case = plan_mixed_core("3.1")[0]
        calls = []
        result = build_prompt_pipeline(
            PipelineOptions(episode_id=case["id"], task=case["task"], layout=case["layout"],
                            shot_count=case["shot_count"], source_id=case["source_id"]),
            request_structured=mock_constructor(case, calls),
            environ={"PROMPT_PROVIDER": "vapi", "OPENROUTER_PROMPT_MODEL": "old-model",
                     "OPENROUTER_SKELETON_MODEL": "old-stage-model", "OPENROUTER_AUDIT_MODEL": "old-audit"},
        )
        self.assertEqual(len(calls), 5)
        self.assertEqual(result["run"]["provider"], "vapi")
        self.assertEqual([r["model"] for r in result["run"]["request_journal"]],
                         ["gpt-5.6-sol"] * 4 + ["gpt-5.6-luna"])

    def test_access_refusal_is_not_retried_and_key_is_redacted(self):
        client = OpenRouterClient("test-vapi-key", provider="vapi")
        error = HTTPError(client.endpoint, 403, "Denied", {}, io.BytesIO(b'test-vapi-key denied'))
        with patch("worldline.openrouter.urlopen", side_effect=error) as send:
            with self.assertRaises(PermanentOpenRouterError) as caught:
                complete(client, [])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertNotIn("test-vapi-key", str(caught.exception))

    def test_transient_disconnect_and_timeout_retry_the_same_request(self):
        response = {"model": "gpt-5.6-sol", "choices": [{"message": {"content": '{"ok":true}'}}]}
        for error in (TimeoutError("read timed out"), RemoteDisconnected("connection closed")):
            with self.subTest(error=type(error).__name__):
                client = OpenRouterClient("test-vapi-key", provider="vapi")
                with patch("worldline.openrouter.urlopen", side_effect=[error,
                        io.BytesIO(json.dumps(response).encode())]) as send, \
                        patch("worldline.openrouter.time.sleep"):
                    trace = []
                    self.assertEqual(complete(client, trace), {"ok": True})
                self.assertEqual(send.call_count, 2)
                first, second = [call.args[0] for call in send.call_args_list]
                self.assertEqual(first.full_url, second.full_url)
                self.assertEqual(first.data, second.data)
                self.assertEqual(len(trace), 1)

    def test_transient_connection_retries_are_bounded(self):
        client = OpenRouterClient("test-vapi-key", provider="vapi")
        trace = []
        with patch("worldline.openrouter.urlopen", side_effect=TimeoutError("read timed out")) as send, \
                patch("worldline.openrouter.time.sleep"), \
                self.assertRaisesRegex(RuntimeError, "VAPI request failed for connection_test"):
            complete(client, trace)
        self.assertEqual(send.call_count, 4)
        self.assertEqual(trace, [])

    def test_failed_first_stage_does_not_overwrite_previous_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "failure-001.json").write_text("{}")
            self.assertEqual(next_attempt_number(root), 2)
            (root / "attempt-003.json").write_text("[]")
            self.assertEqual(next_attempt_number(root), 4)

    def test_batch_stops_new_cases_after_account_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "v3.1"
            argv = ["generate_core_v3.py", "--output-root", str(root), "--execute",
                    "--limit", "3", "--workers", "1"]
            with patch("sys.argv", argv), patch("generate_core_v3.load_env_file"), \
                    patch("generate_core_v3.build_prompt_pipeline",
                          side_effect=PermanentOpenRouterError("Denied", status_code=403)) as build, \
                    patch("sys.stdout", new_callable=io.StringIO), self.assertRaises(SystemExit):
                main()
            self.assertEqual(build.call_count, 1)
            self.assertEqual(len(list(root.glob("*/failure-*.json"))), 1)
            self.assertEqual(json.loads((root / "core_matrix.manifest.json").read_text())["status_summary"],
                             {"pending": 112})


if __name__ == "__main__":
    unittest.main()
