"""Verified literary excerpts used as actual input to source abstraction."""

import hashlib
import json
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "sources" / "catalog.json"


def load_catalog():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    for source in data["sources"]:
        actual = hashlib.sha256(source["excerpt"].encode("utf-8")).hexdigest()
        if actual != source["excerpt_sha256"] or not source["url"].startswith("https://"):
            raise ValueError("Invalid source provenance: " + source["id"])
    return data["sources"]


def select_source(config, source_id=None):
    catalog = load_catalog()
    if source_id:
        matches = [s for s in catalog if s["id"] == source_id]
    else:
        matches = [s for s in catalog if config["scene"] in s["scenes"]]
        # Hold source fixed across camera modes and counts for each task pair.
        from .balance import TASKS
        if config.get("dataset_version") in {"3.0", "3.1"}:
            from .balance import SCENES
            index = SCENES.index(config["scene"]) + TASKS.index(config["task"]) + config["subject_count"] - 3
        else:
            index = TASKS.index(config["task"])
        matches = [matches[index % len(matches)]]
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous source: {}".format(source_id))
    return dict(matches[0])
