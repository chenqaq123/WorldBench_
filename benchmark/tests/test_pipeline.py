"""Tests for the standalone Python WorldLine constructor."""

import copy
import re
import unittest
from worldline.balance import casting_contract

from worldline.layouts import get_layout_template, layout_template_ids
from worldline.matrix import plan_core_matrix
from worldline.pipeline import (
    PipelineOptions,
    attach_prompt,
    build_prompt_pipeline,
    build_shot_contracts,
    case_signature,
    compile_episode,
    expected_visible_subjects,
    positions_by_shot,
    probe_expectations_for_shot,
    probe_subjects_for_shot,
    public_prompt,
    render_public_prompt,
    validate_beat_plan,
    validate_casting,
    validate_compiled_episode,
    validate_layout_template,
    validate_prompt,
    validate_unique_case_signatures,
)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.template = get_layout_template("cafe_rect_table_3_v1")
        self.config = {
            "task": "static_viewpoint_change",
            "subject_count": 3,
            "shot_count": 3,
        }
        self.contracts = build_shot_contracts(self.template, 3)
        self.casting = {
            "subjects": [
                {
                    "id": "A",
                    "gender": "woman",
                    "clothing": "mustard-yellow cardigan",
                },
                {
                    "id": "B",
                    "gender": "man",
                    "clothing": "forest-green jacket",
                },
                {
                    "id": "C",
                    "gender": "woman",
                    "clothing": "cobalt-blue shirt",
                },
            ]
        }
        self.beat_plan = {
            "shots": [
                {
                    "index": 1,
                    "beat": "Subject A begins a story.",
                    "events": [],
                },
                {
                    "index": 2,
                    "beat": "Subject B asks a question and Subject A answers.",
                    "events": [],
                },
                {
                    "index": 3,
                    "beat": "Subject A finishes the story and Subject B replies.",
                    "events": [],
                },
            ]
        }
        self.content_prompt = {
            "shots": [
                {
                    "index": 1,
                    "content": (
                        self.template["public_intro"]
                        + " A woman in a mustard-yellow cardigan "
                        "sits in the plant-side window seat, a man in a forest-green jacket "
                        "sits in the counter-side window seat, and a woman in a cobalt-blue "
                        "shirt sits in the plant-end seat."
                    ),
                },
                {
                    "index": 2,
                    "content": (
                        "The man in the forest-green jacket asks a question, and the woman "
                        "in the mustard-yellow cardigan answers."
                    ),
                },
                {
                    "index": 3,
                    "content": (
                        "The woman in the mustard-yellow cardigan finishes the story, and "
                        "the man in the forest-green jacket replies."
                    ),
                },
            ]
        }
        self.episode = compile_episode(
            "WL-PY-TEST-001",
            self.config["task"],
            self.template,
            self.casting,
            self.beat_plan,
            self.contracts,
        )
        self.completed = attach_prompt(
            self.episode, self.content_prompt, self.template
        )

    def test_layout_and_contracts_are_deterministic(self):
        self.assertEqual(validate_layout_template(self.template), [])
        self.assertEqual(
            self.contracts,
            [
                {
                    "index": 1,
                    "mentioned": ["A", "B", "C"],
                    "camera": "establish_counter_end",
                    "events": [],
                },
                {
                    "index": 2,
                    "mentioned": ["A", "B"],
                    "camera": "partial_window_pair",
                    "events": [],
                },
                {
                    "index": 3,
                    "mentioned": ["A", "B"],
                    "camera": "probe_plant_end",
                    "events": [],
                },
            ],
        )
        self.assertEqual(validate_casting(self.casting, self.config), [])
        self.assertEqual(
            validate_beat_plan(self.beat_plan, self.config, self.contracts), []
        )
        self.assertEqual(validate_compiled_episode(self.episode, self.template), [])

    def test_only_wide_observation_views_carry_spatial_coverage(self):
        cameras = self.template["cameras"]
        self.assertIn(
            "all three seats in frame",
            cameras["establish_counter_end"]["public_view"],
        )
        self.assertEqual(
            cameras["partial_window_pair"]["public_view"],
            "Medium two-shot from the aisle side, centered on the two adjacent "
            "window-side seats.",
        )
        self.assertIn("plant-end seat", cameras["probe_plant_end"]["public_view"])
        self.assertEqual(
            cameras["establish_counter_end"]["view_direction"],
            "counter_to_plant",
        )
        self.assertEqual(
            cameras["probe_plant_end"]["view_direction"],
            "plant_to_counter",
        )
        self.assertTrue(
            cameras["establish_counter_end"]["public_view"].startswith(
                "Wide establishing shot"
            )
        )
        self.assertTrue(
            cameras["probe_plant_end"]["public_view"].startswith(
                "Reverse wide shot"
            )
        )
        for camera in cameras.values():
            self.assertIsNone(
                re.search(
                    r"\d+\s*mm|meters? high|eye level|optical axis|frame edges|outer shoulders",
                    camera["public_view"],
                    re.IGNORECASE,
                )
            )

    def test_wide_reobservation_requires_strong_direction_change(self):
        invalid = copy.deepcopy(self.template)
        invalid["cameras"]["probe_plant_end"]["view_direction"] = (
            "counter_to_plant"
        )
        self.assertTrue(
            any(
                "reverse the landmark-to-landmark axis" in error
                for error in validate_layout_template(invalid)
            )
        )

    def test_overhead_reobservation_is_a_valid_distinct_viewpoint_mode(self):
        overhead = get_layout_template("cafe_rect_table_3_overhead_v1")
        self.assertEqual(validate_layout_template(overhead), [])
        probe = overhead["cameras"][overhead["grammar"]["probe_camera"]]
        self.assertEqual(probe["view_direction"], "overhead")
        self.assertTrue(probe["public_view"].startswith("Top-down wide shot"))

    def test_complete_scene_catalog_and_core_matrix(self):
        layout_ids = layout_template_ids()
        self.assertEqual(len(layout_ids), 28)
        scenes = {}
        for layout_id in layout_ids:
            template = get_layout_template(layout_id)
            self.assertEqual(validate_layout_template(template), [])
            scenes.setdefault(template["scene_type"], []).append(template)
            for task in (
                "static_viewpoint_change",
                "person_entry",
                "person_exit",
                "position_swap",
            ):
                for shot_count in (3, 5, 7):
                    contracts = build_shot_contracts(
                        template, shot_count, task
                    )
                    self.assertEqual(len(contracts), shot_count)
        self.assertEqual(
            set(scenes),
            {
                "café",
                "meeting room",
                "living room",
                "dining room",
                "seminar room",
                "game room",
                "kitchen",
            },
        )
        self.assertTrue(all(len(templates) == 4 for templates in scenes.values()))

        matrix = plan_core_matrix()
        self.assertEqual(len(matrix), 112)
        self.assertEqual(len({case["id"] for case in matrix}), 112)
        self.assertEqual(
            validate_unique_case_signatures(
                [case["case_signature"] for case in matrix]
            ),
            [],
        )
        extended_matrix = plan_core_matrix(shot_counts=(3, 5, 7))
        self.assertEqual(len(extended_matrix), 336)
        self.assertEqual(len({case["id"] for case in extended_matrix}), 336)

    def test_four_subject_dynamic_contracts_preserve_non_targets(self):
        template = get_layout_template("meeting_room_table_4_v1")
        entry = build_shot_contracts(template, 3, "person_entry")
        exit_case = build_shot_contracts(template, 3, "person_exit")
        swap = build_shot_contracts(template, 3, "position_swap")
        self.assertEqual(entry[0]["mentioned"], ["A", "C", "D"])
        self.assertEqual(entry[-1]["mentioned"], ["A", "D"])
        self.assertEqual(exit_case[-1]["mentioned"], ["A", "D"])
        self.assertEqual(swap[-1]["mentioned"], ["A"])
        long_exit = build_shot_contracts(template, 7, "person_exit")
        for contract in long_exit[2:-1]:
            camera = template["cameras"][contract["camera"]]
            if camera["framing"] == "two_shot":
                self.assertEqual(len(contract["mentioned"]), 2)
            if camera["framing"] == "close_up":
                self.assertEqual(len(contract["mentioned"]), 1)

    def test_case_signature_ignores_wording_but_requires_dimension_change(self):
        reverse = case_signature(
            {
                "task": "static_viewpoint_change",
                "scene": "café",
                "viewpoint_mode": "reverse_axis",
                "subject_count": 3,
                "shot_count": 3,
            }
        )
        duplicate = copy.deepcopy(reverse)
        overhead = {**reverse, "viewpoint_mode": "overhead"}
        longer = {**reverse, "shot_count": 5}
        self.assertTrue(validate_unique_case_signatures([reverse, duplicate]))
        self.assertEqual(
            validate_unique_case_signatures([reverse, overhead, longer]), []
        )

    def test_casting_cannot_silently_swap_fixed_seats(self):
        invalid = copy.deepcopy(self.casting)
        invalid["subjects"][0], invalid["subjects"][1] = (
            invalid["subjects"][1],
            invalid["subjects"][0],
        )
        self.assertTrue(
            any(
                "seat-assignment order" in error
                for error in validate_casting(invalid, self.config)
            )
        )

    def test_opening_beat_uses_one_story_actor(self):
        invalid = copy.deepcopy(self.beat_plan)
        invalid["shots"][0]["beat"] = (
            "Subject A begins a story and Subject B asks for context."
        )
        self.assertTrue(
            any(
                "only to Subject A" in error
                for error in validate_beat_plan(invalid, self.config, self.contracts)
            )
        )

    def test_five_llm_stages_are_independent_requests(self):
        calls = []
        prompt_rendering_input = {}
        values = {
            "source_abstraction": {
                "source_id": "alice_riddle",
                "archetype": "café conversation",
                "premise": "Participants debate a riddle with no answer.",
                "interaction_arc": (
                    "The group settles in, an anecdote prompts a response, and the "
                    "exchange ends on a shared light note."
                ),
            },
            "subject_casting": self.casting,
            "story_planning": self.beat_plan,
            "prompt_rendering": self.content_prompt,
            "prompt_audit": {"passed": True, "issues": []},
        }

        def request_structured(**request):
            stage = request["stage"]
            calls.append(stage)
            if stage == "prompt_rendering":
                prompt_rendering_input.update(request["input_value"])
            request["trace"].append(
                {
                    "stage": stage,
                    "request_model": request["model"],
                    "response_model": "mock",
                    "response_id": None,
                    "usage": None,
                }
            )
            if stage == "subject_casting":
                return {"subjects": request["input_value"]["casting_contract"]}
            if stage == "story_planning":
                value = copy.deepcopy(self.beat_plan)
                value["shots"][0]["beat"] = "Subject A asks a riddle."
                return value
            if stage == "prompt_rendering":
                subjects = request["input_value"]["subjects"]
                anchors = [subject["appearance"] for subject in subjects]
                return {"shots": [
                    {"index": 1, "content": self.template["public_intro"] + " " + ", ".join(
                        anchor.capitalize() + " sits in " + self.template["seats"][subject["seat"]]
                        for anchor, subject in zip(anchors, subjects)) + "."},
                    {"index": 2, "content": anchors[0].capitalize() + " asks a riddle and " + anchors[1] + " answers."},
                    {"index": 3, "content": anchors[0].capitalize() + " explains the riddle and " + anchors[1] + " replies."},
                ]}
            return copy.deepcopy(values[stage])

        result = build_prompt_pipeline(
            PipelineOptions(episode_id="WL-PY-STAGE-TEST-001"),
            request_structured=request_structured,
            environ={},
        )
        expected = [
            "source_abstraction",
            "subject_casting",
            "story_planning",
            "prompt_rendering",
            "prompt_audit",
        ]
        self.assertEqual(calls, expected)
        self.assertEqual(list(result["run"]["stage_outputs"]), expected)
        self.assertEqual(len(result["run"]["trace"]), 5)
        self.assertEqual(validate_prompt(result["episode"]), [])
        self.assertEqual(
            prompt_rendering_input["layout"]["public_intro"],
            self.template["public_intro"],
        )

    def test_visibility_and_probe_follow_geometry(self):
        self.assertEqual(
            expected_visible_subjects(self.episode, self.template, 1), ["A", "B", "C"]
        )
        self.assertEqual(
            expected_visible_subjects(self.episode, self.template, 2), ["A", "B"]
        )
        self.assertEqual(
            expected_visible_subjects(self.episode, self.template, 3), ["A", "B", "C"]
        )
        self.assertEqual(probe_subjects_for_shot(self.episode, self.template, 1), [])
        self.assertEqual(probe_subjects_for_shot(self.episode, self.template, 2), [])
        self.assertEqual(
            probe_subjects_for_shot(self.episode, self.template, 3), ["C"]
        )

    def test_entry_exit_and_swap_have_deterministic_state_probes(self):
        cases = {
            "person_entry": {
                "event": {"subject": "B", "action": "enter"},
                "opening_mentions": ["A", "C"],
                "final_mentions": ["A"],
                "probe": [
                    {"subject": "B", "present": True, "seat": "window_right"},
                    {"subject": "C", "present": True, "seat": "table_left_end"},
                ],
            },
            "person_exit": {
                "event": {"subject": "B", "action": "exit"},
                "opening_mentions": ["A", "B", "C"],
                "final_mentions": ["A"],
                "probe": [
                    {"subject": "B", "present": False, "seat": None},
                    {"subject": "C", "present": True, "seat": "table_left_end"},
                ],
            },
            "position_swap": {
                "event": {
                    "subject": "A",
                    "action": "swap",
                    "with_subject": "B",
                },
                "opening_mentions": ["A", "B", "C"],
                "final_mentions": ["A"],
                "probe": [
                    {"subject": "B", "present": True, "seat": "window_left"},
                    {"subject": "C", "present": True, "seat": "table_left_end"},
                ],
            },
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                config = {**self.config, "task": task}
                contracts = build_shot_contracts(self.template, 3, task)
                beat_plan = {
                    "shots": [
                        {
                            "index": 1,
                            "beat": "Subject A begins a story.",
                            "events": [],
                        },
                        {
                            "index": 2,
                            "beat": {
                                "person_entry": (
                                    "Subject B enters and takes the counter-side window seat "
                                    "while Subject A continues."
                                ),
                                "person_exit": (
                                    "Subject B leaves the counter-side window seat and exits."
                                ),
                                "position_swap": (
                                    "Subject A and Subject B exchange their window-side seats."
                                ),
                            }[task],
                            "events": [expected["event"]],
                        },
                        {
                            "index": 3,
                            "beat": {
                                "person_entry": "Subject A continues the story.",
                                "person_exit": "Subject A continues the story.",
                                "position_swap": "Subject A asks a question.",
                            }[task],
                            "events": [],
                        },
                    ]
                }
                self.assertEqual(contracts[0]["mentioned"], expected["opening_mentions"])
                self.assertEqual(contracts[1]["events"], [expected["event"]])
                self.assertEqual(contracts[2]["mentioned"], expected["final_mentions"])
                self.assertEqual(validate_beat_plan(beat_plan, config, contracts), [])
                episode = compile_episode(
                    "WL-PY-DYNAMIC-TEST",
                    task,
                    self.template,
                    self.casting,
                    beat_plan,
                    contracts,
                )
                self.assertEqual(validate_compiled_episode(episode, self.template), [])
                self.assertEqual(
                    probe_expectations_for_shot(episode, self.template, 3),
                    expected["probe"],
                )
                if task == "position_swap":
                    self.assertEqual(
                        positions_by_shot(episode)[-1],
                        {
                            "A": "window_right",
                            "B": "window_left",
                            "C": "table_left_end",
                        },
                    )

    def test_prompt_accepts_unmentioned_but_visible_probe(self):
        self.assertEqual(validate_prompt(self.completed), [])
        self.assertNotIn("cobalt", self.completed["shots"][2]["prompt"]["content"])
        self.assertIn("plant-end seat", self.completed["shots"][2]["prompt"]["viewpoint"])

    def test_prompt_rejects_leakage_and_duration(self):
        invalid = copy.deepcopy(self.completed)
        invalid["shots"][2]["prompt"]["content"] = (
            "The woman in the cobalt-blue shirt remains beside the others for 5 seconds."
        )
        errors = validate_prompt(invalid)
        self.assertTrue(any("uncontracted subject C" in error for error in errors))
        self.assertTrue(any("Duration language" in error for error in errors))

    def test_prompt_rejects_hair_or_accessory_identity_details(self):
        invalid = copy.deepcopy(self.completed)
        invalid["shots"][1]["prompt"]["content"] += " He adjusts his glasses."
        self.assertTrue(
            any(
                "hair or accessories" in error
                for error in validate_prompt(invalid)
            )
        )

    def test_prompt_rejects_decorative_performance_details(self):
        invalid = copy.deepcopy(self.completed)
        invalid["shots"][1]["prompt"]["content"] += (
            " He leans forward with an intrigued smile over his mug."
        )
        self.assertTrue(
            any(
                "decorative posture" in error
                for error in validate_prompt(invalid)
            )
        )

    def test_prompt_rejects_repeated_identity_anchor(self):
        invalid = copy.deepcopy(self.completed)
        invalid["shots"][0]["prompt"]["content"] += (
            " The woman in the mustard-yellow cardigan begins a story."
        )
        self.assertTrue(
            any(
                "repeats subject A's identity anchor" in error
                for error in validate_prompt(invalid)
            )
        )

    def test_prompt_rejects_internal_line_breaks(self):
        invalid = copy.deepcopy(self.completed)
        invalid["shots"][1]["prompt"]["content"] += "\nA second line."
        self.assertTrue(
            any(
                "Content must be a single line" in error
                for error in validate_prompt(invalid)
            )
        )

    def test_prompt_rejects_missing_opening_seat_assignment(self):
        invalid = copy.deepcopy(self.completed)
        invalid["shots"][0]["prompt"]["content"] = (
            "A woman in a mustard-yellow cardigan begins a story, a man in a "
            "forest-green jacket asks a question, and a woman in a cobalt-blue "
            "shirt replies."
        )
        errors = validate_prompt(invalid)
        self.assertTrue(any("exact compact seat label" in error for error in errors))

    def test_prompt_requires_scene_intro_before_people(self):
        invalid = copy.deepcopy(self.completed)
        intro = self.template["public_intro"]
        content = invalid["shots"][0]["prompt"]["content"]
        invalid["shots"][0]["prompt"]["content"] = (
            content[len(intro):].strip() + " " + intro
        )
        self.assertTrue(
            any(
                "before introducing any subjects" in error
                for error in validate_prompt(invalid)
            )
        )

    def test_public_render_uses_one_line_per_shot(self):
        value = public_prompt(self.completed)
        text = render_public_prompt(value)
        lines = text.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("Shot 1: Wide establishing shot"))
        self.assertIn(self.content_prompt["shots"][0]["content"], lines[0])
        self.assertTrue(lines[1].startswith("Shot 2: Medium two-shot"))
        self.assertTrue(lines[2].startswith("Shot 3: Reverse wide shot"))
        self.assertNotIn("Content:", text)
        self.assertNotIn("Viewpoint:", text)
        self.assertNotRegex(text, r"mentioned|expected_visible|probe|events")


if __name__ == "__main__":
    unittest.main()
