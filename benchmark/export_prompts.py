#!/usr/bin/env python3
"""Export a fully validated prompt collection without LLM or video calls."""

import argparse
import json
from pathlib import Path

from validate_matrix import validate_collection
from worldline.artifacts import write_json


def export_collection(root, *, overwrite=False):
    root = Path(root)
    manifest_path = root / "core_matrix.manifest.json"
    report = validate_collection(manifest_path, root)
    if report["errors"]:
        raise ValueError("Cannot export an incomplete or invalid collection: " + "; ".join(report["errors"][:5]))
    destinations = [root / "public_prompts.json", root / "prompts.md"]
    if not overwrite and any(p.exists() for p in destinations):
        raise FileExistsError("Exports already exist; pass --overwrite to replace only the exports.")
    manifest = json.loads(manifest_path.read_text())
    records = []
    lines = ["# WorldLine Core prompts", "", "Version " + manifest["version"] + ". " +
             str(len(manifest["cases"])) + " cases. Candidate dataset; human review remains pending.", "",
             "Each block is the exact public model input. No hidden annotations are included.", ""]
    for case in manifest["cases"]:
        folder = root / (case.get("artifact_id") or case["id"])
        public = json.loads((folder / "prompt.public.json").read_text())
        prompt = (folder / "prompt.txt").read_text().strip()
        records.append({"id": case["id"], "task_type": case["task"], "scene": case["scene"],
                        "subject_count": case["subject_count"], "viewpoint_mode": case["viewpoint_mode"],
                        "shots": public["shots"]})
        lines.extend(["## " + case["id"], "", "{} · {} · {} subjects · {} shots · {}".format(
            case["task"], case["scene"], case["subject_count"], case["shot_count"], case["viewpoint_mode"]),
            "", "```text", prompt, "```", ""])
    write_json(destinations[0], {"benchmark": "WorldLine", "version": manifest["version"],
               "case_count": len(records), "review_status": manifest["review_status"], "cases": records})
    destinations[1].write_text("\n".join(lines), encoding="utf-8")
    return destinations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parent / "outputs/v3.1")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    for path in export_collection(args.output_root, overwrite=args.overwrite):
        print(path.resolve())


if __name__ == "__main__":
    main()
