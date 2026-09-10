"""Version-isolated mixed Core design; legacy templates and outputs stay intact."""

import re
from collections import Counter, defaultdict

from .annotations import build_annotations, digest
from .balance import SCENES, TASKS, casting_contract
from .layouts import get_layout_template
from .matrix import core_case_id, plan_core_matrix
from .pipeline import (build_shot_contracts, case_signature, compile_episode,
                       validate_compiled_episode, validate_layout_template)
from .sources import select_source

VERSION = "3.0"
REFERENCE_VERSION = "3.1"

# End A supplies an orientation landmark for overhead readouts.
# These are semantic directions, not numeric camera calibration.
SPACES = {
    "café": ("floor plant", "café counter", "window", "aisle", "rectangular table"),
    "meeting room": ("presentation screen", "glass door", "window", "walkway", "conference table"),
    "living room": ("bookcase", "doorway", "sofa", "armchair", "coffee table"),
    "dining room": ("sideboard", "patio doors", "window", "aisle", "dining table"),
    "seminar room": ("pinboard", "entrance", "window", "aisle", "worktable"),
    "game room": ("shelving unit", "doorway", "window", "aisle", "game table"),
    "kitchen": ("sink counter", "refrigerator", "window", "aisle", "kitchen island"),
}


def revised_layout(layout_id):
    match = re.fullmatch(r"(.+)_r([0-3])_v3(?:_1)?", layout_id)
    if not match:
        raise ValueError("Invalid v3 layout ID: " + layout_id)
    template = get_layout_template(match[1] + "_v1")
    rotation = int(match[2])
    seats = template["seat_order"]
    n = len(seats)
    if n == 3 and rotation >= 2:
        raise ValueError("Three-person partials must retain the adjacent seat pair")
    scene = template["scene_type"]
    end_a, end_b, side_a, side_b, area = SPACES[scene]
    if scene == "kitchen":
        # Guest/cook lacked a physical side anchor. Use window/aisle instead.
        template["seats"] = {k: v.replace("guest", "window").replace("cook", "aisle")
                             for k, v in template["seats"].items()}
        template["public_intro"] = (
            "Inside a kitchen, a rectangular island stands between a sink counter and a "
            "refrigerator, with a window along one side and an aisle along the opposite side."
        )
    elif scene == "living room":
        template["public_intro"] = (
            "Inside a living room, a rectangular coffee table stands between a bookcase "
            "and the doorway. A two-seat sofa runs along one long side, facing "
            + ("an armchair near the bookcase end." if n == 3 else "two armchairs along the opposite side.")
        )
    else:
        template["public_intro"] = (
            template["public_intro"].rstrip(".") + "; a clear "
            + side_b + " runs opposite the window."
        )
    # Do not retain a contradictory legacy internal scene description.
    template["scene"] = template["public_intro"]
    group = rotation // 2
    pair = seats[group * 2:group * 2 + 2]
    if rotation % 2:
        pair = list(reversed(pair))
    order = pair + [seat for seat in seats if seat not in pair]
    template["seat_order"] = order
    template["seats"] = {seat: template["seats"][seat] for seat in order}
    template["version"] = REFERENCE_VERSION if layout_id.endswith("_v3_1") else VERSION
    template["id"] = layout_id
    original_open = template["cameras"][template["grammar"]["opening_camera"]]
    direction = original_open["view_direction"]
    if scene == "living room":
        coverage = "both sofa seats and " + ("the bookcase-side armchair" if n == 3 else "both armchairs")
        focus = "the two sofa seats" if group == 0 else "the two armchairs"
        origin = "the coffee-table side"
    else:
        noun = "stools" if scene == "kitchen" else "seats"
        coverage = "both {}-side {} and ".format(side_a, noun)
        coverage += template["seats"][seats[2]] if n == 3 else "both {}-side {}".format(side_b, noun)
        focus = "the two adjacent {}-side {}".format(side_a if group == 0 else side_b, noun)
        origin = "the {} side".format(side_b if group == 0 else side_a)
    top_landmark = "the sink basin and the window ledge" if scene == "kitchen" else "the " + end_a
    if scene not in {"living room", "kitchen"}:
        top_landmark += " and the window ledge"
    template["cameras"] = {
        "establish": {
            "framing": "wide", "view_direction": direction,
            "public_view": "Wide establishing shot from just beside the {} end, looking along the {} toward the {}, with {} and the {} in frame.".format(end_b, area, end_a, coverage, end_a),
            "visible_seats": seats,
        },
        "partial_pair": {
            "framing": "two_shot",
            "public_view": "Medium two-shot from {}, centered on {}.".format(origin, focus),
            "visible_seats": pair,
        },
        "partial_first": {
            "framing": "close_up",
            "public_view": "Close-up from {}, centered on the person at {}.".format(origin, template["seats"][pair[0]]),
            "visible_seats": [pair[0]],
        },
        "partial_second": {
            "framing": "close_up",
            "public_view": "Close-up from {}, centered on the person at {}.".format(origin, template["seats"][pair[1]]),
            "visible_seats": [pair[1]],
        },
        "probe_reverse": {
            "framing": "wide", "view_direction": "_to_".join(reversed(direction.split("_to_"))),
            "public_view": "Reverse wide shot from just beside the {} end, looking along the {} toward the {}, with {} and the {} in frame.".format(end_a, area, end_b, coverage, end_b),
            "visible_seats": seats,
        },
        "probe_overhead": {
            "framing": "wide", "view_direction": "overhead",
            "public_view": "Top-down wide shot from directly above the {}, with {}, {}, and the full {} in frame.".format(area, coverage, top_landmark, area),
            "visible_seats": seats,
        },
    }
    template["grammar"] = {
        "opening_camera": "establish",
        "partial_cameras": ["partial_pair", "partial_first", "partial_second"],
        "probe_camera": "probe_overhead" if "overhead" in match[1] else "probe_reverse",
        "probe_focus_seats": pair,
    }
    if template["version"] == REFERENCE_VERSION:
        # Preserve internal coverage for construction, never repeat it as a final answer hint.
        template["cameras"]["probe_reverse"]["public_view"] = "Reverse wide shot of the {}.".format(area)
        template["cameras"]["probe_overhead"]["public_view"] = "Top-down wide shot directly above the {}.".format(area)
    return template


