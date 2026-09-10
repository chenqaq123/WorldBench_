#!/usr/bin/env python3
"""Prepare local blind calibration; paid judging is an explicit separate phase."""

import argparse
import os
from pathlib import Path

from generate_prompt import load_env_file
from run_evaluation import DEFAULT_JUDGE, judge_settings, preflight_judge
from worldline.calibration import compare_labels, load_item, prepare_packet
from worldline.evaluation import PROTOCOL, validate_observation
from worldline.judge import judge_call, observation_schema, observation_system
from worldline.video import VideoClient, read_json, write_json

BASE = Path(__file__).resolve().parent


def run_judge(root, model, client):
    manifest = read_json(root / "manifest.json")
    for item in manifest["items"]:
        load_item(root, item)
    preflight_judge(client, root / "judge-run", judge_settings(model))
    for item in manifest["items"]:
        folder, context, frames = load_item(root, item)
        media = [{"path": str(folder / f["path"]), "kind": "image",
                  "label": "{} | {} | shot {} | {:.3f}s".format(f["label"], f["role"], f["shot"], f["time"])}
                 for f in frames]
        result = judge_call(
            client, root / "judge-run" / item["id"], "observer_primary", model, observation_system(PROTOCOL),
            context, observation_schema(context), media,
            lambda value: validate_observation(value, context, [f for f in frames if f["role"] == "readout"]),
            temperature=None,
        )
        write_json(root / "judge-results" / (item["id"] + ".judge.json"),
                   {"item": item["id"], "input_sha256": item["input_sha256"], "observation": result})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("prepare", "judge", "compare"), default="prepare")
    p.add_argument("--source-run", type=Path, default=BASE / "evaluations/seedance-2.0-fast-pilot-10-3s-per-shot-480p-sol-single")
    p.add_argument("--output", type=Path, default=BASE / "calibration/pilot-10-two-frame")
    p.add_argument("--judge", default=DEFAULT_JUDGE)
    p.add_argument("--execute", action="store_true", help="Explicit paid upload for the judge phase only")
    p.add_argument("--env-file", type=Path, default=BASE / ".env")
    args = p.parse_args()
    if args.execute and args.phase != "judge":
        p.error("--execute is only valid for --phase judge")
    if args.phase == "prepare":
        manifest = prepare_packet(args.source_run, args.output)
        print("Prepared {} blind items locally; human and paid judge labels pending.".format(len(manifest["items"])))
        print(args.output.resolve() / "blind/index.html")
    elif args.phase == "judge":
        if not args.execute:
            print("No API calls made. Paid calibration requires --phase judge --execute.")
            return
        load_env_file(args.env_file)
        run_judge(args.output, args.judge, VideoClient(os.environ.get("OPENROUTER_API_KEY")))
    else:
        report = compare_labels(args.output)
        write_json(args.output / "agreement.report.json", report)
        print("Complete: {}. Pending items: {}. Not a release approval.".format(report["complete"], len(report["pending_items"])))


if __name__ == "__main__":
    main()
