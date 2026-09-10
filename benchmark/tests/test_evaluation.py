"""Offline regressions for scoring validity, blinding, and paid-job safety."""

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from worldline.evaluation import READOUT_FRACTIONS, LEGACY_PROTOCOL, blind_context, observation_signature, score_episode, summarize, validate_observation, write_report
from worldline.judge import judge_call, obj, observation_schema, validate_schema
from worldline.video import OpenRouterHTTPError, generate_video, read_json, write_json
from run_evaluation import generation_parameters, validate_generation_parameters


def annotation():
    return {"observations": [{"scored": False, "shot": 1}, {"scored": True, "shot": 3,
        "expected_count": 2, "expected_occupants": {"near": "A", "far": "C", "end": None}}]}


def observation(frame_count=None):
    frame_count = len(READOUT_FRACTIONS) if frame_count is None else frame_count
    return {"anchors": [{"subject": s, "reliable": True, "evidence": "visible reference"} for s in "ABC"],
        "frames": [{"frame": "readout_" + str(i), "view_compliant": True, "readable": True,
                    "count": 2, "occupants": {"near": "A", "far": "C", "end": None}, "evidence": "visible frame"}
                   for i in range(1, frame_count + 1)], "uncertainties": []}


class EvaluationTests(unittest.TestCase):
    def test_unstarted_evaluation_is_not_zero_model_accuracy(self):
        pending = {**score_episode(annotation()), "evaluated": False}
        result = summarize([pending])
        self.assertEqual(result["evaluated"], 0)
        self.assertIsNone(result["end_to_end_success"])
        self.assertIsNone(result["view_compliance_rate"])

    def test_report_renders_pending_and_completed_cases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "case"
            write_json(directory / "input" / "annotations.hidden.json", annotation())
            (directory / "input" / "prompt.txt").write_text("Shot 1: <untrusted>")
            manifest = {"generation": {"seconds_per_shot": 3, "resolution": "480p"}, "judge": {},
                        "cases": [{"id": "case", "task": "person_exit", "scene": "room", "subject_count": 3, "viewpoint_mode": "overhead"}]}
            report = write_report(root, manifest)
            self.assertFalse(report["complete"])
            self.assertIsNone(report["micro"]["end_to_end_success"])
            self.assertIn("&lt;untrusted&gt;", (root / "report.html").read_text())
            self.assertNotIn('src="case/video.mp4"', (root / "report.html").read_text())
            write_json(directory / "score.json", score_episode(annotation(), observation()))
            write_json(directory / "observation.json", observation())
            report = write_report(root, manifest)
            self.assertTrue(report["complete"])
            self.assertEqual(report["micro"]["end_to_end_success"], 1)
            self.assertEqual(report["by_viewpoint"]["overhead"]["count_accuracy"], 1)
            self.assertTrue((root / "results.csv").exists())

    def test_judge_reuses_successful_call_without_network_and_rejects_changed_input(self):
        with tempfile.TemporaryDirectory() as temp:
            client = Mock()
            client.request.return_value = {"choices": [{"message": {"content": json.dumps({"ok": True})}}],
                                           "model": "test-model", "usage": {"cost": 0.01}}
            schema = obj({"ok": {"type": "boolean"}})
            first = judge_call(client, temp, "test", "test-model", "system", {"neutral": True}, schema, [])
            second = judge_call(client, temp, "test", "test-model", "system", {"neutral": True}, schema, [])
            self.assertEqual(first, second)
            self.assertEqual(client.request.call_count, 1)
            with self.assertRaises(ValueError):
                judge_call(client, temp, "test", "test-model", "changed", {"neutral": True}, schema, [])
            self.assertEqual(client.request.call_count, 1)
            self.assertEqual(len(list((Path(temp) / "judge" / "test").glob("*.response.json"))), 1)

    def test_inflight_budget_retries_but_insufficient_credits_does_not(self):
        for reason, expected_calls in (("in_flight_budget_exhausted", 2), (None, 1)):
            with tempfile.TemporaryDirectory() as temp:
                client = Mock()
                client.request.side_effect = [OpenRouterHTTPError(402, "budget", reason, 120),
                    {"choices": [{"message": {"content": '{"ok":true}'}}]}]
                schema = obj({"ok": {"type": "boolean"}})
                with patch("worldline.judge.time.sleep") as sleeper:
                    if reason:
                        self.assertTrue(judge_call(client, temp, "budget_test", "model", "system", {}, schema, [])["ok"])
                        self.assertEqual(sum(c.args[0] for c in sleeper.call_args_list), 120)
                        self.assertTrue(all(c.args[0] <= 30 for c in sleeper.call_args_list))
                    else:
                        with self.assertRaises(RuntimeError):
                            judge_call(client, temp, "budget_test", "model", "system", {}, schema, [])
                        sleeper.assert_not_called()
                self.assertEqual(client.request.call_count, expected_calls)

    def test_temperature_omission_is_explicit_frozen_and_default_unchanged(self):
        for temperature in (0, None):
            with tempfile.TemporaryDirectory() as temp:
                client = Mock()
                client.request.return_value = {"choices": [{"message": {"content": '{"ok":true}'}}]}
                judge_call(client, temp, "observer", "model", "system", {},
                           obj({"ok": {"type": "boolean"}}), [], temperature=temperature)
                payload = client.request.call_args.args[1]
                self.assertEqual("temperature" in payload, temperature is not None)
                saved = read_json(Path(temp) / "judge/observer/request.json")
                self.assertEqual(saved["temperature"], temperature)
                with self.assertRaises(ValueError):
                    judge_call(client, temp, "observer", "model", "system", {},
                               obj({"ok": {"type": "boolean"}}), [],
                               temperature=None if temperature == 0 else 0)

    def test_explicit_retry_only_for_definitively_rejected_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            client = Mock()
            client.request.side_effect = OpenRouterHTTPError(402, "Insufficient credits")
            with self.assertRaises(OpenRouterHTTPError):
                generate_video(client, temp, {"prompt": "x"})
            self.assertEqual(read_json(Path(temp) / "generation.job.json")["status"], "rejected")
            with self.assertRaises(RuntimeError):
                generate_video(client, temp, {"prompt": "x"})
            self.assertEqual(client.request.call_count, 1)
            client.request.side_effect = None
            client.request.return_value = {"id": "existing-job", "status": "completed"}
            with patch("worldline.video.media_info", return_value={"duration": 9}), patch("worldline.video.file_hash", return_value="hash"):
                generate_video(client, temp, {"prompt": "x"}, retry_rejected=True)
            self.assertEqual(client.request.call_count, 2)
            self.assertTrue((Path(temp) / "generation.rejected-001.json").exists())

    def test_duration_is_three_seconds_per_actual_shot(self):
        for shots, seconds in ((3, 9), (4, 12), (5, 15), (7, 21)):
            settings = {"model": "video-model", "seconds_per_shot": 3}
            parameters = generation_parameters(settings, {"shot_count": shots})
            self.assertEqual(parameters["duration"], seconds)
            self.assertNotIn("seconds_per_shot", parameters)
            self.assertEqual(settings["seconds_per_shot"], 3)

    def test_duration_cannot_change_within_frozen_run(self):
        with self.assertRaises(ValueError):
            generation_parameters({"seconds_per_shot": 3}, {"shot_count": 3, "duration": 15})

    def test_unsupported_long_duration_rejected_before_batch_submission(self):
        model = {"id": "test-model", "supported_durations": list(range(4, 16)),
                 "supported_resolutions": ["720p"], "supported_aspect_ratios": ["16:9"]}
        manifest = {"generation": {"seconds_per_shot": 3, "resolution": "720p", "aspect_ratio": "16:9"},
                    "cases": [{"id": "three", "shot_count": 3}, {"id": "seven", "shot_count": 7}]}
        with self.assertRaisesRegex(ValueError, "duration=21"):
            validate_generation_parameters(model, manifest)
        manifest["cases"].pop()
        validate_generation_parameters(model, manifest)

    def test_two_fixed_readouts_must_both_pass(self):
        observed = observation()
        self.assertTrue(score_episode(annotation(), observed)["joint_success"])
        observed["frames"][1]["count"] = 3
        result = score_episode(annotation(), observed)
        self.assertTrue(result["valid"])
        self.assertFalse(result["count_correct"])
        self.assertTrue(result["position_correct"])
        self.assertFalse(result["joint_success"])

    def test_correct_count_wrong_identity_permutation(self):
        observed = observation()
        for f in observed["frames"]:
            f["occupants"].update(near="C", far="A")
        score = score_episode(annotation(), observed)
        self.assertTrue(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_visible_missing_person_is_state_failure_not_invalid(self):
        observed = observation()
        for f in observed["frames"]:
            f["occupants"]["far"] = None
            f["count"] = 1
        score = score_episode(annotation(), observed)
        self.assertTrue(score["valid"])
        self.assertFalse(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_unknown_identity_is_error_not_unreadable(self):
        observed = observation()
        observed["frames"][0]["occupants"]["far"] = "unknown"
        score = score_episode(annotation(), observed)
        self.assertTrue(score["valid"])
        self.assertTrue(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_missing_anchor_cannot_be_certified_from_final_clothing(self):
        observed = observation()
        observed["anchors"][2]["reliable"] = False
        score = score_episode(annotation(), observed)
        self.assertTrue(score["valid"])
        self.assertTrue(score["count_correct"])
        self.assertFalse(score["position_correct"])

    def test_one_unobservable_seat_invalidates_episode(self):
        observed = observation()
        observed["frames"][1]["occupants"]["end"] = "unobservable"
        score = score_episode(annotation(), observed)
        self.assertFalse(score["valid"])
        self.assertIsNone(score["count_correct"])
        self.assertIsNone(score["position_correct"])

    def test_failed_view_is_in_e2e_denominator(self):
        observed = observation()
        observed["frames"][1]["view_compliant"] = False
        failed = score_episode(annotation(), observed)
        missing = score_episode(annotation(), failure="no_video")
        passed = score_episode(annotation(), observation())
        report = summarize([failed, missing, passed])
        self.assertEqual(report["total"], 3)
        self.assertEqual(report["valid"], 1)
        self.assertEqual(report["count_accuracy"], 1)
        self.assertEqual(report["end_to_end_success"], 1 / 3)
        self.assertIsNone(summarize([failed])["count_accuracy"])

    def test_diagnostics_do_not_gate_endpoint(self):
        result = score_episode(annotation(), observation(), {"establishment_correct": True,
            "partial_views_correct": False, "event_fidelity": False, "shot_sequence_correct": False})
        self.assertTrue(result["joint_success"])
        self.assertFalse(result["strict_trajectory_success"])

    def test_cannot_choose_only_favorable_readouts(self):
        observed = observation()
        observed["frames"].pop()
        with self.assertRaises(ValueError):
            score_episode(annotation(), observed)

    def test_legacy_five_frames_require_the_legacy_protocol(self):
        old = observation(frame_count=5)
        with self.assertRaises(ValueError):
            score_episode(annotation(), old)
        self.assertTrue(score_episode(annotation(), old, protocol=LEGACY_PROTOCOL)["joint_success"])
        with self.assertRaises(ValueError):
            score_episode(annotation(), observation(), protocol=LEGACY_PROTOCOL)

    def test_blind_context_allowlist(self):
        a = annotation()
        a.update(layout={"public_intro": "A room", "seats": {"near": "window seat", "far": "door seat", "end": "end seat"},
            "cameras": {"opening": {"public_view": "Wide toward window"}, "final": {"public_view": "Reverse wide toward door"}}},
            identity_anchor_shots={"A": 1})
        a["observations"][-1]["camera"] = "final"
        episode = {"task": "person_exit", "subjects": [{"id": "A", "appearance": "man in red shirt", "seat": "near", "initially_present": True}],
                   "shots": [{"camera": "opening"}]}
        context = blind_context(episode, a)
        self.assertEqual(context["identity_references"], [{"id": "A", "descriptor": "man in red shirt", "anchor_shot": 1}])
        self.assertFalse({"task", "expected_count", "expected_occupants", "events", "initially_present"} & set(context))
        self.assertNotIn("seat", context["identity_references"][0])

    def test_schema_and_semantic_validation(self):
        context = {"identity_references": [{"id": s} for s in "ABC"], "seats": {"near": "Near", "far": "Far", "end": "End"}}
        observed = observation()
        validate_schema(observed, observation_schema(context))
        frames = [{"label": f["frame"]} for f in observed["frames"]]
        validate_observation(observed, context, frames)
        observed["frames"][0]["count"] = 0
        with self.assertRaises(ValueError):
            validate_observation(observed, context, frames)

    def test_independence_compares_evidence_not_wording(self):
        one, two = observation(), observation()
        two["frames"][0]["evidence"] = "different wording"
        self.assertEqual(observation_signature(one), observation_signature(two))
        two["frames"][0]["occupants"]["end"] = "unknown"
        self.assertNotEqual(observation_signature(one), observation_signature(two))

    def test_ambiguous_paid_submission_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as temp:
            client = Mock()
            client.request.side_effect = TimeoutError("ambiguous network timeout")
            with self.assertRaises(TimeoutError):
                generate_video(client, temp, {"prompt": "x"})
            with self.assertRaises(RuntimeError):
                generate_video(client, temp, {"prompt": "x"})
            self.assertEqual(client.request.call_count, 1)
            self.assertEqual(read_json(Path(temp) / "generation.job.json")["status"], "submission_uncertain")

    def test_changed_parameters_cannot_reuse_paid_job(self):
        with tempfile.TemporaryDirectory() as temp:
            write_json(Path(temp) / "generation.request.json", {"prompt": "first"})
            client = Mock()
            with self.assertRaises(ValueError):
                generate_video(client, temp, {"prompt": "different"})
            client.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
