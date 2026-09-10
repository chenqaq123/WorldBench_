"""Persistence helpers for WorldLine prompt-construction artifacts."""

import json
from pathlib import Path


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_pipeline_result(result, output_root, *, overwrite=False):
    output_root = Path(output_root).resolve()
    episode_id = result["episode"]["id"]
    output_directory = output_root / episode_id
    if output_directory.exists() and any(output_directory.iterdir()) and not overwrite:
        raise FileExistsError(
            "Output already exists: {}. Use overwrite to replace its files.".format(
                output_directory
            )
        )
    output_directory.mkdir(parents=True, exist_ok=True)
    write_json(output_directory / "episode.internal.json", result["episode"])
    write_json(output_directory / "annotations.hidden.json", result["annotations"])
    write_json(output_directory / "prompt.public.json", result["public_prompt"])
    write_json(output_directory / "run.json", result["run"])
    (output_directory / "prompt.txt").write_text(
        result["rendered_prompt"] + "\n", encoding="utf-8"
    )
    return output_directory


def index_existing_cases(output_root, *, dataset_version="2.0"):
    """Index only artifacts that still pass the current deterministic rules."""
    from .layouts import get_layout_template
    from .pipeline import validate_compiled_episode, validate_prompt, public_prompt, render_public_prompt
    from .annotations import build_annotations
    from .balance import casting_contract

    by_id = {}
    by_signature = {}
    invalid_ids = []
    for run_path in Path(output_root).resolve().glob("*/run.json"):
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
            episode = json.loads(
                (run_path.parent / "episode.internal.json").read_text(encoding="utf-8")
            )
            template = get_layout_template(episode["layout"])
            annotations = json.loads((run_path.parent / "annotations.hidden.json").read_text(encoding="utf-8"))
            public = json.loads((run_path.parent / "prompt.public.json").read_text(encoding="utf-8"))
            rendered = (run_path.parent / "prompt.txt").read_text(encoding="utf-8").strip()
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            invalid_ids.append(run_path.parent.name)
            continue
        episode_id = run_path.parent.name
        audits = (run.get("stage_outputs") or {}).get("prompt_audit") or []
        final_audit = audits[-1] if audits else {}
        try:
            errors = validate_compiled_episode(episode, template) + validate_prompt(
                episode
            )
        except (KeyError, TypeError, IndexError):
            invalid_ids.append(episode_id)
            continue
        if (
            errors or not final_audit.get("passed") or final_audit.get("issues")
            or run.get("version") != dataset_version
            or run["stage_outputs"]["subject_casting"].get("subjects") != casting_contract(run["config"])
            or annotations != build_annotations(episode, template, run["source"])
            or public != public_prompt(episode)
            or rendered != render_public_prompt(public)
        ):
            invalid_ids.append(episode_id)
            continue
        by_id[episode_id] = run
        signature = run.get("case_signature")
        if signature:
            key = tuple(
                signature.get(field)
                for field in (
                    "task_type",
                    "scene",
                    "viewpoint_mode",
                    "subject_count",
                    "shot_count",
                )
            )
            by_signature.setdefault(key, episode_id)
    return {
        "by_id": by_id,
        "by_signature": by_signature,
        "invalid_ids": sorted(invalid_ids),
    }


def signature_key(signature):
    return tuple(
        signature.get(field)
        for field in (
            "task_type",
            "scene",
            "viewpoint_mode",
            "subject_count",
            "shot_count",
        )
    )
