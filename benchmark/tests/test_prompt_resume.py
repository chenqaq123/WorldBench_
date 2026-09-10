"""Strict event schemas and replay of real, exact-matching stage prefixes."""

import copy
import unittest

from test_core_v3 import mock_constructor
from worldline.core_v3 import plan_mixed_core
from worldline.pipeline import PipelineOptions, build_prompt_pipeline, beat_plan_schema


class PromptResumeTest(unittest.TestCase):
    def setUp(self):
        self.case = plan_mixed_core("3.1")[0]
        self.options = PipelineOptions(episode_id=self.case["id"], layout=self.case["layout"],
            task=self.case["task"], shot_count=self.case["shot_count"], source_id=self.case["source_id"],
            model="test-shared-model", audit_model="test-audit")
        self.original = build_prompt_pipeline(self.options,
            request_structured=mock_constructor(self.case, []), environ={})

    def test_task_event_schemas_are_strict_without_unions(self):
        def visit(node):
            if isinstance(node, dict):
                self.assertNotIn("anyOf", node)
                if node.get("type") == "object":
                    self.assertEqual(set(node["properties"]), set(node["required"]))
                    self.assertIs(node["additionalProperties"], False)
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
        for task, action in (("person_entry", "enter"), ("person_exit", "exit"),
                             ("position_swap", "swap"), ("static_viewpoint_change", None)):
            with self.subTest(task=task):
                schema = beat_plan_schema({"subject_count": 3, "shot_count": 4, "task": task})
                visit(schema)
                events = schema["properties"]["shots"]["items"]["properties"]["events"]
                fields = events["items"]["properties"]
                self.assertEqual(set(fields), {"subject", "action", "with_subject"}
                                 if task == "position_swap" else {"subject", "action"})
                if action:
                    self.assertEqual(fields["action"]["enum"], [action])
                else:
                    self.assertEqual(events["maxItems"], 0)

    def test_schema_change_reuses_only_the_unchanged_prefix(self):
        cached = copy.deepcopy(self.original["run"]["request_journal"])
        events = cached[2]["schema"]["properties"]["shots"]["items"]["properties"]["events"]
        events["items"] = {"anyOf": [events["items"]]}
        calls = []
        result = build_prompt_pipeline(self.options, request_structured=mock_constructor(self.case, calls),
            environ={}, resume_journal=cached)
        self.assertEqual(calls, ["story_planning", "prompt_rendering", "prompt_audit"])
        self.assertEqual([r.get("reused", False) for r in result["run"]["request_journal"]],
                         [True, True, False, False, False])
        self.assertEqual(result["public_prompt"], self.original["public_prompt"])

    def test_exact_prefix_is_reused_without_new_llm_calls(self):
        cached = copy.deepcopy(self.original["run"]["request_journal"][:2])
        calls = []
        result = build_prompt_pipeline(self.options, request_structured=mock_constructor(self.case, calls),
            environ={}, resume_journal=cached)
        self.assertEqual(calls, ["story_planning", "prompt_rendering", "prompt_audit"])
        self.assertEqual(result["public_prompt"], self.original["public_prompt"])
        self.assertEqual(len(result["run"]["trace"]), 5)
        self.assertEqual(sum(r.get("reused", False) for r in result["run"]["request_journal"]), 2)
        self.assertNotIn("reused", cached[0])

    def test_changed_input_or_provider_cannot_reuse_cached_prefix(self):
        for change in ("input", "provider"):
            with self.subTest(change=change):
                cached = copy.deepcopy(self.original["run"]["request_journal"][:2])
                env = {}
                if change == "input":
                    cached[0]["input_value"]["source"]["id"] = "wrong-source"
                else:
                    env = {"PROMPT_PROVIDER": "vapi"}
                calls = []
                result = build_prompt_pipeline(self.options,
                    request_structured=mock_constructor(self.case, calls), environ=env, resume_journal=cached)
                self.assertEqual(len(calls), 5)
                self.assertFalse(any(r.get("reused") for r in result["run"]["request_journal"]))


if __name__ == "__main__":
    unittest.main()
