#!/usr/bin/env python3
"""Frozen, resumable generation and LLM-as-judge pilot, separate from the website."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import shutil
import time

from generate_prompt import load_env_file
from worldline.evaluation import PROTOCOL, REFERENCE_PROTOCOLS, SCOPED_EVIDENCE_PROTOCOL, READOUT_FRACTIONS
from worldline.video import VideoClient, file_hash, generate_video, now, prepare_overview, read_json, write_json

BASE = Path(__file__).resolve().parent
DEFAULT_JUDGE = "openai/gpt-5.6-sol"
DEFAULT_OUTPUT = BASE / "evaluations" / "seedance-2.0-fast-evidence-v5.1"
# Chosen before video generation: 7 scenes, 4 tasks, 5 reverse / 5 overhead, 5 three / 5 four subjects.
PILOT_IDS = [
    "WL-CORE-CAFE-SWAP-4P-REV-3S",
    "WL-CORE-KITCHEN-EXIT-3P-TOP-3S",
    "WL-CORE-MEETING-STATIC-3P-REV-3S",
    "WL-CORE-LIVING-ENTRY-4P-TOP-3S",
    "WL-CORE-DINING-SWAP-3P-TOP-3S",
    "WL-CORE-GAME-EXIT-4P-REV-3S",
    "WL-CORE-SEMINAR-STATIC-4P-TOP-3S",
    "WL-CORE-KITCHEN-ENTRY-3P-REV-3S",
    "WL-CORE-CAFE-STATIC-3P-TOP-3S",
    "WL-CORE-MEETING-SWAP-4P-REV-3S",
]


def generation_parameters(settings, case):
    """Total API duration is computed per case; never alter the public prompt."""
    parameters = dict(settings)
    if "seconds_per_shot" in parameters:
        seconds = parameters.pop("seconds_per_shot")
        if type(seconds) is not int or seconds <= 0 or type(case["shot_count"]) is not int or case["shot_count"] <= 0:
            raise ValueError("Seconds per shot and shot count must be positive integers")
        parameters["duration"] = case["shot_count"] * seconds
    if "duration" in case and case["duration"] != parameters["duration"]:
        raise ValueError("Case duration differs from the frozen timing policy")
    return parameters


def validate_generation_parameters(model, manifest):
    # Preflight the complete batch before any paid submission. Never silently cap
    # 7 x 3 = 21 seconds to a model's 15-second limit or split the video into jobs.
    for case in manifest["cases"]:
        parameters = generation_parameters(manifest["generation"], case)
        for key, capability in (("duration", "supported_durations"), ("resolution", "supported_resolutions"),
                                ("aspect_ratio", "supported_aspect_ratios")):
            if parameters[key] not in model[capability]:
                raise ValueError("{}: unsupported {}={} for {}; no videos submitted".format(
                    case["id"], key, parameters[key], model["id"]))


def judge_settings(model, protocol=PROTOCOL):
    if protocol not in {PROTOCOL} | REFERENCE_PROTOCOLS:
        raise ValueError("Unsupported evaluation protocol")
    return {"mode": "single", "primary": model, "protocol": protocol,
            "readout_fractions": list(READOUT_FRACTIONS),
            "sequence_input": "timestamped_frames", "sequence_fps": 2, "temperature": None}


def preflight_judge(client, root, settings):
    """Check exact image/JSON route before any paid evaluation or video request."""
    path = Path(root) / "judge.model.snapshot.json"
    if path.exists():
        model = read_json(path)["model"]
    else:
        matches = [m for m in client.request("/models")["data"] if m["id"] == settings["primary"]]
        if len(matches) != 1:
            raise ValueError("Requested judge is not available: " + settings["primary"])
        model = matches[0]
    if model["id"] != settings["primary"]:
        raise ValueError("Frozen judge model differs from manifest")
    if ("image" not in model["architecture"]["input_modalities"] or
            not {"max_tokens", "response_format", "structured_outputs"} <= set(model["supported_parameters"])):
        raise ValueError("Judge does not support the image/structured-output contract")
    if not path.exists():
        write_json(path, {"fetched_at": now(), "model": model})


def prepare(args):
    root = args.output.resolve()
    manifest_path = root / "manifest.json"
    if getattr(args, "all_cases", False) and args.case_id:
        raise ValueError("--all-cases and --case-id are mutually exclusive")
    settings = {"model": args.model, "seconds_per_shot": args.seconds_per_shot, "resolution": args.resolution,
                "aspect_ratio": "16:9", "seed": args.seed, "generate_audio": False}
    judge = judge_settings(args.judge, getattr(args, "protocol", PROTOCOL))
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if args.phase not in {"media", "report"} and Path(manifest["dataset"]).resolve() != args.dataset.resolve():
            raise ValueError("Dataset differs from frozen evaluation; use a new output directory")
        if getattr(args, "all_cases", False):
            requested_ids = [c["id"] for c in read_json(args.dataset / "core_matrix.manifest.json")["cases"]]
            if requested_ids != [c["id"] for c in manifest["cases"]]:
                raise ValueError("All-case selection differs from frozen evaluation; use a new output directory")
        if args.phase not in {"media", "report"} and (manifest["generation"] != settings or manifest["judge"] != judge):
            raise ValueError("Settings differ from frozen manifest; use a new output directory")
        if args.case_id and args.case_id != [c["id"] for c in manifest["cases"]]:
            raise ValueError("Case selection differs from frozen manifest; use a new output directory")
        for case in manifest["cases"]:
            for name, digest in case["input_sha256"].items():
                if file_hash(root / case["id"] / "input" / name) != digest:
                    raise ValueError("Frozen input changed: " + case["id"] + "/" + name)
        return manifest
    dataset_manifest = read_json(args.dataset / "core_matrix.manifest.json")
    cases = {c["id"]: c for c in dataset_manifest["cases"]}
    if judge["protocol"] in REFERENCE_PROTOCOLS and not (getattr(args, "all_cases", False) or args.case_id):
        raise ValueError("Select --case-id or --all-cases explicitly for the new reference protocol")
    selected = list(cases) if getattr(args, "all_cases", False) else (args.case_id or PILOT_IDS)
    if len(set(selected)) != len(selected):
        raise ValueError("Duplicate case IDs")
    for cid in selected:
        if cid not in cases or cases[cid]["status"] != "complete":
            raise ValueError("Not a complete dataset case: " + cid)
    if judge["protocol"] in REFERENCE_PROTOCOLS:
        if dataset_manifest.get("version") != "3.1":
            raise ValueError("Opening-reference protocol requires dataset 3.1; old videos keep their original protocol")
        from worldline.reference_evaluation import reference_context
        for cid in selected:
            reference_context(read_json(args.dataset / cid / "episode.internal.json"),
                              read_json(args.dataset / cid / "annotations.hidden.json"))
    elif dataset_manifest.get("version") == "3.1":
        raise ValueError("Dataset 3.1 must not be evaluated against legacy prescribed final seats")
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for cid in selected:
        record = {k: cases[cid][k] for k in ("id", "task", "scene", "subject_count", "shot_count", "viewpoint_mode")}
        record["duration"] = generation_parameters(settings, record)["duration"]
        record["input_sha256"] = {}
        dest = root / cid / "input"
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("prompt.txt", "prompt.public.json", "episode.internal.json", "annotations.hidden.json", "run.json"):
            shutil.copy2(args.dataset / cid / name, dest / name)
            record["input_sha256"][name] = file_hash(dest / name)
        if len(read_json(dest / "episode.internal.json")["shots"]) != record["shot_count"]:
            raise ValueError("Episode shot count differs from dataset manifest: " + cid)
        records.append(record)
    manifest = {"benchmark": "WorldLine", "created_at": now(), "dataset": str(args.dataset.resolve()),
                "selection": "all manifest cases" if getattr(args, "all_cases", False) else "predeclared subset; one generation per case; no replacement based on outcomes",
                "generation": settings, "judge": judge, "cases": records,
                "coverage": {field: dict(Counter(str(c[field]) for c in records)) for field in
                             ("task", "scene", "subject_count", "shot_count", "viewpoint_mode")}}
    write_json(manifest_path, manifest)
    return manifest


def reuse_videos(source, root, manifest):
    """Copy exact existing generation artifacts into an isolated evaluation revision."""
    source, root = Path(source).resolve(), Path(root).resolve()
    previous = read_json(source / "manifest.json")
    if previous["generation"] != manifest["generation"]:
        raise ValueError("Cannot reuse videos generated with different duration/resolution/model settings")
    previous_cases = {c["id"]: c for c in previous["cases"]}
    for case in manifest["cases"]:
        prior = previous_cases.get(case["id"])
        if not prior or prior["input_sha256"] != case["input_sha256"]:
            raise ValueError("Cannot reuse video with different frozen inputs: " + case["id"])
        for name in ("video.mp4", "video.metadata.json", "generation.request.json", "generation.job.json"):
            src, dst = source / case["id"] / name, root / case["id"] / name
            if not src.exists():
                raise ValueError("Source generation is not ready: " + str(src))
            if dst.exists():
                if file_hash(src) != file_hash(dst):
                    raise ValueError("Refusing to overwrite different generation artifact: " + str(dst))
            else:
                shutil.copy2(src, dst)
    if (source / "model.snapshot.json").exists() and not (root / "model.snapshot.json").exists():
        shutil.copy2(source / "model.snapshot.json", root / "model.snapshot.json")
    write_json(root / "generation.reuse.json", {"source": str(source), "note": "Exact existing videos reused; no new video generation charge", "at": now()})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=["plan", "generate", "media", "evaluate", "all", "report"], default="plan")
    p.add_argument("--dataset", type=Path, default=BASE / "outputs" / "v3.1")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--reuse-videos-from", type=Path, help="Reuse exact existing videos for an isolated judge/protocol revision")
    p.add_argument("--case-id", action="append")
    p.add_argument("--all-cases", action="store_true", help="Use every complete case from the selected dataset manifest")
    p.add_argument("--model", default="bytedance/seedance-2.0-fast")
    p.add_argument("--seconds-per-shot", type=int, default=3,
                   help="Total duration = each case's actual shot count times this value; does not enforce cut timing")
    p.add_argument("--resolution", default="480p", help="Seedance 2.0 Fast's minimum supported resolution")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--judge", default=DEFAULT_JUDGE, help="Single judge for all evaluation stages; no review or adjudication")
    p.add_argument("--protocol", choices=sorted({PROTOCOL} | REFERENCE_PROTOCOLS), default=SCOPED_EVIDENCE_PROTOCOL,
                   help="v5.1 clarifies background exclusions; v5/v4/v3 replay their frozen original protocols")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--wait-for-video", action="store_true", help="Wait for already-running generation; never submit a job in evaluate phase")
    p.add_argument("--retry-rejected", action="store_true", help="Explicitly retry only definitive HTTP rejections; never repeat ambiguous submissions")
    p.add_argument("--env-file", type=Path, default=BASE / ".env")
    args = p.parse_args()
    if not 1 <= args.workers <= 8:
        p.error("workers must be between 1 and 8")
    if args.seconds_per_shot <= 0:
        p.error("seconds-per-shot must be positive")
    load_env_file(args.env_file)
    manifest = prepare(args)
    root = args.output.resolve()
    if args.reuse_videos_from:
        reuse_videos(args.reuse_videos_from, root, manifest)
    if args.phase == "plan":
        print(str(root / "manifest.json"))
        print(manifest["coverage"])
        return
    client = None if args.phase in {"media", "report"} else VideoClient(os.environ.get("OPENROUTER_API_KEY"))
    if args.phase in {"evaluate", "all"}:
        preflight_judge(client, root, manifest["judge"])
    if args.phase in {"generate", "all"}:
        models = client.request("/videos/models")["data"]
        model = next(m for m in models if m["id"] == args.model)
        validate_generation_parameters(model, manifest)
        if not (root / "model.snapshot.json").exists():
            write_json(root / "model.snapshot.json", {"fetched_at": now(), "model": model})
    def run(case):
        directory = root / case["id"]
        try:
            if args.phase in {"generate", "all"}:
                generate_video(client, directory, {**generation_parameters(manifest["generation"], case),
                    "prompt": (directory / "input" / "prompt.txt").read_text(encoding="utf-8").strip()}, retry_rejected=args.retry_rejected)
            if args.phase == "media":
                if (directory / "video.mp4").exists():
                    prepare_overview(directory)
                return True
            if args.phase in {"evaluate", "all"}:
                from worldline.judge import evaluate_video
                waiting_since = time.monotonic()
                while args.wait_for_video and not (directory / "video.mp4").exists():
                    job_path = directory / "generation.job.json"
                    if job_path.exists() and read_json(job_path).get("status") in {"failed", "cancelled", "submission_uncertain", "rejected"}:
                        raise RuntimeError("Generation failed or needs submission review")
                    if time.monotonic() - waiting_since > 3600:
                        raise TimeoutError("No video yet; evaluation can be resumed")
                    time.sleep(10)
                evaluate_video(client, directory, manifest["judge"])
            write_json(directory / "status.json", {"status": "complete" if args.phase in {"evaluate", "all"} else "generated", "at": now()})
            return True
        except Exception as error:
            write_json(directory / "status.json", {"status": "error", "phase": args.phase, "error": str(error), "at": now()})
            print(case["id"] + " ERROR: " + str(error), flush=True)
            return False
    failures = 0
    if args.phase != "report":
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for result in as_completed([pool.submit(run, c) for c in manifest["cases"]]):
                failures += not result.result()
    if args.phase in {"media", "evaluate", "all", "report"}:
        from worldline.evaluation import write_report
        write_report(root, manifest)
    print("Finished; {} execution errors. Output: {}".format(failures, root), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