def plan_mixed_core(version=VERSION):
    if version not in {VERSION, REFERENCE_VERSION}:
        raise ValueError("Unsupported mixed Core version")
    cases = []
    for base in plan_core_matrix():
        s, t, n = SCENES.index(base["scene"]), TASKS.index(base["task"]), base["subject_count"]
        rotation = (s // 2 + t) % 2
        if n == 4:
            rotation += 2 * ((s + t // 2) % 2)
        config = {
            **base, "dataset_version": version,
            "shot_count": 3 + (s // 2 + t + n - 3) % 2,
            "layout": base["layout"][:-3] + "_r{}_v3".format(rotation) + ("_1" if version == REFERENCE_VERSION else ""),
        }
        case = {k: config[k] for k in ("task", "scene", "layout", "viewpoint_mode", "subject_count", "shot_count", "archetype")}
        case.update(id=core_case_id(config), case_signature=case_signature(config), source_id=select_source(config)["id"])
        cases.append(case)
    return sorted(cases, key=lambda c: c["id"])


def design_check(cases, version=VERSION):
    """Check declared design, not real geometric visibility or human quality."""
    errors = []
    sources, event_seats, lengths = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    contracts_out = []
    if cases != plan_mixed_core(version):
        errors.append("Cases differ from the deterministic mixed Core plan")
    for case in cases:
        template = get_layout_template(case["layout"])
        errors.extend(case["id"] + ": " + error for error in validate_layout_template(template))
        contracts = build_shot_contracts(template, case["shot_count"], case["task"])
        episode = compile_episode(
            case["id"], case["task"], template, {"subjects": casting_contract(case)},
            {"shots": [{"index": c["index"], "beat": ""} for c in contracts]}, contracts,
        )
        errors.extend(case["id"] + ": " + error for error in validate_compiled_episode(episode, template))
        bystanders = {s["id"] for s in episode["subjects"][2:]}
        unmentioned = bystanders - set(contracts[-1]["mentioned"])
        for contract in contracts[1:-1]:
            unmentioned -= set(contract["mentioned"])
        if not unmentioned:
            errors.append(case["id"] + ": no persistent offscreen bystander")
        sources[(case["scene"], case["task"])][case["source_id"]] += 1
        if case["task"] in {"person_entry", "person_exit"}:
            event_seats[(case["scene"], case["subject_count"])][template["seat_order"][1]] += 1
        lengths[case["task"]][case["shot_count"]] += 1
        annotation = build_annotations(episode, template, {"id": case["source_id"]})
        contracts_out.append({
            "id": case["id"], "contracts": contracts, "layout_sha256": annotation["layout_sha256"],
            "subjects": episode["subjects"], "observations": annotation["observations"],
        })
    for key, values in sources.items():
        if sorted(values.values()) != [2, 2]:
            errors.append(str(key) + ": source/task imbalance")
    for key, values in lengths.items():
        if values != {3: 14, 4: 14}:
            errors.append(str(key) + ": mixed shot imbalance")
    distributions = {
        field: dict(Counter(c[field] for c in cases))
        for field in ("task", "scene", "subject_count", "viewpoint_mode", "shot_count")
    }
    return {
        "version": version, "case_count": len(cases), "plan_sha256": digest(cases), "errors": errors,
        "distributions": distributions,
        "sources_by_scene_task": {"/".join(k): dict(v) for k, v in sources.items()},
        "event_seats_by_scene_count": {"{}/{}".format(*k): dict(v) for k, v in event_seats.items()},
        "geometry_validation": "declared coverage only; human and video validation pending",
    }, contracts_out
