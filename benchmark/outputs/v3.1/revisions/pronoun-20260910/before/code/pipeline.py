"""Deterministic WorldLine prompt construction with staged LLM generation."""

import os
import re
import copy
from dataclasses import dataclass
from typing import Mapping, Optional

from .layouts import get_layout_template
from .openrouter import OpenRouterClient
from .balance import casting_contract
from .sources import select_source
from .annotations import DATASET_VERSION, build_annotations


DURATION_PATTERN = re.compile(
    r"\b(?:duration|timestamp|timecode)\b|"
    r"\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|minutes?|mins?)\b|"
    r"\b\d{1,2}:\d{2}\b|\bhold for\b",
    re.IGNORECASE,
)
FINAL_ANSWER_PATTERN = re.compile(
    r"\b(?:all three|the three (?:friends|people|subjects|characters)|"
    r"same three|still (?:there|present|seated)|"
    r"remain(?:s|ed)? (?:there|present|seated))\b",
    re.IGNORECASE,
)
PUBLIC_META_PATTERN = re.compile(
    r"\b(?:probe|re-observation|expected[_ -]?visible|mention contract|"
    r"opening view|opening shot|different direction than)\b",
    re.IGNORECASE,
)
FRAMING_TEXT_RULES = {
    "wide": re.compile(r"\bwide\b", re.IGNORECASE),
    "two_shot": re.compile(
        r"\b(?:medium|two[- ]shot|two[- ]person|two people)\b", re.IGNORECASE
    ),
    "close_up": re.compile(r"\bclose\b", re.IGNORECASE),
}
NEGATIVE_VIEW_PATTERN = re.compile(
    r"\b(?:no|not|without|only|exclude|excluding|outside the frame)\b",
    re.IGNORECASE,
)
INTERNAL_LINE_BREAK_PATTERN = re.compile(r"[\r\n]")
OVER_SPECIFIED_VIEW_PATTERN = re.compile(
    r"\b\d+\s*mm\b|\bmeters? high\b|\beye level\b|\boptical axis\b|"
    r"\bframe edges?\b|\bouter shoulders?\b|\bdownward angle\b",
    re.IGNORECASE,
)
APPEARANCE_STOP_WORDS = {
    "adult",
    "and",
    "with",
    "wearing",
    "woman",
    "man",
    "person",
    "hair",
    "the",
    "their",
    "has",
    "who",
}
GENDER_VALUES = ("woman", "man")
TASK_TYPES = (
    "static_viewpoint_change",
    "person_entry",
    "person_exit",
    "position_swap",
)
CLOTHING_COLOR_PATTERN = re.compile(
    r"\b(?:red|blue|green|yellow|orange|purple|pink|brown|black|white|gray|grey|"
    r"navy|teal|maroon|mustard|cobalt|emerald|olive|beige|cream|burgundy|charcoal)\b",
    re.IGNORECASE,
)
GARMENT_PATTERN = re.compile(
    r"\b(?:shirt|sweater|jacket|cardigan|blouse|dress|hoodie|coat|turtleneck|"
    r"vest|polo|pullover|blazer|sweatshirt|overshirt|tunic|top|tee|t-shirt)\b",
    re.IGNORECASE,
)
FORBIDDEN_APPEARANCE_DETAIL_PATTERN = re.compile(
    r"\b(?:hair|haired|bun|ponytail|braid|curls?|glasses|eyeglasses|spectacles|"
    r"beard|mustache|hat|earrings?|necklace|scarf)\b",
    re.IGNORECASE,
)
DECORATIVE_DETAIL_PATTERN = re.compile(
    r"\b(?:leans?|leaning|smiles?|smiling|grins?|grinning|chuckles?|chuckling|"
    r"laughs?|laughing|sighs?|sighing|nods?|nodding|gestures?|gesturing|"
    r"hands?|forearms?|chin|gaze|expression|mug|cup|fingers?|shrugs?|shrugging|"
    r"animatedly|softly|quietly|warmly|eagerly|intrigued|amused|relaxed|"
    r"serves|pours|sips|eats|drinks|stirs|peels|chops)\b",
    re.IGNORECASE,
)
UNPLANNED_TASK_PATTERN = re.compile(
    r"\b(?:starts?|begins?|decides?) to (?:start )?(?:cook(?:ing)?|prepar(?:e|ing)|clean(?:ing)?|fetch(?:ing)?|bring(?:ing)?|deliver(?:ing)?)\b|"
    r"\b(?:asks?|requests?) to continue (?:cook|chop|peel|prepar|clean)\w*\b",
    re.IGNORECASE,
)


@dataclass
class PipelineOptions:
    """Configuration for one prompt-construction run."""

    episode_id: str = "WL-PY-PILOT-001"
    task: str = "static_viewpoint_change"
    layout: str = "cafe_rect_table_3_v1"
    archetype: Optional[str] = None
    source: Optional[str] = None
    source_id: Optional[str] = None
    subject_count: Optional[int] = None
    shot_count: int = 3
    model: Optional[str] = None
    skeleton_model: Optional[str] = None
    casting_model: Optional[str] = None
    story_model: Optional[str] = None
    render_model: Optional[str] = None
    audit_model: Optional[str] = None


def case_signature(config):
    """Return the experimental dimensions that define a distinct benchmark case."""
    return {
        "task_type": config["task"],
        "scene": config["scene"],
        "viewpoint_mode": config["viewpoint_mode"],
        "subject_count": config["subject_count"],
        "shot_count": config["shot_count"],
    }


def validate_unique_case_signatures(signatures):
    """Reject cases that differ only in cast styling, wording, or random seed."""
    errors = []
    seen = {}
    for index, signature in enumerate(signatures, start=1):
        key = tuple(signature.get(field) for field in (
            "task_type",
            "scene",
            "viewpoint_mode",
            "subject_count",
            "shot_count",
        ))
        if key in seen:
            errors.append(
                "Case {} duplicates Case {} on every benchmark dimension.".format(
                    index, seen[key]
                )
            )
        else:
            seen[key] = index
    return errors


def _object_schema(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": False,
    }


def _string_schema(description):
    return {"type": "string", "minLength": 1, "description": description}


def _exact_array(items, length):
    return {
        "type": "array",
        "items": items,
        "minItems": length,
        "maxItems": length,
    }


def _normalized(value):
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _subject_ids(count):
    if not isinstance(count, int) or count < 2 or count > 26:
        raise ValueError("subject count must be an integer between 2 and 26.")
    return [chr(65 + index) for index in range(count)]


def _task_events(task, shot_index):
    """Return the frozen state transition for one shot."""
    if shot_index != 2:
        return []
    if task == "person_entry":
        return [{"subject": "B", "action": "enter"}]
    if task == "person_exit":
        return [{"subject": "B", "action": "exit"}]
    if task == "position_swap":
        return [{"subject": "A", "action": "swap", "with_subject": "B"}]
    return []


def _initial_presence(task, subject_ids):
    presence = {subject_id: True for subject_id in subject_ids}
    if task == "person_entry":
        presence["B"] = False
    return presence


def _apply_events(presence, positions, events):
    next_presence = dict(presence)
    next_positions = dict(positions)
    for event in events:
        subject_id = event["subject"]
        action = event["action"]
        if action == "enter":
            next_presence[subject_id] = True
        elif action == "exit":
            next_presence[subject_id] = False
        elif action == "swap":
            other_id = event["with_subject"]
            next_positions[subject_id], next_positions[other_id] = (
                next_positions[other_id],
                next_positions[subject_id],
            )
    return next_presence, next_positions


def _all_text(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _all_text(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _all_text(item)]
    return []


def _duration_errors(value):
    return [
        "Duration language is forbidden: {!r}".format(text)
        for text in _all_text(value)
        if DURATION_PATTERN.search(text)
    ]


def _same_members(left, right):
    return sorted(left) == sorted(right)


def _is_strong_viewpoint_change(opening_direction, probe_direction):
    opening_direction = _normalized(opening_direction)
    probe_direction = _normalized(probe_direction)
    if "overhead" in {opening_direction, probe_direction}:
        return opening_direction != probe_direction
    opening_parts = opening_direction.split("_to_")
    probe_parts = probe_direction.split("_to_")
    return (
        len(opening_parts) == 2
        and len(probe_parts) == 2
        and opening_parts == list(reversed(probe_parts))
    )


def _sequential_indexes(shots):
    return all(shot.get("index") == index + 1 for index, shot in enumerate(shots))


def _appearance_tokens(appearance):
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _normalized(appearance))
        if len(token) > 2 and token not in APPEARANCE_STOP_WORDS
    ]


