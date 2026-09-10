"""Prompt exports contain only validated public cases and never hidden answers."""

import json
import tempfile
import unittest
from pathlib import Path

from export_prompts import export_collection
from generate_core_v3 import prepare
from test_core_v3 import mock_constructor
from worldline.artifacts import write_pipeline_result
from worldline.core_v3 import plan_mixed_core
from worldline.pipeline import PipelineOptions, build_prompt_pipeline


class PromptExportTest(unittest.TestCase):
    def test_incomplete_collection_cannot_be_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare(root, "3.1")
            with self.assertRaisesRegex(ValueError, "incomplete or invalid"):
                export_collection(root)
            self.assertFalse((root / "public_prompts.json").exists())

    def test_export_keeps_exact_public_shots_and_requires_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for case in plan_mixed_core("3.1"):
                result = build_prompt_pipeline(PipelineOptions(episode_id=case["id"], task=case["task"],
                    layout=case["layout"], shot_count=case["shot_count"], source_id=case["source_id"]),
                    request_structured=mock_constructor(case, []), environ={})
                write_pipeline_result(result, root)
            prepare(root, "3.1")
            paths = export_collection(root)
            data = json.loads(paths[0].read_text())
            self.assertEqual(data["case_count"], 112)
            self.assertEqual(len(data["cases"]), 112)
            self.assertEqual(paths[1].read_text().count("```text"), 112)
            for case in data["cases"]:
                self.assertEqual(set(case), {"id", "task_type", "scene", "subject_count", "viewpoint_mode", "shots"})
                original = json.loads((root / case["id"] / "prompt.public.json").read_text())
                self.assertEqual(case["shots"], original["shots"])
                self.assertIn((root / case["id"] / "prompt.txt").read_text().strip(), paths[1].read_text())
            with self.assertRaises(FileExistsError):
                export_collection(root)


if __name__ == "__main__":
    unittest.main()
