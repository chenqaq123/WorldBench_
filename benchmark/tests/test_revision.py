"""Regression checks for experimental validity, not merely generated wording."""

import copy
from collections import Counter, defaultdict
import unittest

from worldline.annotations import build_annotations, score_wide_observation
from worldline.balance import casting_contract
from worldline.layouts import get_layout_template
from worldline.matrix import plan_core_matrix
from worldline.pipeline import build_shot_contracts, compile_episode, entry_content_prefix, validate_prompt, attach_prompt
from worldline.sources import load_catalog, select_source


class RevisionTest(unittest.TestCase):
    def test_roles_are_balanced_per_task_and_camera_pairs_share_anchors(self):
        counts, pairs, colors = defaultdict(Counter), {}, defaultdict(Counter)
        for config in plan_core_matrix():
            cast = casting_contract(config)
            key = (config["scene"], config["task"], config["subject_count"])
            self.assertEqual(pairs.setdefault(key, cast), cast)
            for subject in cast:
                counts[(config["task"], subject["id"])][subject["gender"]] += 1
                colors[(config["task"], subject["id"])][subject["clothing"]] += 1
        for (task, role), values in counts.items():
            self.assertLessEqual(abs(values["man"] - values["woman"]), 2 if role == "D" else 0)
        for values in colors.values():
            self.assertEqual(len(set(values.values())), 1)

    def test_all_tasks_score_count_and_all_positions_only_in_final_wide(self):
        for task in ("static_viewpoint_change", "person_entry", "person_exit", "position_swap"):
            config = next(c for c in plan_core_matrix() if c["task"] == task and c["subject_count"] == 3)
            template = get_layout_template(config["layout"])
            contracts = build_shot_contracts(template, 3, task)
            episode = compile_episode("test", task, template, {"subjects": casting_contract(config)},
                {"shots": [{"index": c["index"], "beat": ""} for c in contracts]}, contracts)
            annotations = build_annotations(episode, template, select_source(config))
            self.assertEqual([a["shot"] for a in annotations["observations"]], [1, 3])
            final = annotations["observations"][-1]
            occupants = final["expected_occupants"]
            perfect = dict(observed_count=final["expected_count"], observed_occupants=occupants, view_compliant=True)
            self.assertTrue(score_wide_observation(final, **perfect)["joint_success"])
            wrong = dict(occupants)
            seats = list(wrong)
            wrong[seats[0]], wrong[seats[-1]] = wrong[seats[-1]], wrong[seats[0]]
            result = score_wide_observation(final, **{**perfect, "observed_occupants": wrong})
            self.assertTrue(result["count_correct"])
            self.assertFalse(result["position_correct"])
            self.assertFalse(result["joint_success"])
            result = score_wide_observation(final, **{**perfect, "observed_count": 99})
            self.assertFalse(result["count_correct"])
            self.assertFalse(result["joint_success"])
            self.assertIsNone(score_wide_observation(final, **{**perfect, "view_compliant": False})["position_correct"])
            if task == "position_swap":
                self.assertIn("C", [q["subject"] for q in final["unmentioned_probes"]])
            if task == "person_entry":
                self.assertEqual(annotations["identity_anchor_shots"]["B"], 2)

    def test_real_sources_have_verifiable_excerpt_not_template_filler(self):
        sources = load_catalog()
        self.assertEqual(len(sources), 14)
        self.assertEqual(len({s["title"] for s in sources}), 6)
        for source in sources:
            self.assertTrue(source["excerpt"].startswith(source["start_text"]))
            self.assertGreater(len(source["excerpt"].split()), 100)
            self.assertTrue(source["author"] and source["locator"] and source["excerpt_sha256"])

    def test_arriving_beside_a_seat_does_not_establish_seated_state(self):
        config = next(c for c in plan_core_matrix() if c["task"] == "person_entry" and c["subject_count"] == 3)
        template = get_layout_template(config["layout"])
        contracts = build_shot_contracts(template, 3, config["task"])
        episode = compile_episode("test", config["task"], template, {"subjects": casting_contract(config)},
            {"shots": [{"index": c["index"], "beat": ""} for c in contracts]}, contracts)
        b = episode["subjects"][1]
        contents = {"shots": [{"content": "placeholder"}, {"content": b["appearance"].capitalize() + " arrives at " + template["seats"][b["seat"]] + "."}, {"content": "placeholder"}]}
        errors = validate_prompt(attach_prompt(episode, contents, template))
        self.assertTrue(any("explicit arrival and seating" in error for error in errors))
        contents["shots"][1]["content"] = entry_content_prefix(b, template)
        self.assertFalse(any("explicit arrival and seating" in error for error in validate_prompt(attach_prompt(episode, contents, template))))