def _text_mentions_subject(text, subject):
    subject_id = re.escape(subject["id"])
    internal_id = re.compile(
        r"\b(?:subject|character)\s+{}\b".format(subject_id), re.IGNORECASE
    )
    text_tokens = set(re.findall(r"[a-z0-9]+", _normalized(text)))
    anchor_hits = [
        token for token in _appearance_tokens(subject["appearance"]) if token in text_tokens
    ]
    return bool(
        internal_id.search(text)
        or _normalized(subject["appearance"]) in _normalized(text)
        or len(anchor_hits) >= 2
    )


def _internal_id_mentions(text):
    return [
        match.upper()
        for match in re.findall(r"\bSubject\s+([A-Z])\b", str(text), re.IGNORECASE)
    ]


def skeleton_schema():
    return _object_schema(
        {
            "source_id": _string_schema("Copy the real source ID exactly."),
            "archetype": _string_schema("Copy the supplied archetype exactly."),
            "premise": _string_schema("A faithful abstraction of the supplied excerpt's interaction."),
            "interaction_arc": _string_schema(
                "A concise ordered narrative progression, not divided into shots."
            ),
        }
    )


def casting_schema(config):
    ids = _subject_ids(config["subject_count"])
    return _object_schema(
        {
            "subjects": _exact_array(
                _object_schema(
                    {
                        "id": {"type": "string", "enum": ids},
                        "gender": {"type": "string", "enum": list(GENDER_VALUES)},
                        "clothing": _string_schema(
                            "A clothing color and garment, without an article."
                        ),
                    }
                ),
                config["subject_count"],
            )
        }
    )


def beat_plan_schema(config):
    ids = _subject_ids(config["subject_count"])
    # Each case has one known event type. Avoid a union that some VAPI Gemini
    # routes cannot translate, while retaining strict fields and event objects.
    task = config["task"]
    actions = {"person_entry": ["enter"], "person_exit": ["exit"],
               "position_swap": ["swap"], "static_viewpoint_change": ["enter", "exit"]}
    event_fields = {
        "subject": {"type": "string", "enum": ids},
        "action": {"type": "string", "enum": actions[task]},
    }
    if task == "position_swap":
        event_fields["with_subject"] = {"type": "string", "enum": ids}
    events = {"type": "array", "items": _object_schema(event_fields)}
    if task == "static_viewpoint_change":
        events["maxItems"] = 0
    return _object_schema(
        {
            "shots": _exact_array(
                _object_schema(
                    {
                        "index": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": config["shot_count"],
                        },
                        "beat": _string_schema(
                            "Story actions performed only by mentioned subjects."
                        ),
                        "events": events,
                    }
                ),
                config["shot_count"],
            )
        }
    )


def content_prompt_schema(config):
    return _object_schema(
        {
            "shots": _exact_array(
                _object_schema(
                    {
                        "index": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": config["shot_count"],
                        },
                        "content": _string_schema(
                            "Only story-world content, with no camera or duration language."
                        ),
                    }
                ),
                config["shot_count"],
            )
        }
    )


def audit_schema():
    return _object_schema(
        {
            "passed": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": _object_schema(
                    {
                        "stage": {
                            "type": "string",
                            "enum": ["story", "camera", "prompt"],
                        },
                        "message": _string_schema("One concise blocking issue."),
                    }
                ),
            },
        }
    )


def validate_layout_template(template):
    errors = []
    seat_ids = list((template.get("seats") or {}).keys())
    cameras = template.get("cameras") or {}
    camera_ids = list(cameras.keys())
    if not template.get("id") or not template.get("scene"):
        errors.append("Layout template requires id and scene.")
    if not template.get("scene_type") or not template.get("archetype") or not template.get(
        "story_venue"
    ):
        errors.append(
            "Layout template requires scene_type, archetype, and story_venue."
        )
    if not template.get("public_intro"):
        errors.append("Layout template requires one concise public_intro.")
    elif INTERNAL_LINE_BREAK_PATTERN.search(template["public_intro"]):
        errors.append("public_intro must be a single line.")
    elif PUBLIC_META_PATTERN.search(template["public_intro"]):
        errors.append("public_intro cannot expose benchmark meta-language.")
    elif _duration_errors(template["public_intro"]):
        errors.append("public_intro cannot contain duration language.")
    if not seat_ids or not _same_members(template.get("seat_order") or [], seat_ids):
        errors.append("seat_order must contain every seat exactly once.")

    for camera_id, camera in cameras.items():
        public_view = camera.get("public_view", "")
        if not camera.get("framing") or not public_view:
            errors.append("Camera {} requires framing and public_view.".format(camera_id))
        invalid_seats = [
            seat for seat in camera.get("visible_seats", []) if seat not in seat_ids
        ]
        if invalid_seats:
            errors.append(
                "Camera {} references unknown seats: {}.".format(
                    camera_id, ", ".join(invalid_seats)
                )
            )
        if not camera.get("visible_seats"):
            errors.append("Camera {} must cover at least one seat.".format(camera_id))
        if PUBLIC_META_PATTERN.search(public_view):
            errors.append(
                "Camera {} exposes benchmark meta-language in public_view.".format(
                    camera_id
                )
            )
        if INTERNAL_LINE_BREAK_PATTERN.search(public_view):
            errors.append("Camera {} public_view must be a single line.".format(camera_id))
        if NEGATIVE_VIEW_PATTERN.search(public_view):
            errors.append(
                "Camera {} public_view must use positive composition language.".format(
                    camera_id
                )
            )
        framing_rule = FRAMING_TEXT_RULES.get(camera.get("framing"))
        if framing_rule and not framing_rule.search(public_view):
            errors.append(
                "Camera {} public_view does not express its {} framing.".format(
                    camera_id, camera.get("framing")
                )
            )
        if camera.get("framing") == "wide":
            if not camera.get("view_direction"):
                errors.append(
                    "Wide camera {} requires a deterministic view_direction.".format(
                        camera_id
                    )
                )
            reference_probe = template.get("version") == "3.1" and camera_id != template["grammar"]["opening_camera"]
            if reference_probe and public_view != reference_view(template, camera["view_direction"]):
                errors.append("Reference probe must use only the standard wide/view-change instruction.")
            if not reference_probe and not re.search(r"\bfrom\b", public_view, re.IGNORECASE):
                errors.append(
                    "Wide camera {} requires one concise viewpoint origin.".format(camera_id)
                )
            if not reference_probe and not re.search(
                r"\b(?:visible|showing|shows|in (?:the )?frame)\b",
                public_view,
                re.IGNORECASE,
            ):
                errors.append(
                    "Wide camera {} requires concise seat coverage language.".format(
                        camera_id
                    )
                )
        if OVER_SPECIFIED_VIEW_PATTERN.search(public_view):
            errors.append(
                "Camera {} public_view contains over-specified photography parameters.".format(
                    camera_id
                )
            )

    grammar = template.get("grammar") or {}
    referenced = [
        grammar.get("opening_camera"),
        grammar.get("probe_camera"),
    ] + list(grammar.get("partial_cameras") or [])
    for camera_id in referenced:
        if camera_id not in camera_ids:
            errors.append("Grammar references unknown camera: {}.".format(camera_id))
    if not grammar.get("partial_cameras"):
        errors.append("Grammar requires at least one partial camera.")
    elif len(seat_ids) >= 2:
        event_camera = cameras.get(grammar["partial_cameras"][0], {})
        if not set(seat_ids[:2]).issubset(set(event_camera.get("visible_seats", []))):
            errors.append(
                "The first partial camera must cover the first two seats for Entry, "
                "Exit, and Position Swap events."
            )

    opening = cameras.get(grammar.get("opening_camera"))
    probe = cameras.get(grammar.get("probe_camera"))
    if grammar.get("opening_camera") == grammar.get("probe_camera"):
        errors.append("Opening and probe cameras must use different presets.")
    if opening and not _same_members(opening.get("visible_seats", []), seat_ids):
        errors.append("Opening camera must cover every seat.")
    if probe and not _same_members(probe.get("visible_seats", []), seat_ids):
        errors.append("Probe camera must cover every seat.")
    if opening and probe and _normalized(opening["public_view"]) == _normalized(
        probe["public_view"]
    ):
        errors.append("Opening and probe cameras must use different views.")
    if opening and probe and not _is_strong_viewpoint_change(
        opening.get("view_direction"), probe.get("view_direction")
    ):
        errors.append(
            "Opening and probe wide cameras must reverse the landmark-to-landmark axis "
            "or switch to an overhead view."
        )
    if opening and not re.search(
        r"\bestablishing\b", opening.get("public_view", ""), re.IGNORECASE
    ):
        errors.append("Opening wide camera must use the standard term establishing shot.")
    if probe and probe.get("view_direction") != "overhead" and not re.search(
        r"\breverse\b", probe.get("public_view", ""), re.IGNORECASE
    ):
        errors.append("Reverse-axis probe camera must use the standard term reverse wide shot.")

    focus_seats = grammar.get("probe_focus_seats") or []
    invalid_focus = [
        seat for seat in focus_seats if seat not in (probe or {}).get("visible_seats", [])
    ]
    if invalid_focus:
        errors.append(
            "Probe focus references seats outside the probe view: {}.".format(
                ", ".join(invalid_focus)
            )
        )
    if not focus_seats or len(focus_seats) >= len(seat_ids):
        errors.append("Probe focus must cover some, but not all, seats.")
    errors.extend(_duration_errors(template))
    return errors


