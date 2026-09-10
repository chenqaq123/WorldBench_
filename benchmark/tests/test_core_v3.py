"""Offline v3 design, five-stage construction, and release-boundary tests."""

import copy
import json
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

from generate_core_v3 import prepare, protected_output
from validate_matrix import validate_collection
from worldline.annotations import build_annotations
from worldline.artifacts import index_existing_cases, write_pipeline_result
from worldline.balance import casting_contract
from worldline.core_v3 import design_check, plan_mixed_core
from worldline.layouts import get_layout_template, layout_template_ids
from worldline.pipeline import PipelineOptions, build_prompt_pipeline, entry_content_prefix

BASE = Path(__file__).resolve().parents[1]


def mock_constructor(case, calls):
    """Synthetic fixture responses, never saved as real generated benchmark data."""
    template = get_layout_template(case["layout"])

    def request(**r):
        stage, value = r["stage"], r["input_value"]
        calls.append(stage)
        r["trace"].append({"stage": stage, "request_model": r["model"], "response_model": "test-mock"})
        if stage == "source_abstraction":
            source = value["source"]
            return {"source_id": source["id"], "archetype": source["archetype"],
                    "premise": "Participants discuss " + source["topic_terms"][0] + ".",
                    "interaction_arc": "A proposal prompts a question and a reply."}
        if stage == "subject_casting":
            return {"subjects": value["casting_contract"]}
        if stage == "story_planning":
            shots = []
            for c in value["shot_contracts"]:
                topic = value["source_topic_terms"][0]
                if c["index"] == 1:
                    beat = "Subject A discusses " + topic + "."
                elif c["events"]:
                    beat = {
                        "person_entry": "Subject B enters and sits at the established seat. Subject A discusses ",
                        "person_exit": "Subject B leaves the seat and exits the room. Subject A discusses ",
                        "position_swap": "Subject A and Subject B swap seats and discuss ",
                    }[case["task"]] + topic + "."
                else:
                    beat = " and ".join("Subject " + s for s in c["mentioned"]) + " discuss " + topic + "."
                shots.append({"index": c["index"], "beat": beat, "events": c["events"]})
            return {"shots": shots}
        if stage == "prompt_rendering":
            subjects = {s["id"]: s for s in value["subjects"]}
            a, b = subjects["A"], subjects["B"]
            topic = value["source_topic_terms"][0]
            shots = []
            for c in value["shots"]:
                if c["index"] == 1:
                    clauses = [subjects[s]["appearance"].capitalize() + " sits at " +
                               template["seats"][subjects[s]["seat"]] +
                               (" and discusses " + topic if s == "A" else "")
                               for s in c["mentioned"]]
                    text = template["public_intro"] + " " + ", ".join(clauses) + "."
                    if template.get("version") == "3.1" and case["task"] == "person_entry":
                        text += " There is one empty place."
                elif c["events"]:
                    if case["task"] == "person_entry":
                        text = entry_content_prefix(b, template) + " " + a["appearance"].capitalize() + " discusses " + topic + "."
                    elif case["task"] == "person_exit":
                        text = (b["appearance"].capitalize() + " leaves " + template["seats"][b["seat"]] +
                                " and exits the room. " + a["appearance"].capitalize() + " discusses " + topic + ".")
                    else:
                        text = (a["appearance"].capitalize() + " and " + b["appearance"] +
                                " swap " + template["seats"][a["seat"]] + " and " + template["seats"][b["seat"]] +
                                " and discuss " + topic + ".")
                    if template.get("version") == "3.1" and case["task"] == "person_exit":
                        text = b["appearance"].capitalize() + " leaves their seat and exits the room. " + a["appearance"].capitalize() + " discusses " + topic + "."
                    if template.get("version") == "3.1" and case["task"] == "position_swap":
                        text = a["appearance"].capitalize() + " and " + b["appearance"] + " swap seats and discuss " + topic + "."
                else:
                    text = " and ".join(subjects[s]["appearance"] for s in c["mentioned"]).capitalize() + " discuss " + topic + "."
                shots.append({"index": c["index"], "content": text})
            return {"shots": shots}
        if stage == "prompt_audit":
            return {"passed": True, "issues": []}
        raise AssertionError("Unexpected retry/repair: " + stage)
    return request


