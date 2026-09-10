#!/usr/bin/env python3
"""CLI for the standalone WorldLine Python prompt constructor."""

import argparse
import os
from pathlib import Path

from worldline import PipelineOptions, TASK_TYPES, build_prompt_pipeline, case_signature
from worldline.artifacts import (
    index_existing_cases,
    signature_key,
    write_pipeline_result,
)
from worldline.layouts import get_layout_template
from worldline.matrix import viewpoint_mode_for_template


BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path):
    """Load simple KEY=VALUE entries without adding a dotenv dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate one geometry-controlled WorldLine multi-shot prompt."
    )
    parser.add_argument("--id", default="WL-PY-PILOT-001", dest="episode_id")
    parser.add_argument(
        "--task",
        choices=TASK_TYPES,
        default="static_viewpoint_change",
    )
    parser.add_argument("--layout", default="cafe_rect_table_3_v1")
    parser.add_argument("--archetype")
    parser.add_argument("--source-id", help="ID from the verified real-source catalog")
    parser.add_argument("--subjects", type=int, default=3, dest="subject_count")
    parser.add_argument("--shots", type=int, default=3, dest="shot_count")
    parser.add_argument("--model")
    parser.add_argument("--skeleton-model")
    parser.add_argument("--casting-model")
    parser.add_argument("--story-model")
    parser.add_argument("--render-model")
    parser.add_argument("--audit-model")
    parser.add_argument("--env-file", type=Path, default=BASE_DIR / ".env")
    parser.add_argument("--output-root", type=Path, default=BASE_DIR / "outputs" / "v2")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--allow-duplicate-signature",
        action="store_true",
        help="Allow an intentional robustness variant with an existing case signature.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    load_env_file(args.env_file)
    template = get_layout_template(args.layout)
    predicted_config = {
        "task": args.task,
        "scene": template["scene_type"],
        "layout": template["id"],
        "viewpoint_mode": viewpoint_mode_for_template(template),
        "subject_count": len(template["seat_order"]),
        "shot_count": args.shot_count,
    }
    predicted_signature = case_signature(predicted_config)
    output_directory = args.output_root.resolve() / args.episode_id
    if output_directory.exists() and any(output_directory.iterdir()) and not args.overwrite:
        raise FileExistsError(
            "Output already exists: {}. Use --overwrite to replace its files.".format(
                output_directory
            )
        )
    existing = index_existing_cases(args.output_root)
    duplicate_id = existing["by_signature"].get(signature_key(predicted_signature))
    if (
        duplicate_id
        and not args.allow_duplicate_signature
        and not (duplicate_id == args.episode_id and args.overwrite)
    ):
        raise FileExistsError(
            "Case signature duplicates {}. Change task type, scene/layout, viewpoint "
            "mode, subject count, or shot count; use --allow-duplicate-signature only "
            "for an intentional robustness variant.".format(duplicate_id)
        )
    options = PipelineOptions(
        episode_id=args.episode_id,
        task=args.task,
        layout=args.layout,
        archetype=args.archetype,
        source_id=args.source_id,
        subject_count=args.subject_count,
        shot_count=args.shot_count,
        model=args.model,
        skeleton_model=args.skeleton_model,
        casting_model=args.casting_model,
        story_model=args.story_model,
        render_model=args.render_model,
        audit_model=args.audit_model,
    )
    result = build_prompt_pipeline(options)
    if result["run"]["case_signature"] != predicted_signature:
        raise RuntimeError("Generated case signature does not match the preflight signature.")
    output_directory = write_pipeline_result(
        result, args.output_root, overwrite=args.overwrite
    )

    print("Generated {}".format(args.episode_id))
    print("Output: {}".format(output_directory))
    print()
    print(result["rendered_prompt"])


if __name__ == "__main__":
    main()