def build_shot_contracts(
    template, shot_count, task="static_viewpoint_change"
):
    if not isinstance(shot_count, int) or shot_count < 3:
        raise ValueError("shot_count must be at least 3.")
    if task not in TASK_TYPES:
        raise ValueError("Unknown task type: {}.".format(task))
    ids = _subject_ids(len(template["seat_order"]))
    if len(ids) < 3:
        raise ValueError("WorldLine task trajectories require at least 3 subjects.")
    seat_to_subject = dict(zip(template["seat_order"], ids))
    presence = _initial_presence(task, ids)
    positions = {subject_id: seat for seat, subject_id in seat_to_subject.items()}

    def observed_subjects(camera, before_presence, before_positions, events):
        after_presence, after_positions = _apply_events(
            before_presence, before_positions, events
        )
        visible_seats = set(template["cameras"][camera]["visible_seats"])
        return [
            subject_id
            for subject_id in ids
            if (
                before_presence[subject_id]
                and before_positions[subject_id] in visible_seats
            )
            or (
                after_presence[subject_id]
                and after_positions[subject_id] in visible_seats
            )
        ]

    def framing_matches(camera, mentioned):
        framing = template["cameras"][camera]["framing"]
        if framing == "two_shot":
            return len(mentioned) == 2
        if framing == "close_up":
            return len(mentioned) == 1
        return bool(mentioned)

    contracts = [
        {
            "index": 1,
            "mentioned": [subject_id for subject_id in ids if presence[subject_id]],
            "camera": template["grammar"]["opening_camera"],
            "events": [],
        }
    ]
    partial_cameras = template["grammar"]["partial_cameras"]
    for index in range(2, shot_count):
        camera = partial_cameras[(index - 2) % len(partial_cameras)]
        events = _task_events(task, index)
        mentioned = observed_subjects(camera, presence, positions, events)
        if not framing_matches(camera, mentioned):
            for candidate in partial_cameras:
                candidate_mentions = observed_subjects(
                    candidate, presence, positions, events
                )
                if framing_matches(candidate, candidate_mentions):
                    camera = candidate
                    mentioned = candidate_mentions
                    break
        contracts.append(
            {
                "index": index,
                "mentioned": mentioned,
                "camera": camera,
                "events": events,
            }
        )
        presence, positions = _apply_events(presence, positions, events)

    if task == "static_viewpoint_change":
        probe_ids = {ids[-1]}
    elif task in {"person_entry", "person_exit"}:
        probe_ids = {"B", "C"}
    else:
        # Score all occupants; keep a changed subject and bystanders unmentioned.
        probe_ids = set(ids) - {"A"}
    final_mentions = [
        subject_id
        for subject_id in ids
        if subject_id not in probe_ids and presence[subject_id]
    ]
    contracts.append(
        {
            "index": shot_count,
            "mentioned": final_mentions,
            "camera": template["grammar"]["probe_camera"],
            "events": [],
        }
    )
    return contracts


def validate_skeleton(
    skeleton, required_archetype, task="static_viewpoint_change", source=None
):
    if not isinstance(skeleton, dict):
        return ["Skeleton must be an object."]
    errors = []
    if _normalized(skeleton.get("archetype")) != _normalized(required_archetype):
        errors.append("Skeleton archetype must remain exactly {!r}.".format(required_archetype))
    if not str(skeleton.get("premise", "")).strip() or not str(
        skeleton.get("interaction_arc", "")
    ).strip():
        errors.append("Skeleton requires premise and interaction_arc.")
    arc = str(skeleton.get("interaction_arc", ""))
    # Do not fabricate an experimental state event in the source abstraction.
    # The next story-planning stage explicitly adapts the real interaction.
    if source:
        if skeleton.get("source_id") != source["id"]:
            errors.append("Skeleton must cite the exact supplied source_id.")
        text = _normalized(str(skeleton.get("premise", "")) + " " + arc)
        if not any(term in text for term in source["topic_terms"]):
            errors.append("Skeleton lost the source-specific topic: " + ", ".join(source["topic_terms"]))
    errors.extend(_duration_errors(skeleton))
    return errors


def source_topic_errors(value, source):
    text = _normalized(" ".join(_all_text(value)))
    if not any(term in text for term in source["topic_terms"]):
        return ["Retain a concrete source topic in the story: " + ", ".join(source["topic_terms"])]
    return []


def validate_casting(casting, config):
    if not isinstance(casting, dict):
        return ["Casting must be an object."]
    errors = []
    subjects = casting.get("subjects")
    ids = _subject_ids(config["subject_count"])
    if not isinstance(subjects, list) or len(subjects) != config["subject_count"]:
        errors.append(
            "Casting must contain exactly {} subjects.".format(config["subject_count"])
        )
    else:
        actual_ids = [subject.get("id") for subject in subjects]
        if not _same_members(actual_ids, ids):
            errors.append("Subject IDs must be exactly {}.".format(", ".join(ids)))
        if actual_ids != ids:
            errors.append(
                "Casting subjects must remain in seat-assignment order: {}.".format(
                    ", ".join(ids)
                )
            )
        clothing_values = [_normalized(subject.get("clothing", "")) for subject in subjects]
        if any(subject.get("gender") not in GENDER_VALUES for subject in subjects):
            errors.append("Every subject gender must be woman or man.")
        if any(not clothing for clothing in clothing_values):
            errors.append("Every subject requires a clothing anchor.")
        if len(set(clothing_values)) != config["subject_count"]:
            errors.append("Subject clothing anchors must be distinct.")
        for subject, clothing in zip(subjects, clothing_values):
            if re.match(r"^(?:a|an|the)\b", clothing):
                errors.append(
                    "Subject {} clothing must not include an article.".format(
                        subject.get("id")
                    )
                )
            if not CLOTHING_COLOR_PATTERN.search(clothing):
                errors.append(
                    "Subject {} clothing requires a recognizable color.".format(
                        subject.get("id")
                    )
                )
            if not GARMENT_PATTERN.search(clothing):
                errors.append(
                    "Subject {} clothing requires a recognizable garment.".format(
                        subject.get("id")
                    )
                )
            if FORBIDDEN_APPEARANCE_DETAIL_PATTERN.search(clothing):
                errors.append(
                    "Subject {} clothing must not include hair or accessories.".format(
                        subject.get("id")
                    )
                )
    if "scene" in config and "task" in config and subjects != casting_contract(config):
        errors.append("Copy the supplied balanced casting_contract exactly, in subject order.")
    errors.extend(_duration_errors(casting))
    return errors


