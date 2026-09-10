"""Calibration never fills human labels or accepts mismatched evidence."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worldline.annotations import digest
from worldline.calibration import (compare_labels, load_item, observation_template,
                                  packet_hash, prepare_packet, review_html)
from worldline.video import read_json, write_json

BASE = Path(__file__).resolve().parents[1]


class CalibrationTest(unittest.TestCase):
    def make_packet(self, root):
        source = root / "source"
        case_id = "PRIVATE-TASK-EXIT"
        folder = source / case_id
        fixture = BASE / "tests/fixtures/calibration"
        for name in ("episode.internal.json", "annotations.hidden.json"):
            write_json(folder / "input" / name, read_json(fixture / name))
        (folder / "video.mp4").write_bytes(b"offline video fixture")
        write_json(folder / "alignment.json", {"uncertain": False, "shots": [
            {"index": i + 1, "start": 3.0 * i, "end": 3.0 * (i + 1)} for i in range(3)]})
        write_json(source / "manifest.json", {"cases": [{"id": case_id}]})
        output = root / "packet"

        def fake_frame(video, seconds, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("fixture " + str(seconds)).encode())
            from worldline.video import file_hash
            return {"path": str(path), "time": seconds, "sha256": file_hash(path)}

        with patch("worldline.calibration.extract_frame", fake_frame):
            manifest = prepare_packet(source, output)
        return output, manifest

    def test_packet_uses_two_new_readout_times_and_no_answers_in_blind_files(self):
        with tempfile.TemporaryDirectory() as d:
            root, manifest = self.make_packet(Path(d))
            item = manifest["items"][0]
            folder, context, frames = load_item(root, item)
            self.assertEqual([f["time"] for f in frames if f["role"] == "readout"], [6.75, 8.25])
            self.assertEqual(len([f for f in frames if f["role"] == "anchor"]), 3)
            self.assertEqual(item["input_sha256"], packet_hash(context, frames))
            for name in ("context.json", "review.html", "human.template.json"):
                text = (folder / name).read_text()
                for forbidden in ("PRIVATE-TASK-EXIT", "expected_count", "expected_occupants", '"task"'):
                    self.assertNotIn(forbidden, text)
            self.assertFalse(compare_labels(root)["complete"])
            self.assertIsNone(compare_labels(root)["score_agreement"]["Valid"]["rate"])
            self.assertFalse(list((root / "human").glob("*.json")))
            with self.assertRaises(FileExistsError):
                prepare_packet(Path(d) / "source", root)

    def test_image_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root, manifest = self.make_packet(Path(d))
            item = manifest["items"][0]
            folder, _, frames = load_item(root, item)
            (folder / frames[-1]["path"]).write_bytes(b"changed fixture")
            with self.assertRaises(ValueError):
                load_item(root, item)

    def test_score_agreement_does_not_mask_different_wrong_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root, manifest = self.make_packet(Path(d))
            item = manifest["items"][0]
            _, context, frames = load_item(root, item)
            human = observation_template(context, frames)
            for anchor in human["anchors"]:
                anchor.update(reliable=True, evidence="fixture")
            for frame in human["frames"]:
                frame.update(view_compliant=True, readable=True, count=5, evidence="fixture")
                frame["occupants"] = {seat: None for seat in context["seats"]}
            judge = copy.deepcopy(human)
            for frame in judge["frames"]:
                frame["count"] = 6
            for directory, suffix, value in (("human", "human", human), ("judge-results", "judge", judge)):
                write_json(root / directory / (item["id"] + "." + suffix + ".json"),
                           {"item": item["id"], "input_sha256": item["input_sha256"], "observation": value})
            report = compare_labels(root)
            self.assertTrue(report["complete"])
            self.assertEqual(report["score_agreement"]["Count"]["rate"], 1)
            self.assertEqual(report["observation_agreement"]["count"]["rate"], 0)
            self.assertFalse(report["release_ready"])
            target = root / "private" / (item["id"] + ".annotations.json")
            changed = read_json(target)
            changed["observations"][-1]["expected_count"] = 5
            write_json(target, changed)
            with self.assertRaises(ValueError):
                compare_labels(root)

    def test_unfilled_human_template_cannot_be_scored(self):
        with tempfile.TemporaryDirectory() as d:
            root, manifest = self.make_packet(Path(d))
            item = manifest["items"][0]
            folder, context, frames = load_item(root, item)
            value = read_json(folder / "human.template.json")
            for sub, suffix in (("human", "human"), ("judge-results", "judge")):
                write_json(root / sub / (item["id"] + "." + suffix + ".json"), value)
            with self.assertRaises(ValueError):
                compare_labels(root)


if __name__ == "__main__":
    unittest.main()
