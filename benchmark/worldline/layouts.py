"""Approved geometry templates for WorldLine prompt construction."""

from copy import deepcopy


LAYOUT_TEMPLATES = {
    "cafe_rect_table_3_v1": {
        "id": "cafe_rect_table_3_v1",
        "scene_type": "café",
        "archetype": "café conversation",
        "story_venue": "a café seating area",
        "scene": (
            "A quiet café seating area with one rectangular wooden table running parallel "
            "to a window. A tall floor plant stands directly behind the table's plant-side "
            "short end, the café counter lies beyond the opposite short end, and an open "
            "aisle runs along the side opposite the window. No other people are nearby."
        ),
        "public_intro": (
            "Inside a café, a rectangular table stands beside the window, with a tall "
            "floor plant near one end and the counter beyond the other."
        ),
        "seats": {
            "window_left": "the plant-side window seat",
            "window_right": "the counter-side window seat",
            "table_left_end": "the plant-end seat",
        },
        "seat_order": ["window_left", "window_right", "table_left_end"],
        "cameras": {
            "establish_counter_end": {
                "framing": "wide",
                "view_direction": "counter_to_plant",
                "public_view": (
                    "Wide establishing shot from the counter end, looking lengthwise along the "
                    "rectangular table toward the floor plant, with the full table and all three "
                    "seats in frame."
                ),
                "visible_seats": ["window_left", "window_right", "table_left_end"],
            },
            "partial_window_pair": {
                "framing": "two_shot",
                "public_view": (
                    "Medium two-shot from the aisle side, centered on the two adjacent "
                    "window-side seats."
                ),
                "visible_seats": ["window_left", "window_right"],
            },
            "partial_window_left": {
                "framing": "close_up",
                "public_view": (
                    "Close-up from the aisle side, centered on the person in the plant-side "
                    "window seat."
                ),
                "visible_seats": ["window_left"],
            },
            "partial_window_right": {
                "framing": "close_up",
                "public_view": (
                    "Close-up from the aisle side, centered on the person in the counter-side "
                    "window seat."
                ),
                "visible_seats": ["window_right"],
            },
            "probe_plant_end": {
                "framing": "wide",
                "view_direction": "plant_to_counter",
                "public_view": (
                    "Reverse wide shot from behind the plant-end seat, looking lengthwise along "
                    "the table toward the café counter, with the entire table, the plant-end "
                    "seat, and both window-side seats in frame."
                ),
                "visible_seats": ["window_left", "window_right", "table_left_end"],
            },
        },
        "grammar": {
            "opening_camera": "establish_counter_end",
            "partial_cameras": [
                "partial_window_pair",
                "partial_window_left",
                "partial_window_right",
            ],
            "probe_camera": "probe_plant_end",
            "probe_focus_seats": ["window_left", "window_right"],
        },
    }
}


_CAFE_OVERHEAD_TEMPLATE = deepcopy(LAYOUT_TEMPLATES["cafe_rect_table_3_v1"])
_CAFE_OVERHEAD_TEMPLATE["id"] = "cafe_rect_table_3_overhead_v1"
_CAFE_OVERHEAD_TEMPLATE["cameras"]["probe_overhead"] = {
    "framing": "wide",
    "view_direction": "overhead",
    "public_view": (
        "Top-down wide shot from directly above the rectangular table, centered on the "
        "tabletop, with the full table, the plant-end seat, and both window-side seats "
        "in frame."
    ),
    "visible_seats": ["window_left", "window_right", "table_left_end"],
}
_CAFE_OVERHEAD_TEMPLATE["grammar"]["probe_camera"] = "probe_overhead"
LAYOUT_TEMPLATES[_CAFE_OVERHEAD_TEMPLATE["id"]] = _CAFE_OVERHEAD_TEMPLATE
del _CAFE_OVERHEAD_TEMPLATE