def validate_beat_plan(beat_plan, config, contracts):
    if not isinstance(beat_plan, dict):
        return ["Beat plan must be an object."]
    errors = []
    shots = beat_plan.get("shots")
    if not isinstance(shots, list) or len(shots) != config["shot_count"]:
        errors.append(
            "Beat plan must contain exactly {} shots.".format(config["shot_count"])
        )
    else:
        if not _sequential_indexes(shots):
            errors.append("Story shot indexes must be sequential from 1.")
        for shot in shots:
            index = shot.get("index")
            if not isinstance(index, int) or not 1 <= index <= len(contracts):
                continue
            contract = contracts[index - 1]
            expected_events = contract.get("events", [])
            if shot.get("events", []) != expected_events:
                errors.append(
                    "Shot {} events must exactly copy the frozen transition {}.".format(
                        index, expected_events
                    )
                )
            allowed = contract["mentioned"]
            forbidden = [
                subject_id
                for subject_id in _internal_id_mentions(shot.get("beat", ""))
                if subject_id not in allowed
            ]
            if forbidden:
                errors.append(
                    "Shot {} beat mentions subjects outside its mention contract: {}.".format(
                        index, ", ".join(forbidden)
                    )
                )
            if index == 1:
                opening_actors = set(_internal_id_mentions(shot.get("beat", "")))
                if opening_actors != {"A"}:
                    errors.append(
                        "Shot 1 must give a plot action only to Subject A; the "
                        "other subjects are established by identity and seat without actions."
                    )
            beat = str(shot.get("beat", ""))
            if UNPLANNED_TASK_PATTERN.search(beat):
                errors.append("Discuss the source topic while seated; do not start, decide to start, or request a physical task.")
            for event in expected_events:
                subject_id = event["subject"]
                action = event["action"]
                if subject_id not in _internal_id_mentions(beat):
                    errors.append(
                        "Shot {} beat must mention event subject {}.".format(
                            index, subject_id
                        )
                    )
                action_pattern = {
                    "enter": r"\b(?:enter|enters|arrive|arrives)\b",
                    "exit": r"\b(?:exit|exits|leave|leaves|depart|departs)\b",
                    "swap": r"\b(?:swap|swaps|exchange|exchanges|trade|trades)\b",
                }[action]
                if not re.search(action_pattern, beat, re.IGNORECASE):
                    errors.append(
                        "Shot {} beat must explicitly express the {} event.".format(
                            index, action
                        )
                    )
                if action == "exit" and not (
                    re.search(r"\b(?:leave|leaves)\b", beat, re.IGNORECASE)
                    and re.search(r"\b(?:exit|exits|depart|departs)\b", beat, re.IGNORECASE)
                ):
                    errors.append(
                        "Shot {} exit beat must state both leaving the seat and exiting "
                        "the scene.".format(index)
                    )
                if action == "swap" and event.get(
                    "with_subject"
                ) not in _internal_id_mentions(beat):
                    errors.append(
                        "Shot {} swap beat must mention both subjects.".format(index)
                    )
            if DECORATIVE_DETAIL_PATTERN.search(str(shot.get("beat", ""))):
                errors.append(
                    "Shot {} beat contains decorative staging instead of a minimal "
                    "plot-relevant action.".format(index)
                )
    errors.extend(_duration_errors(beat_plan))
    return errors


def compile_episode(episode_id, task, template, casting, beat_plan, contracts):
    subjects = []
    for index, subject in enumerate(casting["subjects"]):
        article = "an" if subject["clothing"][0].lower() in "aeiou" else "a"
        appearance = "a {} in {} {}".format(subject["gender"], article, subject["clothing"])
        subjects.append(
            {
                "id": subject["id"],
                "gender": subject["gender"],
                "clothing": subject["clothing"],
                "appearance": appearance,
                "seat": template["seat_order"][index],
                "initially_present": _initial_presence(
                    task, _subject_ids(len(casting["subjects"]))
                )[subject["id"]],
            }
        )
    shots = []
    for index, shot in enumerate(beat_plan["shots"]):
        shots.append(
            {
                "index": shot["index"],
                "mentioned": contracts[index]["mentioned"],
                "beat": shot["beat"],
                "events": contracts[index].get("events", []),
                "camera": contracts[index]["camera"],
            }
        )
    return {
        "id": episode_id,
        "task": task,
        "layout": template["id"],
        "subjects": subjects,
        "shots": shots,
    }


def states_by_shot(episode):
    state = {
        subject["id"]: subject["initially_present"] for subject in episode["subjects"]
    }
    states = []
    for shot in episode["shots"]:
        for event in shot.get("events", []):
            if event["action"] in {"enter", "exit"}:
                state[event["subject"]] = event["action"] == "enter"
        states.append(dict(state))
    return states


def positions_by_shot(episode):
    positions = {subject["id"]: subject["seat"] for subject in episode["subjects"]}
    values = []
    for shot in episode["shots"]:
        for event in shot.get("events", []):
            if event["action"] == "swap":
                left = event["subject"]
                right = event["with_subject"]
                positions[left], positions[right] = positions[right], positions[left]
        values.append(dict(positions))
    return values


def expected_visible_subjects(episode, template, shot_index):
    shot = episode["shots"][shot_index - 1]
    visible_seats = set(template["cameras"][shot["camera"]]["visible_seats"])
    after_presence = states_by_shot(episode)[shot_index - 1]
    after_positions = positions_by_shot(episode)[shot_index - 1]
    if shot_index == 1:
        before_presence = {
            subject["id"]: subject["initially_present"]
            for subject in episode["subjects"]
        }
        before_positions = {
            subject["id"]: subject["seat"] for subject in episode["subjects"]
        }
    else:
        before_presence = states_by_shot(episode)[shot_index - 2]
        before_positions = positions_by_shot(episode)[shot_index - 2]
    return [
        subject["id"]
        for subject in episode["subjects"]
        if (
            before_presence[subject["id"]]
            and before_positions[subject["id"]] in visible_seats
        )
        or (
            after_presence[subject["id"]]
            and after_positions[subject["id"]] in visible_seats
        )
    ]


def probe_subjects_for_shot(episode, template, shot_index):
    shot = episode["shots"][shot_index - 1]
    if shot_index == 1 or template["cameras"][shot["camera"]]["framing"] != "wide":
        return []
    visible_seats = set(template["cameras"][shot["camera"]]["visible_seats"])
    positions = positions_by_shot(episode)[shot_index - 1]
    mentioned = episode["shots"][shot_index - 1]["mentioned"]
    return [
        subject["id"]
        for subject in episode["subjects"]
        if positions[subject["id"]] in visible_seats
        and subject["id"] not in mentioned
    ]


def probe_expectations_for_shot(episode, template, shot_index):
    presence = states_by_shot(episode)[shot_index - 1]
    positions = positions_by_shot(episode)[shot_index - 1]
    return [
        {
            "subject": subject_id,
            "present": presence[subject_id],
            "seat": positions[subject_id] if presence[subject_id] else None,
        }
        for subject_id in probe_subjects_for_shot(
            episode, template, shot_index
        )
    ]


def validate_compiled_episode(episode, template):
    errors = []
    if episode.get("layout") != template["id"]:
        errors.append("Episode layout does not match the selected template.")
    if not _sequential_indexes(episode.get("shots", [])):
        errors.append("Episode shot indexes must be sequential from 1.")
    episode_ids = [subject["id"] for subject in episode.get("subjects", [])]
    if episode.get("task") not in TASK_TYPES:
        errors.append("Episode uses an unknown task type.")
    expected_initial = _initial_presence(episode.get("task"), episode_ids)
    actual_initial = {
        subject["id"]: subject.get("initially_present")
        for subject in episode.get("subjects", [])
    }
    if actual_initial != expected_initial:
        errors.append("Episode initial presence does not match its task trajectory.")
    for shot in episode.get("shots", []):
        expected_events = _task_events(episode.get("task"), shot.get("index"))
        if shot.get("events", []) != expected_events:
            errors.append(
                "Shot {} state transition does not match task {}.".format(
                    shot.get("index"), episode.get("task")
                )
            )
        if shot.get("camera") not in template["cameras"]:
            errors.append(
                "Shot {} references unknown camera {}.".format(
                    shot.get("index"), shot.get("camera")
                )
            )
            continue
        invalid = [item for item in shot.get("mentioned", []) if item not in episode_ids]
        if invalid:
            errors.append(
                "Shot {} mentions unknown subjects: {}.".format(
                    shot["index"], ", ".join(invalid)
                )
            )
        expected = expected_visible_subjects(episode, template, shot["index"])
        framing = template["cameras"][shot["camera"]]["framing"]
        if framing == "two_shot" and len(expected) != 2:
            errors.append(
                "Shot {} uses a two-shot but its state trajectory makes {} subjects "
                "observable in that camera.".format(shot["index"], len(expected))
            )
        if framing == "close_up" and len(expected) != 1:
            errors.append(
                "Shot {} uses a close-up but its state trajectory makes {} subjects "
                "observable in that camera.".format(shot["index"], len(expected))
            )
        outside = [item for item in shot.get("mentioned", []) if item not in expected]
        if outside:
            errors.append(
                "Shot {} mentions subjects outside camera coverage: {}.".format(
                    shot["index"], ", ".join(outside)
                )
            )
    final_camera_is_valid = bool(
        episode.get("shots")
        and episode["shots"][-1].get("camera") in template["cameras"]
    )
    if final_camera_is_valid:
        final_probe = probe_subjects_for_shot(
            episode, template, len(episode["shots"])
        )
        if not final_probe:
            errors.append(
                "Final wide shot must include at least one unmentioned state probe."
            )
        required_probes = {
            "static_viewpoint_change": {episode_ids[-1]},
            "person_entry": {"B", "C"},
            "person_exit": {"B", "C"},
            "position_swap": {"B", "C"},
        }.get(episode.get("task"), set())
        if not required_probes.issubset(set(final_probe)):
            errors.append(
                "Final probe does not include the task's changed and preserved targets."
            )
    errors.extend(_duration_errors(episode))
    return errors


