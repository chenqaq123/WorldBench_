#!/usr/bin/env python3
"""Plan or sequentially generate the complete WorldLine Core matrix."""

import argparse
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from worldline import PipelineOptions, TASK_TYPES, build_prompt_pipeline
from worldline.annotations import DATASET_VERSION
from worldline.artifacts import (
    index_existing_cases,
    signature_key,
    write_json,
    write_pipeline_result,
)
from worldline.matrix import (
    CORE_SHOT_COUNTS,
    CORE_SUBJECT_COUNTS,
    CORE_VIEWPOINT_MODES,
    SCENE_CODES,
    SUPPORTED_SHOT_COUNTS,
    plan_core_matrix,
)


BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Plan or generate the WorldLine Core benchmark matrix."
    )
    parser.add_argument("--task", action="append", choices=TASK_TYPES)
    parser.add_argument("--scene", action="append", choices=sorted(SCENE_CODES))
    parser.add_argument(
        "--subjects", nargs="+", type=int, choices=CORE_SUBJECT_COUNTS
    )
    parser.add_argument("--shots", nargs="+", type=int, choices=SUPPORTED_SHOT_COUNTS)
    parser.add_argument(
        "--viewpoint", action="append", choices=CORE_VIEWPOINT_MODES
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model")
    parser.add_argument("--workers", type=int, default=1, help="Independent case workers (default 1)")
    parser.add_argument("--env-file", type=Path, default=BASE_DIR / ".env")
    parser.add_argument("--output-root", type=Path, default=BASE_DIR / "outputs" / "v2")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=BASE_DIR / "outputs" / "v2" / "core_matrix.manifest.json",
    )
    return parser.parse_args()


def summarize(records):
    counts = Counter(record["status"] for record in records)
    return {key: counts[key] for key in sorted(counts)}


def save_manifest(path, records, filters, selected_ids, invalid_ids):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    selected_records = [record for record in records if record["id"] in selected_ids]
    resolved_ids = {record.get("artifact_id", record["id"]) for record in records if record["status"] in {"complete", "reused"}}
    write_json(
        path,
        {
            "benchmark": "WorldLine",
            "version": DATASET_VERSION,
            "track": "Core",
            "review_status": "automated_checks_only; human and video validation pending",
            "case_count": len(records),
            "selected_case_count": len(selected_records),
            "filters": filters,
            "status_summary": summarize(records),
            "selected_status_summary": summarize(selected_records),
            "ignored_invalid_artifacts": [artifact_id for artifact_id in invalid_ids if artifact_id not in resolved_ids],
            "cases": records,
        },
    )


def main():
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be a positive integer.")
    if not 1 <= args.workers <= 8:
        raise ValueError("--workers must be between 1 and 8.")
    load_env_file(args.env_file)
    filters = {
        "tasks": args.task or list(TASK_TYPES),
        "scenes": args.scene or sorted(SCENE_CODES),
        "subject_counts": args.subjects or list(CORE_SUBJECT_COUNTS),
        "shot_counts": args.shots or list(CORE_SHOT_COUNTS),
        "viewpoint_modes": args.viewpoint or list(CORE_VIEWPOINT_MODES),
    }
    selected = plan_core_matrix(
        tasks=filters["tasks"],
        scenes=filters["scenes"],
        subject_counts=filters["subject_counts"],
        shot_counts=filters["shot_counts"],
        viewpoint_modes=filters["viewpoint_modes"],
    )
    selected_ids = {case["id"] for case in selected}
    manifest_shot_counts = tuple(
        sorted(set(CORE_SHOT_COUNTS) | set(filters["shot_counts"]))
    )
    planned = plan_core_matrix(shot_counts=manifest_shot_counts)
    existing = index_existing_cases(args.output_root)
    records = []
    for case in planned:
        record = dict(case)
        exact = existing["by_id"].get(case["id"])
        reused_id = existing["by_signature"].get(
            signature_key(case["case_signature"])
        )
        if exact and exact.get("case_signature") == case["case_signature"]:
            record["status"] = "complete"
        elif reused_id:
            record["status"] = "reused"
            record["artifact_id"] = reused_id
        else:
            record["status"] = "pending"
        records.append(record)
    save_manifest(
        args.manifest,
        records,
        filters,
        selected_ids,
        existing["invalid_ids"],
    )

    if not args.execute:
        print("Planned {} cases".format(len(records)))
        print("Selected {} cases".format(len(selected_ids)))
        print("Status: {}".format(summarize(records)))
        if existing["invalid_ids"]:
            print(
                "Ignored invalid artifacts: {}".format(
                    ", ".join(existing["invalid_ids"])
                )
            )
        print("Manifest: {}".format(args.manifest.resolve()))
        return

    pending = [
        record
        for record in records
        if record["id"] in selected_ids and record["status"] == "pending"
    ]
    if args.limit is not None:
        pending = pending[: args.limit]
    def generate_record(record):
        print("Generating {}".format(record["id"]), flush=True)
        folder = args.output_root / record["id"]
        folder.mkdir(parents=True, exist_ok=True)
        # Preserve incomplete attempts too; never replace a completed result.
        attempt = 1 + len(list(folder.glob("attempt-*.json")))
        journal_path = folder / "attempt-{:03d}.json".format(attempt)
        try:
            result = build_prompt_pipeline(
                PipelineOptions(
                    episode_id=record["id"],
                    task=record["task"],
                    layout=record["layout"],
                    subject_count=record["subject_count"],
                    shot_count=record["shot_count"],
                    model=args.model,
                ),
                on_stage=lambda journal: write_json(journal_path, journal),
            )
            if result["run"]["case_signature"] != record["case_signature"]:
                raise RuntimeError("Generated signature differs from the matrix plan.")
            write_pipeline_result(result, args.output_root, overwrite=True)
            record["status"] = "complete"
            record["artifact_id"] = record["id"]
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
        return record

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(generate_record, record) for record in pending]):
            record = future.result()
            print("{}: {}{}".format(record["id"], record["status"], ": " + record["error"] if record.get("error") else ""), flush=True)
            save_manifest(args.manifest, records, filters, selected_ids, existing["invalid_ids"])

    print("Processed {} pending cases".format(len(pending)))
    print("Status: {}".format(summarize(records)))
    print("Manifest: {}".format(args.manifest.resolve()))


if __name__ == "__main__":
    main()