def _register_scene_layouts(spec, subject_counts=(3, 4)):
    """Expand one declarative scene into 3/4-person reverse and overhead templates."""
    for subject_count in subject_counts:
        seats = dict(spec["seats"][subject_count])
        seat_order = list(seats)
        coverage = spec["coverage"][subject_count]
        base_id = "{}_{}_v1".format(spec["id_prefix"], subject_count)
        reverse_camera = "probe_reverse"
        reverse_template = {
            "id": base_id,
            "scene_type": spec["scene_type"],
            "archetype": spec["archetype"],
            "story_venue": spec["story_venue"],
            "scene": spec["scene"],
            "public_intro": spec["public_intro"],
            "seats": seats,
            "seat_order": seat_order,
            "cameras": {
                "establish": {
                    "framing": "wide",
                    "view_direction": spec["opening_direction"],
                    "public_view": spec["opening_view"].format(coverage=coverage),
                    "visible_seats": seat_order,
                },
                "partial_pair": {
                    "framing": "two_shot",
                    "public_view": spec["pair_view"],
                    "visible_seats": seat_order[:2],
                },
                "partial_first": {
                    "framing": "close_up",
                    "public_view": spec["first_view"],
                    "visible_seats": [seat_order[0]],
                },
                "partial_second": {
                    "framing": "close_up",
                    "public_view": spec["second_view"],
                    "visible_seats": [seat_order[1]],
                },
                reverse_camera: {
                    "framing": "wide",
                    "view_direction": spec["reverse_direction"],
                    "public_view": spec["reverse_view"].format(coverage=coverage),
                    "visible_seats": seat_order,
                },
            },
            "grammar": {
                "opening_camera": "establish",
                "partial_cameras": [
                    "partial_pair",
                    "partial_first",
                    "partial_second",
                ],
                "probe_camera": reverse_camera,
                "probe_focus_seats": seat_order[:2],
            },
        }
        LAYOUT_TEMPLATES[base_id] = reverse_template

        overhead_template = deepcopy(reverse_template)
        overhead_template["id"] = "{}_{}_overhead_v1".format(
            spec["id_prefix"], subject_count
        )
        overhead_template["cameras"]["probe_overhead"] = {
            "framing": "wide",
            "view_direction": "overhead",
            "public_view": spec["overhead_view"].format(coverage=coverage),
            "visible_seats": seat_order,
        }
        overhead_template["grammar"]["probe_camera"] = "probe_overhead"
        LAYOUT_TEMPLATES[overhead_template["id"]] = overhead_template