def attach_prompt(episode, content_prompt, template):
    attached = {
        key: value for key, value in episode.items() if key != "shots"
    }
    attached["shots"] = []
    for index, shot in enumerate(episode["shots"]):
        completed_shot = dict(shot)
        completed_shot["prompt"] = {
            "content": content_prompt["shots"][index]["content"],
            "viewpoint": template["cameras"][shot["camera"]]["public_view"],
        }
        attached["shots"].append(completed_shot)
    return attached


def validate_prompt(episode, template=None):
    errors = []
    template = template if template is not None else get_layout_template(episode["layout"])
    for shot in episode.get("shots", []):
        prompt = shot.get("prompt") or {}
        content = str(prompt.get("content", ""))
        viewpoint = str(prompt.get("viewpoint", ""))
        if not content.strip() or not viewpoint.strip():
            errors.append("Shot {} requires Content and Viewpoint.".format(shot["index"]))
            continue
        if INTERNAL_LINE_BREAK_PATTERN.search(content):
            errors.append("Shot {} Content must be a single line.".format(shot["index"]))
        if INTERNAL_LINE_BREAK_PATTERN.search(viewpoint):
            errors.append("Shot {} Viewpoint must be a single line.".format(shot["index"]))
        if PUBLIC_META_PATTERN.search("{} {}".format(content, viewpoint)):
            errors.append(
                "Shot {} exposes benchmark meta-language in the public prompt.".format(
                    shot["index"]
                )
            )
        if FORBIDDEN_APPEARANCE_DETAIL_PATTERN.search(content):
            errors.append(
                "Shot {} Content uses hair or accessories instead of the approved gender "
                "and clothing anchors.".format(shot["index"])
            )
        if DECORATIVE_DETAIL_PATTERN.search(content):
            errors.append(
                "Shot {} Content contains decorative posture, expression, gesture, prop, "
                "or adverb details.".format(shot["index"])
            )
        if re.search(r"\b(?:treacle|raven|writing[- ]desk|premise|narrative structure|physical logic)\b", content, re.IGNORECASE):
            errors.append("Use a simple conversational topic, not literary details or story-analysis terminology.")
        if UNPLANNED_TASK_PATTERN.search(content):
            errors.append("Keep the interaction conversational; do not initiate an unplanned physical task.")
        if shot["index"] == 1:
            public_intro = template["public_intro"]
            if not _normalized(content).startswith(_normalized(public_intro)):
                errors.append(
                    "Shot 1 Content must begin with the exact public scene introduction "
                    "{!r} before introducing any subjects.".format(public_intro)
                )
            for subject in episode["subjects"]:
                if subject["id"] not in shot["mentioned"]:
                    continue
                seat_label = template["seats"][subject["seat"]]
                if _normalized(seat_label) not in _normalized(content):
                    errors.append(
                        "Shot 1 must assign subject {} to the exact compact seat label "
                        "{!r}.".format(subject["id"], seat_label)
                    )
        for subject in episode["subjects"]:
            mentioned_in_text = _text_mentions_subject(content, subject)
            should_be_mentioned = subject["id"] in shot["mentioned"]
            if should_be_mentioned and not mentioned_in_text:
                errors.append(
                    "Shot {} Content does not clearly mention contracted subject {}.".format(
                        shot["index"], subject["id"]
                    )
                )
            if not should_be_mentioned and mentioned_in_text:
                errors.append(
                    "Shot {} Content mentions uncontracted subject {}.".format(
                        shot["index"], subject["id"]
                    )
                )
            anchor_count = _normalized(content).count(
                _normalized(subject["clothing"])
            )
            if should_be_mentioned and anchor_count > 1:
                errors.append(
                    "Shot {} repeats subject {}'s identity anchor; state it once and "
                    "combine it with the seat or action.".format(
                        shot["index"], subject["id"]
                    )
                )
        for event in shot.get("events", []):
            action = event["action"]
            action_pattern = {
                "enter": r"\b(?:enter|enters|arrive|arrives)\b",
                "exit": r"\b(?:exit|exits|leave|leaves|depart|departs)\b",
                "swap": r"\b(?:swap|swaps|exchange|exchanges|trade|trades)\b",
            }[action]
            if not re.search(action_pattern, content, re.IGNORECASE):
                errors.append(
                    "Shot {} Content does not explicitly render the {} event.".format(
                        shot["index"], action
                    )
                )
            if action == "exit" and not (
                re.search(r"\b(?:leave|leaves)\b", content, re.IGNORECASE)
                and re.search(
                    r"\b(?:exit|exits|depart|departs)\b", content, re.IGNORECASE
                )
            ):
                errors.append(
                    "Shot {} exit Content must state both leaving the seat and exiting "
                    "the scene.".format(shot["index"])
                )
            event_subject = next(
                subject
                for subject in episode["subjects"]
                if subject["id"] == event["subject"]
            )
            if action == "enter":
                prefix = entry_content_prefix(event_subject, template)
                if not content.startswith(prefix):
                    errors.append("Entry Content must begin with the explicit arrival and seating sentence: " + prefix)
            required_seats = [event_subject["seat"]]
            if action == "swap":
                other_subject = next(
                    subject
                    for subject in episode["subjects"]
                    if subject["id"] == event["with_subject"]
                )
                required_seats.append(other_subject["seat"])
            if template.get("version") == "3.1":
                required_seats = []
                if any(_normalized(label) in _normalized(content) for label in template["seats"].values()):
                    errors.append("Reference-based updates must use identities and original places, not landmark seat labels.")
            for seat in required_seats:
                seat_label = template["seats"][seat]
                if _normalized(seat_label) not in _normalized(content):
                    errors.append(
                        "Shot {} {} event must include the exact seat label {!r}.".format(
                            shot["index"], action, seat_label
                        )
                    )
    if episode.get("shots"):
        if template.get("version") == "3.1":
            final_shot = episode["shots"][-1]
            if final_shot.get("prompt", {}).get("viewpoint") != template["cameras"][final_shot["camera"]]["public_view"]:
                errors.append("Final reference Viewpoint must contain only its fixed wide/view-change instruction.")
        if template.get("version") == "3.1" and episode["task"] == "person_entry":
            opening_text = episode["shots"][0].get("prompt", {}).get("content", "")
            if "one empty place" not in opening_text.lower():
                errors.append("Entry opening must establish one empty place for the requested arrival.")
        final_text = episode["shots"][-1].get("prompt", {}).get("content", "")
        if FINAL_ANSWER_PATTERN.search(final_text):
            errors.append("Final Content explicitly reveals the persistence answer.")
        if re.search(r"\balone\b", final_text, re.IGNORECASE):
            errors.append("Final Content must not imply that other established subjects have disappeared.")
        if any(_normalized(label) in _normalized(final_text) for label in template["seats"].values()):
            errors.append("Final Content must not restate seat assignments, including mentioned subjects.")
    errors.extend(
        _duration_errors([shot.get("prompt", {}) for shot in episode.get("shots", [])])
    )
    return errors


def entry_content_prefix(subject, template):
    if template.get("version") == "3.1":
        return subject["appearance"].capitalize() + " enters and sits in the empty place."
    label = template["seats"][subject["seat"]]
    preposition = "on" if "stool" in label else "in"
    appearance = subject["appearance"]
    return "{} enters and sits {} {}.".format(appearance[0].upper() + appearance[1:], preposition, label)


def reference_view(template, direction):
    """No identities, seat inventory, landmarks or numeric calibration at the probe."""
    from .core_v3 import SPACES
    area = SPACES[template["scene_type"]][-1]
    return ("Top-down wide shot directly above the {}." if direction == "overhead"
            else "Reverse wide shot of the {}.").format(area)


def public_prompt(episode):
    return {
        "id": episode["id"],
        "shots": [
            {
                "index": shot["index"],
                "content": shot["prompt"]["content"],
                "viewpoint": shot["prompt"]["viewpoint"],
            }
            for shot in episode["shots"]
        ],
    }


def render_public_prompt(value):
    def single_line(text):
        return re.sub(r"\s+", " ", str(text)).strip()

    return "\n".join(
        "Shot {index}: {viewpoint} {content}".format(
            index=shot["index"],
            content=single_line(shot["content"]),
            viewpoint=single_line(shot["viewpoint"]),
        )
        for shot in value["shots"]
    )


def _derived_shot_contracts(episode, template):
    return [
        {
            "index": shot["index"],
            "mentioned": shot["mentioned"],
            "expected_visible": expected_visible_subjects(
                episode, template, shot["index"]
            ),
            "probe": probe_subjects_for_shot(episode, template, shot["index"]),
            "probe_expectations": probe_expectations_for_shot(
                episode, template, shot["index"]
            ),
            "camera": shot["camera"],
            "required_content_prefix": next((entry_content_prefix(subject, template)
                for event in shot.get("events", []) if event["action"] == "enter"
                for subject in episode["subjects"] if subject["id"] == event["subject"]), None),
        }
        for shot in episode["shots"]
    ]


