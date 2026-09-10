#!/usr/bin/env python3
"""Plan the 112-case mixed Core; paid construction requires explicit --execute."""

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event

from generate_prompt import load_env_file
from validate_matrix import validate_collection
from worldline import PipelineOptions, build_prompt_pipeline
from worldline.annotations import digest
from worldline.artifacts import index_existing_cases, write_json, write_pipeline_result
from worldline.core_v3 import VERSION, REFERENCE_VERSION, design_check, plan_mixed_core
from worldline.openrouter import PermanentOpenRouterError

BASE = Path(__file__).resolve().parent


def next_attempt_number(folder):
    """Keep even failures that occurred before the first successful stage."""
    numbers = [0]
    for pattern in ("attempt-*.json", "failure-*.json"):
        for path in folder.glob(pattern):
            suffix = path.stem.rsplit("-", 1)[-1]
            if suffix.isdigit():
                numbers.append(int(suffix))
    return max(numbers) + 1


def protected_output(root):
    root = Path(root).resolve()
    legacy = (BASE / "outputs" / "v2").resolve()
    if root == legacy or legacy in root.parents or root in legacy.parents:
        raise ValueError("Use a separate v3 output directory; v2 and its parents are protected")
    return root


def prepare(root, version=VERSION):
    root = protected_output(root)
    planned = plan_mixed_core(version)
    design, contracts = design_check(planned, version)
    if design["errors"]:
        raise ValueError("Invalid v3 design: " + "; ".join(design["errors"]))
    root.mkdir(parents=True, exist_ok=True)
    path = root / "core_matrix.manifest.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get("version") != version or previous.get("plan_sha256") != digest(planned):
            raise ValueError("Existing plan differs; choose a new versioned output directory")
    existing = index_existing_cases(root, dataset_version=version)
    records = []
    for case in planned:
        record = dict(case)
        run = existing["by_id"].get(case["id"])
        if run and (run["config"]["layout"] != case["layout"] or run["source"]["id"] != case["source_id"]
                    or run["case_signature"] != case["case_signature"]):
            record["status"] = "needs_repair"
        elif run:
            record["status"] = "complete"
        elif (root / case["id"] / "run.json").exists():
            record["status"] = "needs_repair"
        else:
            record["status"] = "pending"
        records.append(record)
    manifest = {
        "benchmark": "WorldLine", "version": version, "track": "Core",
        "review_status": "candidate; human prompt review and two-frame judge calibration pending",
        "plan_sha256": digest(planned), "case_count": len(records),
        "filters": {"shot_counts": [3, 4]},
        "status_summary": dict(Counter(r["status"] for r in records)), "cases": records,
    }
    write_json(path, manifest)
    write_json(root / "design.report.json", design)
    write_json(root / "planned.contracts.json", contracts)
    # This is a review checklist, not fabricated approval or generated content.
    review_path = root / "review.checklist.json"
    if not review_path.exists():
        write_json(review_path, {
            "plan_sha256": digest(planned),
            "cases": [{"id": c["id"], "public_facts_unambiguous": None,
                       "camera_feasible": None, "answers_supported": None, "notes": ""}
                      for c in planned],
        })
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", choices=[VERSION, REFERENCE_VERSION], default=REFERENCE_VERSION)
    p.add_argument("--output-root", type=Path)
    p.add_argument("--execute", action="store_true", help="Paid prompt construction using the configured provider, never video generation")
    p.add_argument("--validate", action="store_true", help="Require every generated case to pass collection checks")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=1, help="Independent cases in parallel; stages within each case remain sequential")
    p.add_argument("--case-id", action="append")
    p.add_argument("--model")
    p.add_argument("--resume", action="store_true", help="Reuse an exact matching prefix of saved stage responses")
    p.add_argument("--env-file", type=Path, default=BASE / ".env")
    args = p.parse_args()
    if args.limit is not None and args.limit < 1:
        p.error("--limit must be positive")
    if not 1 <= args.workers <= 4:
        p.error("--workers must be between 1 and 4")
    if args.execute and args.validate:
        p.error("--execute and --validate are separate operations")
    root = protected_output(args.output_root or BASE / "outputs" / ("v" + args.version))
    manifest = prepare(root, args.version)
    selected = set(args.case_id or [c["id"] for c in manifest["cases"]])
    if selected - {c["id"] for c in manifest["cases"]}:
        p.error("Unknown case ID")
    if args.execute:
        load_env_file(args.env_file)
        pending = [c for c in manifest["cases"] if c["id"] in selected and c["status"] == "pending"]
        if args.limit:
            pending = pending[:args.limit]
        failures = []
        stopped = Event()
        skipped = []
        def construct(case):
            if stopped.is_set():
                return ("skipped", case["id"])
            folder = root / case["id"]
            folder.mkdir(parents=True, exist_ok=True)
            attempt = next_attempt_number(folder)
            journal = folder / "attempt-{:03d}.json".format(attempt)
            try:
                previous = sorted(folder.glob("attempt-*.json"),
                                  key=lambda path: int(path.stem.rsplit("-", 1)[-1]))
                resume = json.loads(previous[-1].read_text()) if args.resume and previous else None
                print(case['id'] + ': constructing', flush=True)
                result = build_prompt_pipeline(
                    PipelineOptions(episode_id=case["id"], task=case["task"], layout=case["layout"],
                                    source_id=case["source_id"], subject_count=case["subject_count"],
                                    shot_count=case["shot_count"], model=args.model),
                    on_stage=lambda value: write_json(journal, value),
                    resume_journal=resume,
                )
                if result["run"]["version"] != args.version or result["run"]["case_signature"] != case["case_signature"]:
                    raise ValueError("Generated result differs from frozen v3 plan")
                # A pending folder contains journals, not a completed user-owned run.
                write_pipeline_result(result, root, overwrite=True)
                print(case['id'] + ': complete', flush=True)
                return None
            except Exception as exc:
                if isinstance(exc, PermanentOpenRouterError) and exc.status_code in {401, 402, 403}:
                    stopped.set()
                write_json(folder / ("failure-{:03d}.json".format(attempt)), {"error": str(exc)})
                print(case["id"] + ": failed: " + str(exc), flush=True)
                return ("failed", case["id"])
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in as_completed([pool.submit(construct, case) for case in pending]):
                failed = future.result()
                if failed:
                    (failures if failed[0] == "failed" else skipped).append(failed[1])
        # Only the main thread updates collection files, after all case writes finish.
        manifest = prepare(root, args.version)
        if skipped:
            print("Batch stopped after access/balance refusal; {} cases left pending.".format(len(skipped)))
        if failures:
            raise SystemExit("Failed cases retained for explicit diagnosis: " + ", ".join(failures))
    if args.validate:
        report = validate_collection(root / "core_matrix.manifest.json", root)
        write_json(root / "validation.report.json", report)
        print(json.dumps({"cases": report["cases"], "errors": report["errors"]}, ensure_ascii=False))
        raise SystemExit(1 if report["errors"] else 0)
    print(json.dumps({"version": args.version, "cases": manifest["case_count"], "status": manifest["status_summary"],
                      "manifest": str(root / "core_matrix.manifest.json"),
                      "release_ready": False,
                      "note": "Design plan is not a generated or human-validated dataset."}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
