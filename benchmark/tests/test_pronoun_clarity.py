"""Regression coverage for ambiguous dialogue roles without banning clear pronouns."""

import copy
import unittest

from test_core_v3 import mock_constructor
from worldline.core_v3 import plan_mixed_core
from worldline.pipeline import (PipelineOptions, build_prompt_pipeline, validate_prompt,
                                ambiguous_dialogue_pronouns, _renderer_system, _auditor_system)

SUBJECTS = [
    {"id": "A", "gender": "man", "clothing": "purple shirt"},
    {"id": "B", "gender": "man", "clothing": "red shirt"},
    {"id": "C", "gender": "woman", "clothing": "white shirt"},
    {"id": "D", "gender": "woman", "clothing": "blue shirt"},
]


class PronounClarityTest(unittest.TestCase):
    def test_rejects_speaker_pronouns_after_two_same_gender_identities(self):
        examples = [
            "A man in a purple shirt and a man in a red shirt exchange seats, and he asks him to help.",
            "A man in a red shirt enters. A man in a purple shirt asks a question, and he answers.",
            "A woman in a blue shirt enters. A woman in a white shirt asks a question, and she replies.",
            "A woman in a white shirt and a woman in a blue shirt exchange seats and she asks about the story.",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(len(ambiguous_dialogue_pronouns(text, SUBJECTS)), 1)

    def test_keeps_clear_pronouns_and_uniquely_bound_references(self):
        examples = [
            "A man in a red shirt enters. He asks about the case, and a man in a purple shirt replies.",
            "A man in a red shirt leaves his seat, while a man in a purple shirt asks a question.",
            "A woman in a blue shirt leaves her seat, while a woman in a white shirt replies.",
            "A man in a red shirt claims he can solve the riddle, and a man in a purple shirt listens.",
            "A man in a purple shirt and a woman in a white shirt exchange seats, and she asks him to help.",
            "A man in a purple shirt and a man in a red shirt exchange seats; the former asks the latter to help.",
            "A man in a red shirt enters. A man in a purple shirt asks a question, and the newcomer answers.",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(ambiguous_dialogue_pronouns(text, SUBJECTS), [])

    def test_full_v31_validation_rejects_ambiguity_and_accepts_clarification(self):
        case = next(c for c in plan_mixed_core("3.1") if c["id"] == "WL-CORE-MEETING-SWAP-4P-REV-3S")
        result = build_prompt_pipeline(PipelineOptions(episode_id=case["id"], task=case["task"],
            layout=case["layout"], shot_count=case["shot_count"], source_id=case["source_id"]),
            request_structured=mock_constructor(case, []), environ={})
        episode = copy.deepcopy(result["episode"])
        episode["shots"][1]["prompt"]["content"] = (
            "A man in a purple shirt and a man in a red shirt exchange seats, and he asks him to help review the case.")
        errors = validate_prompt(episode)
        self.assertTrue(any("ambiguous dialogue pronoun" in error for error in errors))
        episode["shots"][1]["prompt"]["content"] = episode["shots"][1]["prompt"]["content"].replace(
            "he asks him", "the former asks the latter")
        self.assertEqual(validate_prompt(episode), [])

    def test_renderer_and_auditor_share_the_clarity_rule(self):
        config = {"dataset_version": "3.1", "task": "person_entry", "shot_count": 3}
        for system in (_renderer_system(config), _auditor_system(config)):
            self.assertIn("the newcomer uniquely refers", system)
            self.assertIn("Do not repeat identity anchors", system)
            self.assertIn("intended subject in the approved beat", system)


if __name__ == "__main__":
    unittest.main()