def _casting_system(config):
    return (
        "You verify and render a balanced cast for a controlled world-state benchmark. "
        "Copy every id, gender and clothing from casting_contract exactly. It is balanced "
        "across the dataset; do not infer gender, colors or appearance from the original "
        "literary characters, participant roles or seat labels. "
        "Return only the requested structured object with subjects {} in that order. "
        "For each subject, choose gender as exactly woman or man and choose one clothing "
        "phrase containing a controlled color and garment, such as mustard-yellow sweater. "
        "Use a simple garment from shirt, sweater, jacket, cardigan, blouse, hoodie, coat, "
        "turtleneck, vest, polo, pullover, blazer, sweatshirt, overshirt, tunic, top, tee, "
        "or t-shirt. "
        "The color must include at least one of: red, blue, green, yellow, orange, purple, "
        "pink, brown, black, white, gray, navy, teal, maroon, mustard, cobalt, emerald, "
        "olive, beige, cream, burgundy, or charcoal. "
        "Use a different clothing color for every subject. Do not include articles in the "
        "clothing field. Gender plus clothing color is the complete identity anchor. Do not "
        "add hair, facial features, age, glasses, accessories, names, personality, actions, "
        "seats, camera language, duration, timestamps, or generation settings."
    ).format(", ".join(_subject_ids(config["subject_count"])))


def _beat_planner_system(config):
    return (
        "You plan story-world beats for a controlled multi-shot world-state benchmark. "
        "Return exactly {} ordered shots. The supplied casting, layout, seats, camera "
        "plan, and per-shot mention contracts are fixed and cannot be changed. Every beat "
        "may assign actions only to the subjects listed in that shot's mentioned array. "
        "Never refer to another subject, even indirectly as a third person, listener, "
        "group, or everyone. Copy every supplied events array exactly. Events are frozen: "
        "enter means the named subject enters and takes that subject's established seat; "
        "exit means the named subject leaves that seat and exits; swap means the two named "
        "subjects exchange their established seats. State each supplied event explicitly in "
        "that shot's beat and invent no other entry, exit, or seat change. When a shot has a "
        "non-empty events array, begin its beat with that event and explicitly name every "
        "event subject before adding any conversational action. Follow the supplied task_rules "
        "literally. When task_rules supplies required_event_prefix, copy that prefix verbatim at "
        "the beginning of Shot 2; do not paraphrase, shorten, or replace it. Use the supplied "
        "skeleton as the narrative basis. Preserve its concrete topic, disagreement or "
        "question; do not flatten everything into an unspecified conversation. Adapt the "
        "real interaction to the frozen task; remove original events not in the contracts. "
        "All additional actions must be conversational. Adapt cooking or food delivery in "
        "the source to discussion OF that plan, never starting the work, deciding to deliver "
        "food or asking to continue chopping. Prefer asks about the recipe / explains the "
        "plan / discusses sharing breakfast. Keep the PUBLIC story at the level of an ordinary topic such as a riddle, a dinner "
        "invitation, a holiday plan or breakfast chores. These are examples, not interchangeable "
        "topics: choose the closest ordinary equivalent of the supplied skeleton and keep it "
        "consistent across shots. A question about a puzzling story stays about that story's "
        "puzzle; do not turn it into an unrelated holiday trip. Preserve the concrete question "
        "or disagreement, not merely a generic keyword such as story or conversation. Do not retell fictional specifics, "
        "fantastical objects or distinctive comparisons. Do not use analysis jargon such as "
        "premise, narrative structure or physical logic. "
        "State changes added for the experiment are adaptations, not source facts. Each beat "
        "must contain only plot-relevant actions in plain verbs such as tells, asks, answers, "
        "or replies. Do not add posture, gaze, facial expressions, hand gestures, prop handling, "
        "or decorative adverbs. Do not list the other contracted subjects again merely as the "
        "audience or recipients of an action. In Shot 1, only Subject A performs a plot "
        "action; do not mention the other subjects in that beat, because the renderer will still "
        "establish their identities and seats from the mention contract. Keep the remaining "
        "exchange to a direct question, answer, or reply without explanatory qualifiers. Beats "
        "contain no appearance redesign, camera, "
        "framing, duration, timestamp, or generation language."
    ).format(config["shot_count"])


def _story_task_rules(config):
    forbidden_opening_ids = ", ".join(
        "Subject {}".format(subject_id)
        for subject_id in _subject_ids(config["subject_count"])[1:]
    )
    rules = {
        "opening": (
            "Shot 1 is one concise sentence beginning with 'Subject A'. It must not "
            "contain any of these tokens: {}."
        ).format(forbidden_opening_ids),
        "event_shot": (
            "Shot 2 begins by expressing its supplied event and naming every event "
            "subject."
        ),
        "final": (
            "The final beat names only subjects in its mentioned array and does not "
            "restate any probe subject or final state."
        ),
    }
    required_event_prefix = {
        "person_entry": "Subject B enters and takes the established seat.",
        "person_exit": "Subject B leaves the established seat and exits the scene.",
        "position_swap": (
            "Subject A and Subject B exchange their established seats."
        ),
    }.get(config["task"])
    if required_event_prefix:
        if config.get("dataset_version") == "3.1" and config["task"] == "person_entry":
            required_event_prefix = "Subject B enters and takes the empty place."
        rules["required_event_prefix"] = required_event_prefix
    return rules


def _renderer_system(config):
    system = (
        "You write only the Content field for exactly {} approved benchmark shots. Camera "
        "Viewpoint text is supplied deterministically elsewhere. For each shot, mention "
        "every subject in its mentioned array using that subject's gender and clothing color, "
        "and mention no other subject. Use the shortest natural wording that preserves the "
        "required facts, not cinematic prose. Keep the topic to a short familiar label "
        "such as a riddle or dinner invitation, not the original literary particulars. "
        "Do not retell a story within the story or add analysis jargon such as premise. "
        "State each contracted subject's identity anchor "
        "exactly once per shot. Begin Shot 1 with the supplied public_intro verbatim as a short "
        "standalone scene introduction. Only after that sentence, introduce the subjects. Then "
        "combine each identity, named seat, and any approved action "
        "within the same introduction; never repeat an identity to state that person's action. "
        "Subjects without an approved Shot 1 action receive only identity and seat; do not invent "
        "actions for them. "
        "Use the supplied compact seat labels without expanding them into landmarks. The scene "
        "introduction supplies only the venue; do not add any other background description or "
        "repeat geometry already expressed by the fixed Viewpoint. Later shots "
        "describe only the contracted subjects and their approved plot-relevant action. Never "
        "add posture, gaze, expressions, hand gestures, prop handling, or decorative adverbs. "
        "Never invent hair, stable facial features, age, or accessory details. Render each "
        "supplied event explicitly and concisely. When derived_contracts gives a non-null "
        "required_content_prefix, copy it verbatim at the beginning of that Content. This "
        "sentence establishes both entering and sitting; use pronouns if that subject has "
        "another action instead of repeating the anchor. For exit, "
        "state that the subject leaves the named seat and exits the venue; use swaps or "
        "exchanges for swap. An event sentence must include the "
        "exact compact seat label for every changing subject. Do not add people, state changes, "
        "seat changes, camera language, or facts not present in the plan. The final shot "
        "must not repeat any seat assignment or state answer, even for its mentioned subject. "
        "It deliberately omits every subject listed in probe, whether that subject is expected "
        "present or absent. Never name, describe, count, or indirectly refer to an omitted "
        "probe subject. Do not say everyone or all three remain present. Never include "
        "durations, timestamps, frame rate, resolution, or generation parameters."
    ).format(config["shot_count"])
    if config.get("dataset_version") == "3.1":
        system = system.replace(
            "state that the subject leaves the named seat and exits the venue; use swaps or "
            "exchanges for swap. An event sentence must include the "
            "exact compact seat label for every changing subject.",
            "state that the subject leaves their seat and exits the venue. For swap, name the "
            "two identities and say they exchange seats. Updates must NOT repeat any landmark "
            "or named-seat label: refer to the subjects' actual original places. Entry takes "
            "the unique empty place."
        )
        if config["task"] == "person_entry":
            system += " In Shot 1 add 'There is one empty place.' Do not introduce the arriving subject yet."
    return system