_SCENE_SPECS = [
    {
        "id_prefix": "cafe_rect_table",
        "scene_type": "café",
        "archetype": "café conversation",
        "story_venue": "a café seating area",
        "scene": (
            "A café seating area with a rectangular table parallel to a window. A tall "
            "floor plant marks one short end, the counter lies beyond the other, and an "
            "open aisle runs opposite the window. No other people are nearby."
        ),
        "public_intro": (
            "Inside a café, a rectangular table stands beside the window, with a tall "
            "floor plant near one end and the counter beyond the other."
        ),
        "seats": {
            3: [
                ("window_left", "the plant-side window seat"),
                ("window_right", "the counter-side window seat"),
                ("table_left_end", "the plant-end seat"),
            ],
            4: [
                ("window_left", "the plant-side window seat"),
                ("window_right", "the counter-side window seat"),
                ("aisle_left", "the plant-side aisle seat"),
                ("aisle_right", "the counter-side aisle seat"),
            ],
        },
        "coverage": {
            3: "both window-side seats and the plant-end seat",
            4: "both window-side seats and both aisle-side seats",
        },
        "opening_direction": "counter_to_plant",
        "reverse_direction": "plant_to_counter",
        "opening_view": (
            "Wide establishing shot from the counter end, looking lengthwise along the "
            "rectangular table toward the floor plant, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the plant end, looking lengthwise along the rectangular "
            "table toward the café counter, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the rectangular table, centered on the "
            "tabletop, with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the aisle side, centered on the two adjacent window-side seats."
        ),
        "first_view": (
            "Close-up from the aisle side, centered on the person in the plant-side window seat."
        ),
        "second_view": (
            "Close-up from the aisle side, centered on the person in the counter-side window seat."
        ),
    },
    {
        "id_prefix": "meeting_room_table",
        "scene_type": "meeting room",
        "archetype": "meeting-room discussion",
        "story_venue": "a meeting room",
        "scene": (
            "A meeting room with a rectangular conference table between a presentation "
            "screen and a glass door. Windows line one side and a clear walkway runs along "
            "the opposite side. No other people are present."
        ),
        "public_intro": (
            "Inside a meeting room, a rectangular conference table stands between a "
            "presentation screen and a glass door, with windows along one side."
        ),
        "seats": {
            3: [
                ("window_screen", "the screen-side window seat"),
                ("window_door", "the door-side window seat"),
                ("screen_end", "the screen-end seat"),
            ],
            4: [
                ("window_screen", "the screen-side window seat"),
                ("window_door", "the door-side window seat"),
                ("walkway_screen", "the screen-side walkway seat"),
                ("walkway_door", "the door-side walkway seat"),
            ],
        },
        "coverage": {
            3: "both window-side seats and the screen-end seat",
            4: "both window-side seats and both walkway-side seats",
        },
        "opening_direction": "door_to_screen",
        "reverse_direction": "screen_to_door",
        "opening_view": (
            "Wide establishing shot from the glass-door end, looking lengthwise along the "
            "conference table toward the presentation screen, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the presentation-screen end, looking lengthwise along "
            "the conference table toward the glass door, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the conference table, centered on the "
            "tabletop, with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the walkway side, centered on the two adjacent window-side seats."
        ),
        "first_view": (
            "Close-up from the walkway side, centered on the person in the screen-side window seat."
        ),
        "second_view": (
            "Close-up from the walkway side, centered on the person in the door-side window seat."
        ),
    },
    {
        "id_prefix": "living_room_seating",
        "scene_type": "living room",
        "archetype": "living-room conversation",
        "story_venue": "a living room",
        "scene": (
            "A living room with a two-seat sofa facing a low coffee table. A bookcase marks "
            "one side of the seating area and the doorway marks the opposite side. One or "
            "two armchairs complete the controlled arrangement."
        ),
        "public_intro": (
            "Inside a living room, a sofa and armchairs surround a low coffee table between "
            "a bookcase and the doorway."
        ),
        "seats": {
            3: [
                ("sofa_bookcase", "the bookcase-side sofa seat"),
                ("sofa_doorway", "the doorway-side sofa seat"),
                ("bookcase_chair", "the bookcase-side armchair"),
            ],
            4: [
                ("sofa_bookcase", "the bookcase-side sofa seat"),
                ("sofa_doorway", "the doorway-side sofa seat"),
                ("bookcase_chair", "the bookcase-side armchair"),
                ("doorway_chair", "the doorway-side armchair"),
            ],
        },
        "coverage": {
            3: "both sofa seats and the bookcase-side armchair",
            4: "both sofa seats and both armchairs",
        },
        "opening_direction": "doorway_to_bookcase",
        "reverse_direction": "bookcase_to_doorway",
        "opening_view": (
            "Wide establishing shot from the doorway side, looking across the coffee table "
            "toward the bookcase, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the bookcase side, looking across the coffee table "
            "toward the doorway, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the coffee table, centered on the "
            "seating arrangement, with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the coffee-table side, centered on the two adjacent sofa seats."
        ),
        "first_view": (
            "Close-up from the coffee-table side, centered on the person in the bookcase-side sofa seat."
        ),
        "second_view": (
            "Close-up from the coffee-table side, centered on the person in the doorway-side sofa seat."
        ),
    },
    {
        "id_prefix": "dining_room_table",
        "scene_type": "dining room",
        "archetype": "shared-meal conversation",
        "story_venue": "a dining room",
        "scene": (
            "A dining room with a rectangular table between a sideboard and patio doors. "
            "A window runs along one side and a clear serving aisle runs along the other. "
            "No other people are nearby."
        ),
        "public_intro": (
            "Inside a dining room, a rectangular table stands between a sideboard and patio "
            "doors, with a window along one side."
        ),
        "seats": {
            3: [
                ("window_sideboard", "the sideboard-side window seat"),
                ("window_patio", "the patio-side window seat"),
                ("sideboard_end", "the sideboard-end seat"),
            ],
            4: [
                ("window_sideboard", "the sideboard-side window seat"),
                ("window_patio", "the patio-side window seat"),
                ("aisle_sideboard", "the sideboard-side aisle seat"),
                ("aisle_patio", "the patio-side aisle seat"),
            ],
        },
        "coverage": {
            3: "both window-side seats and the sideboard-end seat",
            4: "both window-side seats and both aisle-side seats",
        },
        "opening_direction": "patio_to_sideboard",
        "reverse_direction": "sideboard_to_patio",
        "opening_view": (
            "Wide establishing shot from the patio-door end, looking lengthwise along the "
            "dining table toward the sideboard, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the sideboard end, looking lengthwise along the dining "
            "table toward the patio doors, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the dining table, centered on the "
            "tabletop, with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the aisle side, centered on the two adjacent window-side seats."
        ),
        "first_view": (
            "Close-up from the aisle side, centered on the person in the sideboard-side window seat."
        ),
        "second_view": (
            "Close-up from the aisle side, centered on the person in the patio-side window seat."
        ),
    },
    {
        "id_prefix": "seminar_room_table",
        "scene_type": "seminar room",
        "archetype": "small-group discussion",
        "story_venue": "a seminar room",
        "scene": (
            "A seminar room with a rectangular worktable between a pinboard and the entrance. "
            "A wall of windows lines one side and an open circulation strip lines the other."
        ),
        "public_intro": (
            "Inside a seminar room, a rectangular worktable stands between a pinboard and "
            "the entrance, with windows along one side."
        ),
        "seats": {
            3: [
                ("window_pinboard", "the pinboard-side window seat"),
                ("window_entrance", "the entrance-side window seat"),
                ("pinboard_end", "the pinboard-end seat"),
            ],
            4: [
                ("window_pinboard", "the pinboard-side window seat"),
                ("window_entrance", "the entrance-side window seat"),
                ("aisle_pinboard", "the pinboard-side aisle seat"),
                ("aisle_entrance", "the entrance-side aisle seat"),
            ],
        },
        "coverage": {
            3: "both window-side seats and the pinboard-end seat",
            4: "both window-side seats and both aisle-side seats",
        },
        "opening_direction": "entrance_to_pinboard",
        "reverse_direction": "pinboard_to_entrance",
        "opening_view": (
            "Wide establishing shot from the entrance end, looking lengthwise along the "
            "worktable toward the pinboard, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the pinboard end, looking lengthwise along the worktable "
            "toward the entrance, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the worktable, centered on the tabletop, "
            "with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the aisle side, centered on the two adjacent window-side seats."
        ),
        "first_view": (
            "Close-up from the aisle side, centered on the person in the pinboard-side window seat."
        ),
        "second_view": (
            "Close-up from the aisle side, centered on the person in the entrance-side window seat."
        ),
    },
    {
        "id_prefix": "board_game_table",
        "scene_type": "game room",
        "archetype": "board-game conversation",
        "story_venue": "a game room",
        "scene": (
            "A game room with a rectangular board-game table between a shelving unit and the "
            "doorway. A window lines one side and a clear aisle lines the opposite side."
        ),
        "public_intro": (
            "Inside a game room, a rectangular board-game table stands between a shelving "
            "unit and the doorway, with a window along one side."
        ),
        "seats": {
            3: [
                ("window_shelf", "the shelf-side window seat"),
                ("window_door", "the doorway-side window seat"),
                ("shelf_end", "the shelf-end seat"),
            ],
            4: [
                ("window_shelf", "the shelf-side window seat"),
                ("window_door", "the doorway-side window seat"),
                ("aisle_shelf", "the shelf-side aisle seat"),
                ("aisle_door", "the doorway-side aisle seat"),
            ],
        },
        "coverage": {
            3: "both window-side seats and the shelf-end seat",
            4: "both window-side seats and both aisle-side seats",
        },
        "opening_direction": "doorway_to_shelf",
        "reverse_direction": "shelf_to_doorway",
        "opening_view": (
            "Wide establishing shot from the doorway end, looking lengthwise along the game "
            "table toward the shelving unit, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the shelving-unit end, looking lengthwise along the game "
            "table toward the doorway, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the game table, centered on the tabletop, "
            "with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the aisle side, centered on the two adjacent window-side seats."
        ),
        "first_view": (
            "Close-up from the aisle side, centered on the person in the shelf-side window seat."
        ),
        "second_view": (
            "Close-up from the aisle side, centered on the person in the doorway-side window seat."
        ),
    },
    {
        "id_prefix": "kitchen_island",
        "scene_type": "kitchen",
        "archetype": "kitchen conversation",
        "story_venue": "a kitchen",
        "scene": (
            "A kitchen with a long rectangular island between a refrigerator wall and the "
            "sink area. Guest stools line one side and matching positions line the opposite "
            "side, leaving both short ends clear for cameras."
        ),
        "public_intro": (
            "Inside a kitchen, a long rectangular island stands between the refrigerator "
            "wall and the sink area, with stools arranged along its sides."
        ),
        "seats": {
            3: [
                ("guest_sink", "the sink-side guest stool"),
                ("guest_fridge", "the refrigerator-side guest stool"),
                ("sink_end", "the sink-end stool"),
            ],
            4: [
                ("guest_sink", "the sink-side guest stool"),
                ("guest_fridge", "the refrigerator-side guest stool"),
                ("cook_sink", "the sink-side cook stool"),
                ("cook_fridge", "the refrigerator-side cook stool"),
            ],
        },
        "coverage": {
            3: "both guest-side stools and the sink-end stool",
            4: "both guest-side stools and both cook-side stools",
        },
        "opening_direction": "refrigerator_to_sink",
        "reverse_direction": "sink_to_refrigerator",
        "opening_view": (
            "Wide establishing shot from the refrigerator end, looking lengthwise along the "
            "kitchen island toward the sink area, with {coverage} in frame."
        ),
        "reverse_view": (
            "Reverse wide shot from the sink end, looking lengthwise along the kitchen island "
            "toward the refrigerator wall, with {coverage} in frame."
        ),
        "overhead_view": (
            "Top-down wide shot from directly above the kitchen island, centered on the "
            "worktop, with {coverage} in frame."
        ),
        "pair_view": (
            "Medium two-shot from the cook side, centered on the two adjacent guest-side stools."
        ),
        "first_view": (
            "Close-up from the cook side, centered on the person at the sink-side guest stool."
        ),
        "second_view": (
            "Close-up from the cook side, centered on the person at the refrigerator-side guest stool."
        ),
    },
]


for _scene_spec in _SCENE_SPECS:
    if _scene_spec["id_prefix"] == "cafe_rect_table":
        _register_scene_layouts(_scene_spec, subject_counts=(4,))
    else:
        _register_scene_layouts(_scene_spec)

del _scene_spec


def layout_template_ids():
    """Return all approved layout IDs in stable order."""
    return sorted(LAYOUT_TEMPLATES)


def get_layout_template(template_id):
    """Return an isolated copy of one approved template."""
    if template_id.endswith(("_v3", "_v3_1")):
        from .core_v3 import revised_layout
        return revised_layout(template_id)
    try:
        return deepcopy(LAYOUT_TEMPLATES[template_id])
    except KeyError as exc:
        available = ", ".join(LAYOUT_TEMPLATES)
        raise ValueError(
            "Unknown layout template: {}. Available templates: {}.".format(
                template_id, available
            )
        ) from exc
