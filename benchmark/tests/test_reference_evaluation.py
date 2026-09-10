"""Offline protocol tests. All visual judgments here are synthetic fixtures."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from generate_core_v3 import prepare as prepare_dataset
from run_evaluation import DEFAULT_JUDGE, generation_parameters, judge_settings, prepare
from validate_evaluation import validate_run
from validate_matrix import validate_collection
from worldline.artifacts import write_pipeline_result
from worldline.core_v3 import design_check, plan_mixed_core
from worldline.evaluation import PROTOCOL, REFERENCE_PROTOCOL, score_episode, write_report
from worldline.judge import evaluate_video
from worldline.layouts import get_layout_template
from worldline.pipeline import PipelineOptions, build_prompt_pipeline, validate_prompt, _renderer_system, _auditor_system
from worldline.reference_evaluation import (derive_target, reference_context, reference_schema,
                                           score_reference_episode, validate_reference_observation)
from worldline.video import file_hash, read_json, write_json
from test_core_v3 import mock_constructor


def context_and_observation(task="position_swap"):
    event = {
        "position_swap": [{"subject": "A", "action": "swap", "with_subject": "B"}],
        "person_entry": [{"subject": "B", "action": "enter"}],
        "person_exit": [{"subject": "B", "action": "exit"}],
        "static_viewpoint_change": [],
    }[task]
    context = {"initial_identities": list("AC" if task == "person_entry" else "ABC"),
               "identity_references": [{"id": s} for s in "ABC"], "places": ["P1", "P2", "P3"],
               "updates": [{"shot": 2, "content": "Requested event fixture", "events": event}]}
    initial = {"P1": "A", "P2": None if task == "person_entry" else "B", "P3": "C"}
    opening = {"view_compliant": True, "readable": True, "layout_usable": True, "count": len(context["initial_identities"]),
               "places": {p: {"description": "physical place " + p, "occupant": v} for p, v in initial.items()},
               "evidence": "synthetic opening"}
    anchors = [{"subject": s, "reliable": True, "evidence": "synthetic identity"} for s in "ABC"]
    target = derive_target(context, opening, anchors)
    frames = [{"frame": "readout_" + str(i), "view_compliant": True, "readable": True,
               "count": target["expected_count"], "occupants": copy.deepcopy(target["expected_occupants"]),
               "evidence": "synthetic final"} for i in (1, 2)]
    return context, {"opening": opening, "anchors": anchors, "frames": frames, "uncertainties": []}


def constructed(case):
    return build_prompt_pipeline(
        PipelineOptions(episode_id=case["id"], layout=case["layout"], task=case["task"],
                        shot_count=case["shot_count"], source_id=case["source_id"]),
        request_structured=mock_constructor(case, []), environ={})


class ReferenceEvaluationTest(unittest.TestCase):
    def test_all_four_tasks_update_and_preserve(self):
        for task in ("position_swap", "person_entry", "person_exit", "static_viewpoint_change"):
            context, observed = context_and_observation(task)
            score = score_reference_episode(context, observed)
            self.assertTrue(score["joint_success"], task)
            self.assertEqual(score["target"]["expected_occupants"]["P3"], "C")

    def test_initial_order_drift_uses_observed_places_not_prescribed_order(self):
        context, observed = context_and_observation()
        observed["opening"]["places"]["P1"]["occupant"] = "B"
        observed["opening"]["places"]["P2"]["occupant"] = "A"
        target = derive_target(context, observed["opening"], observed["anchors"])
        self.assertEqual(target["expected_occupants"], {"P1": "A", "P2": "B", "P3": "C"})
        for frame in observed["frames"]:
            frame["occupants"] = target["expected_occupants"]
        self.assertTrue(score_reference_episode(context, observed)["joint_success"])

    def test_unexecuted_swap_is_not_forgiven(self):
        context, observed = context_and_observation()
        for frame in observed["frames"]:
            frame["occupants"] = {"P1": "A", "P2": "B", "P3": "C"}
        score = score_reference_episode(context, observed)
        self.assertTrue(score["valid"])
        self.assertTrue(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_changed_final_cannot_change_derived_target(self):
        context, observed = context_and_observation()
        before = score_reference_episode(context, observed)["target"]
        observed["frames"][0]["occupants"] = {"P1": "C", "P2": "A", "P3": "B"}
        self.assertEqual(score_reference_episode(context, observed)["target"], before)

    def test_extra_person_counts_and_one_bad_frame_fails(self):
        context, observed = context_and_observation()
        observed["frames"][1]["count"] += 1
        score = score_reference_episode(context, observed)
        self.assertTrue(score["valid"])
        self.assertFalse(score["count_correct"])
        self.assertTrue(score["position_correct"])
        self.assertFalse(score["joint_success"])

    def test_count_correct_bystander_position_wrong(self):
        context, observed = context_and_observation("person_exit")
        observed["frames"][1]["occupants"] = {"P1": "A", "P2": "C", "P3": None}
        score = score_reference_episode(context, observed)
        self.assertTrue(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_unknown_identity_is_error_not_invalid_but_unobservable_is_invalid(self):
        context, observed = context_and_observation()
        observed["frames"][0]["occupants"]["P3"] = "unknown"
        score = score_reference_episode(context, observed)
        self.assertTrue(score["valid"])
        self.assertFalse(score["position_correct"])
        observed["frames"][0]["occupants"]["P3"] = "unobservable"
        observed["frames"][0]["readable"] = False
        score = score_reference_episode(context, observed)
        self.assertFalse(score["valid"])
        self.assertIsNone(score["count_correct"])
        self.assertIsNone(score["position_correct"])
        self.assertFalse(score["joint_success"])

    def test_invalid_initial_cast_count_topology_or_reference_is_not_normalized(self):
        context, original = context_and_observation()
        for field in ("extra", "missing", "topology", "identity", "unstable"):
            observed = copy.deepcopy(original)
            if field == "extra":
                observed["opening"]["count"] = 4
            elif field == "missing":
                observed["opening"]["count"] = 2
                observed["opening"]["places"]["P3"]["occupant"] = None
            elif field == "topology":
                observed["opening"]["layout_usable"] = False
            elif field == "identity":
                observed["anchors"][0]["reliable"] = False
            else:
                observed["opening"]["readable"] = False
            score = score_reference_episode(context, observed)
            self.assertFalse(score["reference_valid"], field)
            self.assertFalse(score["valid"], field)
            self.assertIsNone(score["position_correct"], field)

    def test_entry_reference_cannot_repair_initial_and_ambiguous_destination_rejected(self):
        context, observed = context_and_observation("person_entry")
        observed["anchors"][1]["reliable"] = False
        score = score_reference_episode(context, observed)
        self.assertTrue(score["reference_valid"])
        self.assertTrue(score["valid"])
        self.assertFalse(score["position_correct"])
        context["places"].append("P4")
        observed["opening"]["places"]["P4"] = {"description": "extra empty place", "occupant": None}
        target = derive_target(context, observed["opening"], observed["anchors"])
        self.assertFalse(target["valid"])
        self.assertIn("entry_requires_one_unambiguous_empty_place", target["issues"])

    def test_schema_consistency_and_two_frames(self):
        context, observed = context_and_observation()
        readouts = [{"label": "readout_1"}, {"label": "readout_2"}]
        validate_reference_observation(observed, context, readouts)
        observed["frames"][0]["count"] = 1
        with self.assertRaises(ValueError):
            validate_reference_observation(observed, context, readouts)
        with self.assertRaises(ValueError):
            validate_reference_observation(observed, context, readouts[:1])

    def test_wrong_final_camera_and_duplicate_identity(self):
        context, observed = context_and_observation()
        observed["frames"][0]["view_compliant"] = False
        self.assertFalse(score_reference_episode(context, observed)["valid"])
        observed["frames"][0]["view_compliant"] = True
        observed["frames"][0]["occupants"]["P3"] = "A"
        score = score_reference_episode(context, observed)
        self.assertTrue(score["valid"])
        self.assertTrue(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_entry_evidence_has_only_two_opening_two_identity_and_two_readouts(self):
        from worldline.judge import build_evidence
        annotation = {"identity_anchor_shots": {"A": 1, "B": 2, "C": 1}}
        alignment = {"shots": [{"index": i, "start": (i-1)*3, "end": i*3} for i in range(1, 5)]}
        with tempfile.TemporaryDirectory() as d:
            with patch("worldline.judge.extract_frame", side_effect=lambda video, time, path: {"path": str(path), "time": time}), patch(
                    "worldline.judge.contact_sheet"), patch("worldline.judge.prepare_overview"):
                frames = build_evidence(d, "unused-video", alignment, annotation, protocol=REFERENCE_PROTOCOL)
            self.assertEqual([f["role"] for f in frames], ["opening"]*2 + ["anchor"]*2 + ["readout"]*2)
            self.assertEqual([f["shot"] for f in frames], [1, 1, 2, 2, 4, 4])
            self.assertEqual([f["time"] for f in frames], [0.75, 2.25, 3.75, 5.25, 9.75, 11.25])

    def test_missing_initial_evidence_never_calls_judge_and_pending_report_has_no_scores(self):
        case = plan_mixed_core("3.1")[0]
        result = constructed(case)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            directory = root / case["id"]
            write_pipeline_result(result, root / "dataset")
            args = SimpleNamespace(output=root / "evaluation", dataset=root / "dataset", model="test-video",
                                   judge=DEFAULT_JUDGE, protocol=REFERENCE_PROTOCOL, seconds_per_shot=3,
                                   resolution="480p", seed=42, case_id=[case["id"]], all_cases=False, phase="plan")
            write_json(args.dataset / "core_matrix.manifest.json", {"version": "3.1", "cases": [{**case, "status": "complete"}]})
            manifest = prepare(args)
            report = write_report(args.output, manifest)
            self.assertFalse(report["complete"])
            self.assertEqual(report["evaluated_count"], 0)
            self.assertTrue(all(report["micro"][k] is None for k in
                                ("valid_observation_rate", "count_accuracy", "position_accuracy", "end_to_end_success")))
            directory = args.output / case["id"]
            (directory / "video.mp4").touch()
            client = Mock()
            with patch("worldline.judge.align_video", return_value={"uncertain": False}), patch(
                    "worldline.judge.build_evidence", return_value=[]):
                score = evaluate_video(client, directory, manifest["judge"])
            client.request.assert_not_called()
            self.assertFalse(score["valid"])
            self.assertEqual(score["failure"], "missing_or_unresolved_opening_or_final_alignment")

    def test_all_112_new_mock_pipelines_collection_and_no_probe_landmarks(self):
        cases = plan_mixed_core("3.1")
        report, _ = design_check(cases, "3.1")
        self.assertFalse(report["errors"])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(prepare_dataset(root, "3.1")["status_summary"], {"pending": 112})
            for case in cases:
                result = constructed(case)
                self.assertEqual(result["run"]["version"], "3.1")
                write_pipeline_result(result, root)
                template = result["annotations"]["layout"]
                final = result["episode"]["shots"][-1]["prompt"]["viewpoint"]
                self.assertNotIn("in frame", final)
                self.assertFalse(any(label in final for label in template["seats"].values()))
                context = reference_context(result["episode"], result["annotations"])
                self.assertNotIn("seats", context)
                self.assertNotIn("expected_occupants", context)
                changed = copy.deepcopy(result["annotations"])
                changed["observations"][-1]["expected_occupants"] = {"fake": "ANSWER"}
                self.assertEqual(context, reference_context(result["episode"], changed))
            self.assertEqual(prepare_dataset(root, "3.1")["status_summary"], {"complete": 112})
            self.assertFalse(validate_collection(root / "core_matrix.manifest.json", root)["errors"])
            with self.assertRaises(ValueError):
                prepare_dataset(root, "3.0")

    def test_instruction_updates_and_legacy_compatibility_are_explicit(self):
        config = {"dataset_version": "3.1", "shot_count": 3, "task": "person_entry"}
        renderer, auditor = _renderer_system(config), _auditor_system(config)
        self.assertNotIn("exact compact seat label for every changing subject", renderer)
        self.assertNotIn("Opening and final wide views must state", auditor)
        self.assertIn("one empty place", renderer)
        case = plan_mixed_core("3.1")[0]
        result = constructed(case)
        bad = copy.deepcopy(result["episode"])
        bad["shots"][-1]["prompt"]["viewpoint"] += " All seats in frame."
        self.assertTrue(validate_prompt(bad))
        with self.assertRaises(ValueError):
            score_episode(result["annotations"])
        with self.assertRaises(ValueError):
            reference_context(result["episode"], {**result["annotations"], "version": "3.0"})

    def test_mock_end_to_end_saves_all_inputs_scores_and_audits_without_network(self):
        case = next(c for c in plan_mixed_core("3.1") if c["task"] == "position_swap" and c["subject_count"] == 3)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = constructed(case)
            write_pipeline_result(result, root / "dataset")
            write_json(root / "dataset/core_matrix.manifest.json", {"version": "3.1", "cases": [{**case, "status": "complete"}]})
            args = SimpleNamespace(output=root / "evaluation", dataset=root / "dataset", model="test-video",
                                   judge=DEFAULT_JUDGE, protocol=REFERENCE_PROTOCOL, seconds_per_shot=3,
                                   resolution="480p", seed=42, case_id=[case["id"]], all_cases=False, phase="plan")
            manifest = prepare(args)
            directory = args.output / case["id"]
            video = directory / "video.mp4"
            video.write_bytes(b"synthetic video fixture, not real media")
            duration = case["shot_count"] * 3
            write_json(directory / "video.metadata.json", {"sha256": file_hash(video), "duration": duration, "width": 864, "height": 496})
            write_json(directory / "generation.request.json", {**generation_parameters(manifest["generation"], manifest["cases"][0]), "prompt": result["rendered_prompt"].strip()})
            alignment = {"shots": [{"index": i, "start": (i-1)*3, "end": i*3, "transition": "cut"} for i in range(1, case["shot_count"]+1)],
                         "uncertain": False, "extra_cuts": False}
            write_json(directory / "alignment.json", alignment)
            context, observed = context_and_observation()
            client = Mock()
            client.request.return_value = {"choices": [{"message": {"content": json.dumps(observed)}}], "usage": {"cost": 0}}
            def extract(video, time, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic image fixture")
                return {"path": str(path), "time": time, "sha256": file_hash(path)}
            with patch("worldline.judge.align_video", return_value=alignment), patch("worldline.judge.extract_frame", side_effect=extract), patch(
                    "worldline.judge.contact_sheet"), patch("worldline.judge.prepare_overview"):
                score = evaluate_video(client, directory, manifest["judge"])
            self.assertTrue(score["joint_success"])
            client.request.assert_called_once()
            trace = read_json(directory / "judge/reference_observer/request.json")
            self.assertEqual(trace["protocol"], REFERENCE_PROTOCOL)
            self.assertEqual([f["role"] for f in trace["input"]["frames"]], ["opening", "opening", "readout", "readout"])
            self.assertEqual(trace["input"]["updates"][0]["events"], context["updates"][0]["events"])
            self.assertNotIn("expected_occupants", trace["input"])
            self.assertFalse((directory / "diagnostics.json").exists())
            self.assertFalse(validate_run(args.output)["errors"])
            report = write_report(args.output, manifest)
            self.assertEqual(report["micro"]["end_to_end_success"], 1)
            self.assertNotIn("view_compliance_rate", report["micro"])
            self.assertIn("开场空间参照", (args.output / "report.html").read_text())
            write_json(directory / "reference.target.json", {"tampered": True})
            self.assertTrue(validate_run(args.output)["errors"])

    def test_pending_and_legacy_selection_cannot_run_new_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            args = SimpleNamespace(output=root / "evaluation", dataset=root / "dataset", model="test-video",
                                   judge=DEFAULT_JUDGE, protocol=REFERENCE_PROTOCOL, seconds_per_shot=3,
                                   resolution="480p", seed=42, case_id=["case"], all_cases=False, phase="plan")
            write_json(args.dataset / "core_matrix.manifest.json", {"version": "2.0", "cases": [{"id": "case", "status": "complete"}]})
            with self.assertRaisesRegex(ValueError, "requires dataset 3.1"):
                prepare(args)
            self.assertFalse(args.output.exists())
            args.case_id = None
            with self.assertRaisesRegex(ValueError, "Select --case-id"):
                prepare(args)


if __name__ == "__main__":
    unittest.main()