AUDITOR_SYSTEM = (
    "You are the strict final auditor for a controlled world-state benchmark. "
    "The supplied layout and camera presets are construction contracts, not proof of actual "
    "video compliance. For every shot, compare "
    "mentioned, expected_visible, probe, Content, and Viewpoint. Content must clearly "
    "describe exactly the subjects in mentioned and no others. Subject identity must use "
    "only the approved gender and clothing-color anchors; reject invented hair, stable facial "
    "features, age, or accessory details. Each identity anchor may appear only once per shot. "
    "Shot 1 must begin with layout.public_intro before any subject is introduced. This exact "
    "short scene sentence has already passed deterministic validation; do not remove or expand it. "
    "Shot 1 seat-label presence, exact wording, and compactness have already passed a "
    "deterministic validator. The public labels are the natural-language values in layout.seats, "
    "not internal keys such as window_left. Do not report an issue merely because these required "
    "seat labels appear. Report a seat issue only when Content clearly pairs a subject with a "
    "different subject's supplied seat. Every subject in Shot 1's mentioned array must be introduced "
    "once with an identity anchor and seat; these required introductions are not a redundant audience "
    "list and must never be rejected merely because only Subject A acts. In an opening "
    "introduction, sits/seated/is at a named seat ESTABLISHES a required location; it is "
    "not decorative posture and is allowed for EVERY initially present subject. Entry's "
    "enters-and-sits sentence is also a required state event, never decoration. Reject repeated anchors or "
    "actual audience lists added after those required introductions. Content "
    "must contain only plot-relevant actions; "
    "reject decorative posture, gaze, expressions, hand gestures, prop handling, and adverbs. "
    "Physical cooking, serving or cleaning must not be introduced; people may discuss these "
    "topics while seated. Do not accept final wording that initiates an unplanned physical "
    "task or implies the speaker is alone. "
    "Opening and final wide views "
    "must state their viewpoint origin and seat coverage. Intermediate partial views need "
    "only a short focal framing phrase; do not demand lens, height, angle, or crop parameters. "
    "Compare the story to source.excerpt and skeleton: retain a recognizable topic or interaction, "
    "but allow the documented task adaptation and new human cast. Reject source-attribution "
    "claims invented by the writer. Every frozen entry, exit, or swap event must be explicit in that shot's Content and use "
    "the supplied compact seat labels. A subject in probe must not be named, described, counted, "
    "or indirectly mentioned in final Content. Read probe_expectations for its required final "
    "presence and seat. The score checks count and positions for ALL occupants in the final "
    "wide, not just unmentioned probes. Mentioned subjects may act without repeating their "
    "seat. An absent probe correctly does not appear in expected_visible; do not "
    "treat that as an inconsistency. The final Viewpoint must cover every probe subject's "
    "established or expected seat. This deliberate omission is the benchmark test, not an error. "
    "Reject duration, timestamp, frame-rate, resolution, or generation language. "
    "If passed is true, issues must be empty. Classify a broken story beat as story, an "
    "ambiguous or inconsistent template/view as camera, and public wording as prompt."
)


def _auditor_system(config):
    if config.get("dataset_version") != "3.1":
        return AUDITOR_SYSTEM
    return AUDITOR_SYSTEM.replace(
        "Opening and final wide views must state their viewpoint origin and seat coverage.",
        "Only the opening wide states its origin and layout. The final wide uses a standard "
        "reverse or top-down instruction without any seat inventory or required orientation "
        "landmarks. Naming the interaction area itself (table, coffee table, kitchen island) "
        "is explicitly allowed and necessary; it is NOT a forbidden landmark. For example, "
        "'Reverse wide shot of the coffee table.' and 'Top-down wide shot directly above the "
        "kitchen island.' are allowed. Reject required shelf/window/seat-coverage lists, "
        "not the name of the filmed interaction area."
    ).replace(
        "Every frozen entry, exit, or swap event must be explicit in that shot's Content and use "
        "the supplied compact seat labels.",
        "Every frozen event must be explicit. Updates name the participating identities, "
        "never compact seat labels or landmarks. Entry takes the unique empty place established "
        "in Shot 1; Exit leaves the seat and venue; Swap exchanges the named subjects' seats. "
        "Naming both people followed by 'exchange seats' or 'swap seats' fully specifies the "
        "swap. Do NOT require restating either person's original or destination position."
    ) + (" Actual opening screenshots, not prescribed identity-to-seat assignments, will supply "
         "the evaluation reference. Check narrative continuity against the skeleton: ordinary "
         "adaptation is allowed, but changing its discussion into an unrelated topic is not. "
         "A shared generic keyword alone does not establish source fidelity.")


def _generate_valid(
    *,
    stage,
    model,
    schema_name,
    schema,
    system,
    base_input,
    temperature,
    validate,
    trace,
    request_structured,
    feedback=None
):
    errors = list(feedback or [])
    previous_invalid_output = None
    for _attempt in range(3):
        input_value = dict(base_input)
        if errors:
            input_value["revision_required"] = errors
        if previous_invalid_output is not None:
            input_value["previous_invalid_output"] = previous_invalid_output
        value = request_structured(
            stage=stage,
            model=model,
            schema_name=schema_name,
            schema=schema,
            system=system,
            input_value=input_value,
            temperature=temperature,
            trace=trace,
        )
        errors = validate(value)
        if not errors:
            return value
        previous_invalid_output = value
    raise RuntimeError("{} failed validation: {}".format(stage, " ".join(errors)))


