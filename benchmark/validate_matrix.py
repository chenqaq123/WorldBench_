#!/usr/bin/env python3
"""Validate a generated WorldLine matrix without calling an LLM."""

import argparse
from collections import Counter
import json
from pathlib import Path

from worldline.layouts import get_layout_template
from worldline.annotations import DATASET_VERSION, build_annotations, digest
from worldline.balance import casting_contract
from worldline.sources import load_catalog
from worldline.matrix import plan_core_matrix
from worldline.artifacts import write_json
from worldline.pipeline import (
    case_signature,
    public_prompt,
    render_public_prompt,
    validate_compiled_episode,
    validate_prompt,
    validate_unique_case_signatures,
    source_topic_errors,
)


REQUIRED_STAGES = {
    "source_abstraction",
    "subject_casting",
    "story_planning",
    "prompt_rendering",
    "prompt_audit",
}


def validate_collection(manifest_path, outputs_dir):
    manifest = json.loads(manifest_path.read_text())
    cases = manifest.get("cases") or []
    errors = []
    version = manifest.get("version")
    if version not in {DATASET_VERSION, "3.0", "3.1"}:
        errors.append("Manifest has an unsupported dataset version.")
    if manifest.get("case_count") != len(cases):
        errors.append("Manifest case_count differs from actual entries.")
    if version in {"3.0", "3.1"}:
        from worldline.core_v3 import plan_mixed_core
        planned = plan_mixed_core(version)
        for case in cases:
            expected = next((c for c in planned if c["id"] == case.get("id")), {})
            if any(case.get(k) != v for k, v in expected.items()):
                errors.append(case.get("id", "?") + ": differs from the v3 frozen design")
    else:
        planned = plan_core_matrix(shot_counts=manifest.get("filters", {}).get("shot_counts") or [3])
    if {case["id"] for case in cases} != {case["id"] for case in planned}:
        errors.append("Manifest does not cover the complete requested matrix.")
    sources = {source["id"]: source for source in load_catalog()}
    source_counts = Counter()
    role_genders = {}
    role_colors = {}
    signatures = []
    rendered_prompts = []
    distributions = {
        "task": Counter(),
        "scene": Counter(),
        "subject_count": Counter(),
        "viewpoint_mode": Counter(),
        "shot_count": Counter(),
    }

    for case in cases:
        if case.get("status") not in {"complete", "reused"}:
            errors.append(
                "{}: manifest status is {}".format(
                    case.get("id"), case.get("status")
                )
            )
            continue

        artifact_id = case.get("artifact_id") or case["id"]
        folder = outputs_dir / artifact_id
        try:
            episode = json.loads((folder / "episode.internal.json").read_text())
            public = json.loads((folder / "prompt.public.json").read_text())
            run = json.loads((folder / "run.json").read_text())
            annotation = json.loads((folder / "annotations.hidden.json").read_text())
            prompt_text = (folder / "prompt.txt").read_text().strip()
        except Exception as exc:
            errors.append("{}: artifact read failed: {}".format(case["id"], exc))
            continue

        template = annotation["layout"]
        if template["id"] != case["layout"]:
            errors.append(case["id"] + ": frozen layout differs from manifest")
        if run.get("version") != version or annotation.get("version") != version:
            errors.append(case["id"] + ": stale construction version")
        if version in {"3.0", "3.1"}:
            if template != get_layout_template(case["layout"]):
                errors.append(case["id"] + ": v3 layout differs from the approved plan")
            if run.get("source", {}).get("id") != case["source_id"]:
                errors.append(case["id"] + ": v3 source allocation differs from the plan")
        if annotation != build_annotations(episode, template, run["source"]):
            errors.append(case["id"] + ": frozen ground truth differs from deterministic state")
        if annotation.get("layout_sha256") != digest(annotation.get("layout")):
            errors.append(case["id"] + ": layout snapshot checksum mismatch")
        source = run.get("source", {})
        original = sources.get(source.get("id"), {})
        if not original or any(source.get(key) != value for key, value in original.items()):
            errors.append(case["id"] + ": source differs from verified catalog")
        source_counts[source.get("id")] += 1
        skeleton = run.get("stage_outputs", {}).get("source_abstraction", {})
        if skeleton.get("source_id") != source.get("id"):
            errors.append(case["id"] + ": skeleton source provenance mismatch")
        journal = run.get("request_journal", [])
        if not journal or journal[0].get("input_value", {}).get("source") != source:
            errors.append(case["id"] + ": actual source-abstraction input missing or different")
        expected_cast = casting_contract(run["config"])
        actual_cast = [{k: subject[k] for k in ("id", "gender", "clothing")} for subject in episode["subjects"]]
        if actual_cast != expected_cast:
            errors.append(case["id"] + ": casting is not counterbalanced")
        for subject in actual_cast:
            key = case["task"] + "/" + subject["id"]
            role_genders.setdefault(key, Counter())[subject["gender"]] += 1
            role_colors.setdefault(key, Counter())[subject["clothing"].split()[0]] += 1
        for message in source_topic_errors(public, source):
            errors.append(case["id"] + ": " + message)
        for message in validate_compiled_episode(episode, template):
            errors.append("{}: episode: {}".format(case["id"], message))
        for message in validate_prompt(episode, template):
            errors.append("{}: prompt: {}".format(case["id"], message))

        expected_public = public_prompt(episode)
        if public != expected_public:
            errors.append(
                "{}: prompt.public.json differs from episode".format(case["id"])
            )
        expected_text = render_public_prompt(expected_public)
        if prompt_text != expected_text:
            errors.append(
                "{}: prompt.txt differs from structured prompt".format(case["id"])
            )
        if len(public.get("shots", [])) != case["shot_count"] or len(prompt_text.splitlines()) != case["shot_count"]:
            errors.append(
                "{}: public prompt must contain exactly {} shots and lines".format(
                    case["id"], case["shot_count"]
                )
            )

        stage_outputs = run.get("stage_outputs") or {}
        missing_stages = REQUIRED_STAGES - set(stage_outputs)
        if missing_stages:
            errors.append(
                "{}: missing intermediate stages: {}".format(
                    case["id"], ", ".join(sorted(missing_stages))
                )
            )
        audits = stage_outputs.get("prompt_audit") or []
        if not audits or not audits[-1].get("passed") or audits[-1].get("issues"):
            errors.append(
                "{}: final LLM audit did not pass cleanly".format(case["id"])
            )

        actual_signature = case_signature(run.get("config") or {})
        if actual_signature != case.get("case_signature"):
            errors.append(
                "{}: run signature differs from manifest".format(case["id"])
            )
        if episode["task"] != case["task"] or len(episode["subjects"]) != case["subject_count"]:
            errors.append(case["id"] + ": episode task/count differs from manifest")

        signatures.append(case["case_signature"])
        rendered_prompts.append(prompt_text)
        for key in distributions:
            distributions[key][case[key]] += 1

    errors.extend(validate_unique_case_signatures(signatures))
    if len(set(rendered_prompts)) != len(rendered_prompts):
        errors.append("Exact duplicate public prompts exist in the collection.")
    if len(signatures) == len(cases):
        for key, values in role_genders.items():
            tolerance = 2 if key.endswith("/D") else 0
            if abs(values["man"] - values["woman"]) > tolerance:
                errors.append("Unbalanced gender assignment: " + key)
        for key, values in role_colors.items():
            if len(values) != 7 or len(set(values.values())) != 1:
                errors.append("Unbalanced clothing colors: " + key)

    report = {
        "cases": len(cases),
        "status": manifest.get("status_summary") or {},
        "unique_signatures": len(
            {json.dumps(value, sort_keys=True) for value in signatures}
        ),
        "unique_public_prompts": len(set(rendered_prompts)),
        "distributions": {
            key: dict(sorted(counts.items(), key=lambda item: str(item[0])))
            for key, counts in distributions.items()
        },
        "sources": dict(source_counts),
        "gender_by_task_and_role": {key: dict(value) for key, value in role_genders.items()},
        "colors_by_task_and_role": {key: dict(value) for key, value in role_colors.items()},
        "errors": errors,
    }
    return report


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs/v3.1/core_matrix.manifest.json",
    )
    parser.add_argument("--outputs", type=Path, default=Path(__file__).resolve().parent / "outputs/v3.1")
    parser.add_argument("--report", type=Path, help="Save the full validation report")
    return parser.parse_args()


def main():
    args = parse_args()
    report = validate_collection(args.manifest, args.outputs)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.report, report)
        print(json.dumps({key: report[key] for key in ("cases", "status", "unique_signatures", "unique_public_prompts", "errors")}, ensure_ascii=False, indent=2))
        print("Report: " + str(args.report.resolve()))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
