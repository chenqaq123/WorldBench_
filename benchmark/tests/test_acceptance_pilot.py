import unittest
from collections import Counter

from acceptance_pilot import select_cases
from worldline.pipeline import _auditor_system, _beat_planner_system


class AcceptancePilotTests(unittest.TestCase):
    def test_predeclared_balanced_subset(self):
        cases = select_cases()
        self.assertEqual(cases, select_cases())
        self.assertEqual(len({c['id'] for c in cases}), 16)
        self.assertEqual(len({(c['task'], c['viewpoint_mode'], c['subject_count']) for c in cases}), 16)
        self.assertEqual(Counter(c['shot_count'] for c in cases), {3: 8, 4: 8})
        self.assertEqual(Counter(c['subject_count'] for c in cases), {3: 8, 4: 8})
        self.assertEqual(len({c['scene'] for c in cases}), 7)

    def test_audit_allows_area_but_not_answer_landmarks(self):
        text = _auditor_system({'dataset_version': '3.1'})
        self.assertIn('NOT a forbidden landmark', text)
        self.assertIn('Reject required shelf/window/seat-coverage lists', text)
        self.assertIn('shared generic keyword alone', text)
        self.assertIn('closest ordinary equivalent', _beat_planner_system({'shot_count': 3}))


if __name__ == '__main__':
    unittest.main()
