"""Frozen wide-shot ground truth and the two-part WorldLine scoring contract."""

import hashlib
import json

DATASET_VERSION = "2.0"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def build_annotations(episode, template, source):
    from .pipeline import states_by_shot, positions_by_shot, probe_expectations_for_shot
    states, positions = states_by_shot(episode), positions_by_shot(episode)
    observations = []
    for shot, present, seats in zip(episode["shots"], states, positions):
        camera = template["cameras"][shot["camera"]]
        if camera["framing"] != "wide":
            continue
        occupants = {
            seat: next((sid for sid, location in seats.items() if location == seat and present[sid]), None)
            for seat in camera["visible_seats"]
        }
        observations.append({
            "shot": shot["index"],
            "scored": shot["index"] != 1,
            "camera": shot["camera"],
            "expected_count": sum(sid is not None for sid in occupants.values()),
            "expected_occupants": occupants,
            "unmentioned_probes": probe_expectations_for_shot(episode, template, shot["index"]),
        })
    result = {
        "version": template.get("version", DATASET_VERSION),
        "episode_id": episode["id"],
        "source_id": source["id"],
        "layout": template,
        "layout_sha256": digest(template),
        "identity_anchor_shots": {
            subject["id"]: next(shot["index"] for shot in episode["shots"] if subject["id"] in shot["mentioned"])
            for subject in episode["subjects"]
        },
        "observations": observations,
    }
    if result["version"] == "3.1":
        result["evaluation_reference"] = "observed_opening_plus_requested_updates"
    return result


def score_wide_observation(annotation, *, observed_count, observed_occupants, view_compliant):
    """Score a human/detector observation, not pixels. Partial shots have no record.

    Identity-to-landmark-seat correspondence represents spatial relations, not
    screen-left/right coordinates. Unknown/occluded seats must not be guessed.
    Count includes all people in the controlled interaction area, even unmatched
    extras. Both components cover mentioned AND unmentioned subjects.
    """
    if not annotation["scored"]:
        raise ValueError("Establishing views are references, not final evaluation shots.")
    if not view_compliant:
        return {"count_correct": None, "position_correct": None, "joint_success": False}
    count_correct = observed_count == annotation["expected_count"]
    position_correct = observed_occupants == annotation["expected_occupants"]
    return {
        "count_correct": count_correct,
        "position_correct": position_correct,
        "joint_success": count_correct and position_correct,
    }
