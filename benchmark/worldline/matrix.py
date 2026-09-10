"""Deterministic Core matrix planning for WorldLine."""

import re

from .layouts import get_layout_template, layout_template_ids
from .pipeline import TASK_TYPES, case_signature, validate_unique_case_signatures


# Reproduce the frozen v2 snapshot when no explicit shot-count selection is given.
# The revised primary design uses mixed three- and four-shot episodes.
CORE_SHOT_COUNTS = (3,)
SUPPORTED_SHOT_COUNTS = (3, 4, 5, 7)
CORE_SUBJECT_COUNTS = (3, 4)
CORE_VIEWPOINT_MODES = ("reverse_axis", "overhead")

SCENE_CODES = {
    "café": "CAFE",
    "meeting room": "MEETING",
    "living room": "LIVING",
    "dining room": "DINING",
    "seminar room": "SEMINAR",
    "game room": "GAME",
    "kitchen": "KITCHEN",
}
TASK_CODES = {
    "static_viewpoint_change": "STATIC",
    "person_entry": "ENTRY",
    "person_exit": "EXIT",
    "position_swap": "SWAP",
}
VIEWPOINT_CODES = {"reverse_axis": "REV", "overhead": "TOP"}


def viewpoint_mode_for_template(template):
    probe = template["cameras"][template["grammar"]["probe_camera"]]
    return "overhead" if probe.get("view_direction") == "overhead" else "reverse_axis"


def _fallback_code(value):
    return re.sub(r"[^A-Z0-9]+", "-", str(value).upper()).strip("-")


def core_case_id(config):
    scene_code = SCENE_CODES.get(config["scene"], _fallback_code(config["scene"]))
    return "WL-CORE-{scene}-{task}-{subjects}P-{view}-{shots}S".format(
        scene=scene_code,
        task=TASK_CODES[config["task"]],
        subjects=config["subject_count"],
        view=VIEWPOINT_CODES[config["viewpoint_mode"]],
        shots=config["shot_count"],
    )


def plan_core_matrix(
    *,
    tasks=None,
    scenes=None,
    subject_counts=None,
    shot_counts=None,
    viewpoint_modes=None
):
    tasks = tuple(tasks or TASK_TYPES)
    scenes = set(scenes or SCENE_CODES)
    subject_counts = set(subject_counts or CORE_SUBJECT_COUNTS)
    shot_counts = tuple(shot_counts or CORE_SHOT_COUNTS)
    viewpoint_modes = set(viewpoint_modes or CORE_VIEWPOINT_MODES)
    cases = []
    for layout_id in layout_template_ids():
        template = get_layout_template(layout_id)
        scene = template["scene_type"]
        subject_count = len(template["seat_order"])
        viewpoint_mode = viewpoint_mode_for_template(template)
        if (
            scene not in scenes
            or subject_count not in subject_counts
            or viewpoint_mode not in viewpoint_modes
        ):
            continue
        for task in tasks:
            if task not in TASK_TYPES:
                raise ValueError("Unknown task type: {}.".format(task))
            for shot_count in shot_counts:
                config = {
                    "task": task,
                    "scene": scene,
                    "layout": layout_id,
                    "viewpoint_mode": viewpoint_mode,
                    "subject_count": subject_count,
                    "shot_count": shot_count,
                }
                cases.append(
                    {
                        "id": core_case_id(config),
                        "task": task,
                        "scene": scene,
                        "layout": layout_id,
                        "viewpoint_mode": viewpoint_mode,
                        "subject_count": subject_count,
                        "shot_count": shot_count,
                        "archetype": template["archetype"],
                        "case_signature": case_signature(config),
                    }
                )
    signature_errors = validate_unique_case_signatures(
        [case["case_signature"] for case in cases]
    )
    if signature_errors:
        raise ValueError("Invalid Core matrix: {}".format(" ".join(signature_errors)))
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Core matrix contains duplicate episode IDs.")
    return sorted(cases, key=lambda case: case["id"])
