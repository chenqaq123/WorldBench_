"""Offline guards for the requested single Sol judge and image-only sequence path."""

import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from run_evaluation import DEFAULT_JUDGE, judge_settings, preflight_judge
from worldline.evaluation import READOUT_FRACTIONS, write_report
from worldline.judge import align_video, diagnose, evaluate_video, sequence_evidence
from worldline.video import read_json, write_json
from test_evaluation import annotation, observation


class SingleJudgeTests(unittest.TestCase):
    def test_settings_have_no_replication_or_adjudicator(self):
        settings = judge_settings(DEFAULT_JUDGE)
        self.assertEqual(settings["primary"], "openai/gpt-5.6-sol")
        self.assertEqual(settings["mode"], "single")
        self.assertEqual(settings["readout_fractions"], [0.25, 0.75])
        self.assertIsNone(settings["temperature"])
        self.assertFalse({"secondary", "alignment", "adjudicator"} & set(settings))

    def test_preflight_exact_model_and_image_capabilities(self):
        with tempfile.TemporaryDirectory() as temp:
            client = Mock()
            client.request.return_value = {"data": [{"id": DEFAULT_JUDGE,
                "architecture": {"input_modalities": ["image", "text"]},
                "supported_parameters": ["max_tokens", "response_format", "structured_outputs"]}]}
            preflight_judge(client, temp, judge_settings(DEFAULT_JUDGE))
            preflight_judge(client, temp, judge_settings(DEFAULT_JUDGE))
            client.request.assert_called_once_with("/models")
            with self.assertRaises(ValueError):
                preflight_judge(client, temp, judge_settings("different-model"))

    def test_sequence_evidence_is_chronological_images_only(self):
        with tempfile.TemporaryDirectory() as temp:
            overview = [{"path": "late.jpg", "time": 2.25, "label": "overview", "sha256": "x"},
                        {"path": "early.jpg", "time": 0.25, "label": "overview", "sha256": "y"}]
            cuts = {"segments": [{"index": 1, "start": 0, "end": 3}]}
            with patch("worldline.judge.prepare_overview", return_value=overview), patch(
                    "worldline.judge.extract_frame", return_value={"path": "mid.jpg", "time": 1.5, "sha256": "z"}):
                media = sequence_evidence(temp, Path(temp)/"video.mp4", cuts)
            self.assertEqual([m["path"] for m in media], ["early.jpg", "mid.jpg", "late.jpg"])
            self.assertTrue(all(m["kind"] == "image" for m in media))

    def test_one_blind_observer_no_review_and_diagnostics_do_not_change_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/"video.mp4").touch()
            write_json(root/"input/episode.internal.json", {})
            write_json(root/"input/annotations.hidden.json", annotation())
            frames = [{"label": "readout_"+str(i), "time": t, "shot": 3, "role": "readout", "path": "image.jpg"}
                      for i,t in enumerate(READOUT_FRACTIONS, 1)]
            context = {"seats": {"near": "near", "far": "far", "end": "end"},
                       "identity_references": [{"id": s} for s in "ABC"]}
            diagnostics = {"uncertain": True, "event_fidelity": False}
            with patch("worldline.judge.align_video", return_value={"uncertain": False}), patch(
                    "worldline.judge.build_evidence", return_value=frames), patch(
                    "worldline.judge.blind_context", return_value=context), patch(
                    "worldline.judge.judge_call", return_value=observation()) as call, patch(
                    "worldline.judge.diagnose", return_value=diagnostics) as diagnose:
                score = evaluate_video(Mock(), root, judge_settings(DEFAULT_JUDGE))
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[2:4], ("observer_primary", DEFAULT_JUDGE))
            self.assertIsNone(call.call_args.kwargs["temperature"])
            self.assertNotIn("independent_observations", call.call_args.args[5])
            self.assertNotIn("initial_reference", call.call_args.args[5])
            self.assertEqual(diagnose.call_count, 1)
            self.assertTrue(score["joint_success"])
            self.assertFalse(score["strict_trajectory_success"])
            self.assertEqual(read_json(root/"decision.json")["mode"], "single")

    def test_alignment_and_diagnostics_use_sol_images_not_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root/"video.mp4"
            cuts = {"cut_times": [1, 2], "segments": [
                {"index": 1, "start": 0, "end": 1}, {"index": 2, "start": 1, "end": 2},
                {"index": 3, "start": 2, "end": 3}]}
            layout = {"public_intro": "a room", "seats": {"near": "near"},
                      "cameras": {"wide": {"public_view": "Wide", "visible_seats": ["near"]}}}
            episode = {"task": "static_viewpoint_change", "subjects": [{"id": "A", "appearance": "red shirt"}],
                "shots": [{"index": i, "camera": "wide", "prompt": {"content": "test", "viewpoint": "Wide"}} for i in (1,2)]}
            annotations = {"layout": layout, "observations": [{"scored": False}]}
            alignment = {"shots": [{"index": 1, "start": 0, "end": 1, "transition": "opening"},
                                   {"index": 2, "start": 2, "end": 3, "transition": "cut"}],
                         "extra_cuts": True, "uncertain": False, "notes": "extra physical cut"}
            media = [{"kind": "image", "path": "frame.jpg", "label": "0.25s"}]
            with patch("worldline.judge.media_info", return_value={"duration": 3}), patch(
                    "worldline.judge.detect_cuts", return_value=cuts), patch(
                    "worldline.judge.sequence_evidence", return_value=media), patch(
                    "worldline.judge.judge_call", return_value=alignment) as call:
                align_video(Mock(), root, episode, annotations, judge_settings(DEFAULT_JUDGE), video)
                self.assertEqual(call.call_args.args[3], DEFAULT_JUDGE)
                self.assertEqual(call.call_args.args[7], media)
                call.call_args.args[8](alignment)
                call.return_value = {"uncertain": False, "shot_sequence_correct": True}
                result = diagnose(Mock(), root, video, episode, annotations, alignment, judge_settings(DEFAULT_JUDGE))
                self.assertEqual(call.call_args.args[3], DEFAULT_JUDGE)
                self.assertEqual(call.call_args.args[7], media)
                self.assertIn("initial_reference", call.call_args.args[5])
                self.assertFalse(result["shot_sequence_correct"])

    def test_single_report_does_not_claim_review_or_recharge_reused_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root/"case"
            write_json(directory/"input/annotations.hidden.json", annotation())
            (directory/"input/prompt.txt").write_text("Shot 1: test")
            write_json(directory/"generation.job.json", {"usage": {"cost": 1.25}})
            write_json(root/"generation.reuse.json", {"source": "previous"})
            manifest = {"generation": {}, "judge": judge_settings(DEFAULT_JUDGE), "cases": [
                {"id": "case", "task": "person_exit", "scene": "room", "subject_count": 3, "viewpoint_mode": "overhead"}]}
            report = write_report(root, manifest)
            self.assertIsNone(report["observer_agreement"])
            self.assertEqual(report["human_review_cases"], [])
            self.assertEqual(report["cost_usd_reported"]["video"], 0)
            self.assertEqual(report["cost_usd_reported"]["reused_video_historical"], 1.25)
            rendered = (root/"REPORT.md").read_text()
            self.assertNotIn("两位裁判", rendered)
            self.assertNotIn("待人工复核", rendered)
            self.assertIn(DEFAULT_JUDGE, (root/"report.html").read_text())
            self.assertIn("本报告按 2 帧协议评分", (root/"report.html").read_text())
            self.assertIn("Valid（可评测）", (root/"report.html").read_text())


if __name__ == "__main__":
    unittest.main()
