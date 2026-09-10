"""Balanced visual anchors, independent of narrative roles and camera mode."""

SCENES = ("café", "meeting room", "living room", "dining room", "seminar room", "game room", "kitchen")
TASKS = ("static_viewpoint_change", "person_entry", "person_exit", "position_swap")
COLORS = ("red", "blue", "green", "yellow", "orange", "purple", "white")
PATTERNS = ("0010", "0101", "0110", "1001", "1010", "1101", "0011")


def casting_contract(config):
    """A/B/C have 50/50 gender and equal color frequency within each task.

    The 14 scene/count cells form seven complementary gender pairs. Reverse and
    overhead use the same anchors; neither camera direction nor LLM preferences
    determine a subject's attributes.
    """
    cell = SCENES.index(config["scene"]) * 2 + config["subject_count"] - 3
    cell = (cell + 3 * TASKS.index(config["task"])) % 14
    pattern = PATTERNS[cell % 7]
    return [
        {
            "id": chr(65 + role),
            "gender": "woman" if (
                (SCENES.index(config["scene"]) + TASKS.index(config["task"])) % 2
                if role == 3 else (int(pattern[role % 4]) + cell // 7) % 2
            ) else "man",
            "clothing": COLORS[(cell + 2 * role) % 7] + " shirt",
        }
        for role in range(config["subject_count"])
    ]