def build_prompt_pipeline(
    options=None,
    *,
    request_structured=None,
    environ: Optional[Mapping[str, str]] = None,
    on_stage=None,
    resume_journal=None,
):
    """Build one prompt episode through five independent LLM stages."""
    options = options or PipelineOptions()
    env = environ if environ is not None else os.environ
    template = get_layout_template(options.layout)
    template_errors = validate_layout_template(template)
    if template_errors:
        raise ValueError("Invalid layout template: {}".format(" ".join(template_errors)))

    config = {
        "task": options.task,
        "scene": template["scene_type"],
        "layout": template["id"],
        "viewpoint_mode": (
            "overhead"
            if template["cameras"][template["grammar"]["probe_camera"]].get(
                "view_direction"
            )
            == "overhead"
            else "reverse_axis"
        ),
        "subject_count": len(template["seat_order"]),
        "shot_count": options.shot_count,
    }
    if template.get("version"):
        config["dataset_version"] = template["version"]
    if config["task"] not in TASK_TYPES:
        raise ValueError(
            "Unknown task type {}. Choose one of: {}.".format(
                config["task"], ", ".join(TASK_TYPES)
            )
        )
    if options.subject_count and options.subject_count != config["subject_count"]:
        raise ValueError(
            "Layout {} supports exactly {} subjects.".format(
                template["id"], config["subject_count"]
            )
        )
    if config["shot_count"] < 3:
        raise ValueError("shot_count must be at least 3.")

    provider = env.get("PROMPT_PROVIDER", "openrouter").strip().lower()
    if provider not in {"openrouter", "vapi"}:
        raise ValueError("PROMPT_PROVIDER must be openrouter or vapi.")
    prefix = provider.upper()
    default_model = (
        options.model
        or env.get(prefix + "_PROMPT_MODEL")
        or ("gpt-5.6-sol" if provider == "vapi" else "google/gemini-3.7-flash")
    )
    models = {
        "source_abstraction": options.skeleton_model
        or env.get(prefix + "_SKELETON_MODEL")
        or default_model,
        "subject_casting": options.casting_model
        or env.get(prefix + "_CAST_MODEL")
        or default_model,
        "story_planning": options.story_model
        or env.get(prefix + "_STORY_MODEL")
        or default_model,
        "prompt_rendering": options.render_model
        or env.get(prefix + "_RENDER_MODEL")
        or default_model,
        "prompt_audit": options.audit_model
        or env.get(prefix + "_AUDIT_MODEL")
        or ("gpt-5.6-luna" if provider == "vapi" else "openai/gpt-5.6-luna"),
    }

    if request_structured is None:
        client = OpenRouterClient(
            env.get(prefix + "_API_KEY", ""),
            site_url=env.get("OPENROUTER_SITE_URL") if provider == "openrouter" else None,
            provider=provider,
            base_url=env.get("VAPI_BASE_URL") if provider == "vapi" else None,
            timeout=int(env.get("VAPI_TIMEOUT_SECONDS", "240")) if provider == "vapi" else 120,
        )
        request_structured = client.complete

    trace, journal = [], []
    underlying_request = request_structured
    replay = list(resume_journal or [])
    replay_index = 0

    def recorded_request(**kwargs):
        nonlocal replay_index
        request_record = {key: kwargs[key] for key in (
            "stage", "model", "schema_name", "schema", "system", "input_value", "temperature"
        )}
        reused = False
        if replay_index < len(replay):
            cached = replay[replay_index]
            metadata = cached.get("response_metadata") or {}
            if (all(cached.get(k) == v for k, v in request_record.items())
                    and "output" in cached and metadata
                    and metadata.get("provider", "openrouter") == provider
                    and (provider != "vapi" or metadata.get("endpoint") ==
                         env.get("VAPI_BASE_URL", "https://api.gpt.ge/v1").rstrip("/") + "/chat/completions")):
                value = copy.deepcopy(cached["output"])
                trace.append(copy.deepcopy(metadata))
                replay_index += 1
                reused = True
            else:
                # Only reuse an exact matching prefix; never search later stages.
                replay_index = len(replay)
        if not reused:
            value = underlying_request(**kwargs)
        journal.append(request_record)
        if reused:
            journal[-1]["reused"] = True
        journal[-1]["output"] = value
        if trace and trace[-1].get('stage') == kwargs['stage']:
            journal[-1]['response_metadata'] = dict(trace[-1])
        if on_stage:
            on_stage(journal)
        return value

    request_structured = recorded_request
    if options.source:
        raise ValueError("Unattributed source text is no longer accepted. Select a verified --source-id.")
    source = select_source(config, options.source_id)
    source["archetype"] = options.archetype or template["archetype"]
    source["adaptation"] = (
        "The excerpt supplies the topic and interaction. Human cast, venue, seats and "
        "task-specific entry/exit/swap are controlled experimental adaptations, not claims about the original."
    )
    contracts = build_shot_contracts(
        template, config["shot_count"], config["task"]
    )

    skeleton = _generate_valid(
        stage="source_abstraction",
        model=models["source_abstraction"],
        schema_name="story_skeleton",
        schema=skeleton_schema(),
        system=(
            "Read the supplied real literary excerpt and abstract its actual interaction. "
            "Copy source.id into source_id and the archetype exactly. Keep its concrete "
            "topic and question or disagreement in a compact premise and interaction_arc. "
            "Use at least one supplied topic term naturally. Do not invent a task event in "
            "the source: the next stage separately adapts it to the experimental trajectory. "
            "Do not include character names, quotations, dialogue, "
            "mood, performance details, props, "
            "scenic embellishment, source wording, shot divisions, camera instructions, or "
            "duration language. A later stage will map "
            "this skeleton to {} shots."
        ).format(config["shot_count"]),
        base_input={"source": source},
        temperature=0.5,
        validate=lambda value: validate_skeleton(
            value, source["archetype"], config["task"], source=source
        ),
        trace=trace,
        request_structured=request_structured,
    )

    casting = _generate_valid(
        stage="subject_casting",
        model=models["subject_casting"],
        schema_name="subject_casting",
        schema=casting_schema(config),
        system=_casting_system(config),
        base_input={
            "skeleton": skeleton,
            "scene": template["scene"],
            "subject_ids": _subject_ids(config["subject_count"]),
            "casting_contract": casting_contract(config),
        },
        temperature=0.5,
        validate=lambda value: validate_casting(value, config),
        trace=trace,
        request_structured=request_structured,
    )

    beat_plan = _generate_valid(
        stage="story_planning",
        model=models["story_planning"],
        schema_name="story_beats",
        schema=beat_plan_schema(config),
        system=_beat_planner_system(config),
        base_input={
            "skeleton": skeleton,
            "casting": casting,
            "source_topic_terms": source["topic_terms"],
            "layout": {
                "scene": template["scene"],
                "public_intro": template["public_intro"],
                "seats": template["seats"],
            },
            "shot_contracts": contracts,
            "task_rules": _story_task_rules(config),
        },
        temperature=0.2,
        validate=lambda value: validate_beat_plan(value, config, contracts) + source_topic_errors(value, source),
        trace=trace,
        request_structured=request_structured,
    )

    episode = compile_episode(
        options.episode_id,
        config["task"],
        template,
        casting,
        beat_plan,
        contracts,
    )
    episode_errors = validate_compiled_episode(episode, template)
    if episode_errors:
        raise RuntimeError("Compiled episode failed: {}".format(" ".join(episode_errors)))

    content_prompt = _generate_valid(
        stage="prompt_rendering",
        model=models["prompt_rendering"],
        schema_name="content_prompt",
        schema=content_prompt_schema(config),
        system=_renderer_system(config),
        base_input={
            "source_topic_terms": source["topic_terms"],
            "layout": {
                "scene": template["scene"],
                "public_intro": template["public_intro"],
                "seats": template["seats"],
            },
            "subjects": episode["subjects"],
            "shots": episode["shots"],
            "derived_contracts": _derived_shot_contracts(episode, template),
        },
        temperature=0.3,
        validate=lambda value: validate_prompt(attach_prompt(episode, value, template)) + source_topic_errors(value, source),
        trace=trace,
        request_structured=request_structured,
    )
    episode = attach_prompt(episode, content_prompt, template)

    audits = []
    audit = None
    for round_index in range(1, 4):
        audit = request_structured(
            stage="prompt_audit",
            model=models["prompt_audit"],
            schema_name="prompt_audit",
            schema=audit_schema(),
            system=_auditor_system(config),
            input_value={
                "source": source,
                "skeleton": skeleton,
                "layout": template,
                "episode": episode,
                "derived_contracts": _derived_shot_contracts(episode, template),
                "public_prompt": public_prompt(episode),
            },
            temperature=None,
            trace=trace,
        )
        audits.append({"round": round_index, **audit})
        if audit.get("passed") and not audit.get("issues"):
            break

        issues = audit.get("issues") or []
        if any(issue.get("stage") == "camera" for issue in issues):
            raise RuntimeError(
                "Approved layout template failed camera audit: {}".format(
                    " ".join(issue.get("message", "") for issue in issues)
                )
            )

        if round_index == 3:
            # Do not pay for a repair that cannot receive its required independent audit.
            break

        story_issues = [
            issue.get("message", "")
            for issue in issues
            if issue.get("stage") == "story"
        ]
        if story_issues:
            beat_plan = _generate_valid(
                stage="story_repair",
                model=models["story_planning"],
                schema_name="story_beats",
                schema=beat_plan_schema(config),
                system=_beat_planner_system(config),
                base_input={
                    "skeleton": skeleton,
                    "casting": casting,
                    "source_topic_terms": source["topic_terms"],
                    "layout": {
                        "scene": template["scene"],
                        "seats": template["seats"],
                    },
                    "shot_contracts": contracts,
                    "task_rules": _story_task_rules(config),
                    "previous_beat_plan": beat_plan,
                },
                temperature=0.2,
                validate=lambda value: validate_beat_plan(value, config, contracts) + source_topic_errors(value, source),
                trace=trace,
                request_structured=request_structured,
                feedback=story_issues,
            )
            episode = compile_episode(
                options.episode_id,
                config["task"],
                template,
                casting,
                beat_plan,
                contracts,
            )

        content_prompt = _generate_valid(
            stage="prompt_repair",
            model=models["prompt_rendering"],
            schema_name="content_prompt",
            schema=content_prompt_schema(config),
            system=_renderer_system(config),
            base_input={
                "source_topic_terms": source["topic_terms"],
                "layout": {
                    "scene": template["scene"],
                    "public_intro": template["public_intro"],
                    "seats": template["seats"],
                },
                "subjects": episode["subjects"],
                "shots": episode["shots"],
                "derived_contracts": _derived_shot_contracts(episode, template),
                "previous_prompt": content_prompt,
            },
            temperature=0.1,
            validate=lambda value: validate_prompt(attach_prompt(episode, value, template)) + source_topic_errors(value, source),
            trace=trace,
            request_structured=request_structured,
            feedback=[issue.get("message", "") for issue in issues],
        )
        episode = attach_prompt(episode, content_prompt, template)

    if not audit or not audit.get("passed") or audit.get("issues"):
        messages = [issue.get("message", "") for issue in (audit or {}).get("issues", [])]
        raise RuntimeError("Prompt audit failed: {}".format(" ".join(messages)))

    public_value = public_prompt(episode)
    return {
        "episode": episode,
        "annotations": build_annotations(episode, template, source),
        "public_prompt": public_value,
        "rendered_prompt": render_public_prompt(public_value),
        "run": {
            "version": template.get("version", DATASET_VERSION),
            "source": source,
            "config": config,
            "case_signature": case_signature(config),
            "models": models,
            "provider": provider,
            "stage_outputs": {
                "source_abstraction": skeleton,
                "subject_casting": casting,
                "story_planning": beat_plan,
                "prompt_rendering": content_prompt,
                "prompt_audit": audits,
            },
            "trace": trace,
            "request_journal": journal,
        },
    }