class CoreV3Test(unittest.TestCase):
    def test_mixed_plan_is_balanced_and_keeps_legacy_catalog(self):
        cases = plan_mixed_core()
        report, contracts = design_check(cases)
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(cases), 112)
        self.assertEqual(Counter(c["shot_count"] for c in cases), {3: 56, 4: 56})
        self.assertEqual(len(layout_template_ids()), 28)
        self.assertNotIn("version", get_layout_template("cafe_rect_table_3_v1"))
        for value in report["sources_by_scene_task"].values():
            self.assertEqual(sorted(value.values()), [2, 2])
        for record in contracts:
            self.assertEqual(sum(o["scored"] for o in record["observations"]), 1)

    def test_camera_pairs_share_controls_not_assumed_identical_generated_prose(self):
        pairs = {}
        for c in plan_mixed_core():
            template = get_layout_template(c["layout"])
            key = c["scene"], c["task"], c["subject_count"]
            controls = c["source_id"], c["shot_count"], template["seat_order"], casting_contract(c)
            self.assertEqual(pairs.setdefault(key, controls), controls)

    def test_event_seat_and_focal_side_really_rotate(self):
        seats = defaultdict(set)
        for c in plan_mixed_core():
            template = get_layout_template(c["layout"])
            seats[(c["scene"], c["subject_count"])].add(tuple(template["seat_order"][:2]))
        for (_, n), orders in seats.items():
            self.assertEqual(len(orders), 2 if n == 3 else 4)

    def test_kitchen_sides_and_overhead_orientation_are_physical(self):
        for c in plan_mixed_core():
            t = get_layout_template(c["layout"])
            if c["scene"] == "kitchen":
                self.assertIn("window", t["public_intro"])
                self.assertFalse(any("guest" in v or "cook" in v for v in t["seats"].values()))
                self.assertIn("sink basin", t["cameras"]["probe_overhead"]["public_view"])
            self.assertIn("in frame", t["cameras"]["probe_overhead"]["public_view"])
        with self.assertRaises(ValueError):
            get_layout_template("cafe_rect_table_3_r2_v3")

    def test_all_112_mock_pipelines_keep_independent_stages_and_versions(self):
        for c in plan_mixed_core():
            with self.subTest(case=c["id"]):
                calls = []
                result = build_prompt_pipeline(
                    PipelineOptions(episode_id=c["id"], layout=c["layout"], task=c["task"],
                                    shot_count=c["shot_count"], subject_count=c["subject_count"],
                                    source_id=c["source_id"]),
                    request_structured=mock_constructor(c, calls), environ={},
                )
                self.assertEqual(calls, ["source_abstraction", "subject_casting", "story_planning",
                                         "prompt_rendering", "prompt_audit"])
                self.assertEqual(result["run"]["version"], "3.0")
                self.assertEqual(result["annotations"]["version"], "3.0")
                self.assertEqual(len(result["rendered_prompt"].splitlines()), c["shot_count"])
                self.assertEqual(result["run"]["request_journal"][0]["input_value"]["source"]["id"], c["source_id"])

    def test_plan_is_offline_and_pending_is_not_complete(self):
        with tempfile.TemporaryDirectory() as d, patch("worldline.openrouter.OpenRouterClient") as client:
            manifest = prepare(Path(d))
            self.assertEqual(manifest["status_summary"], {"pending": 112})
            client.assert_not_called()
            self.assertEqual(prepare(Path(d)), manifest)
            report = validate_collection(Path(d) / "core_matrix.manifest.json", Path(d))
            self.assertTrue(report["errors"])
            self.assertTrue(all(c["public_facts_unambiguous"] is None for c in
                                json.loads((Path(d) / "review.checklist.json").read_text())["cases"]))
        with self.assertRaises(ValueError):
            protected_output(BASE / "outputs/v2")
        with self.assertRaises(ValueError):
            protected_output(BASE / "outputs")

    def test_mock_complete_collection_validates_and_corruption_is_not_reused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            prepare(root)
            for c in plan_mixed_core():
                result = build_prompt_pipeline(
                    PipelineOptions(episode_id=c["id"], layout=c["layout"], task=c["task"],
                                    shot_count=c["shot_count"], source_id=c["source_id"]),
                    request_structured=mock_constructor(c, []), environ={},
                )
                write_pipeline_result(result, root)
            manifest = prepare(root)
            self.assertEqual(manifest["status_summary"], {"complete": 112})
            report = validate_collection(root / "core_matrix.manifest.json", root)
            self.assertEqual(report["errors"], [])
            c = manifest["cases"][0]
            (root / c["id"] / "prompt.txt").write_text("changed")
            self.assertIn(c["id"], index_existing_cases(root, dataset_version="3.0")["invalid_ids"])
            self.assertEqual(prepare(root)["status_summary"], {"needs_repair": 1, "complete": 111})


if __name__ == "__main__":
    unittest.main()
