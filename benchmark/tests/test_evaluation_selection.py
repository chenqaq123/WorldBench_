"""A new dataset or full-matrix request must not silently resume an old pilot."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from run_evaluation import prepare
from worldline.video import write_json


class EvaluationSelectionTest(unittest.TestCase):
    def options(self, root):
        return SimpleNamespace(
            output=root / "evaluation", dataset=root / "dataset", model="test-model",
            seconds_per_shot=3, resolution="480p", seed=42, judge="test-judge",
            case_id=None, all_cases=True, phase="plan",
        )

    def test_pending_v3_plan_cannot_be_submitted(self):
        with tempfile.TemporaryDirectory() as d:
            args = self.options(Path(d))
            write_json(args.dataset / "core_matrix.manifest.json",
                       {"version": "3.0", "cases": [{"id": "case-a", "status": "pending"}]})
            with self.assertRaisesRegex(ValueError, "Not a complete"):
                prepare(args)
            self.assertFalse(args.output.exists())

    def test_changed_dataset_or_all_case_selection_cannot_resume_subset(self):
        with tempfile.TemporaryDirectory() as d:
            args = self.options(Path(d))
            write_json(args.dataset / "core_matrix.manifest.json",
                       {"cases": [{"id": "case-a"}, {"id": "case-b"}]})
            path = args.output / "manifest.json"
            write_json(path, {"dataset": str(args.dataset), "cases": [{"id": "case-a"}]})
            with self.assertRaisesRegex(ValueError, "All-case selection"):
                prepare(args)
            write_json(path, {"dataset": str(Path(d) / "different-dataset"), "cases": []})
            with self.assertRaisesRegex(ValueError, "Dataset differs"):
                prepare(args)


if __name__ == "__main__":
    unittest.main()
