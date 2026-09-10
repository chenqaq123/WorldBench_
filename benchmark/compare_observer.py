#!/usr/bin/env python3
"""Replay one frozen blind image observation with another judge, without regeneration."""

import argparse
import json
import os
from pathlib import Path

from generate_prompt import load_env_file
from worldline.evaluation import PROTOCOL, readout_fractions, blind_context, score_episode, validate_observation
from worldline.judge import observation_system, judge_call, observation_schema, validate_schema
from worldline.video import VideoClient, file_hash, now, read_json, write_json


def freeze(path, value):
    if path.exists() and read_json(path) != value:
        raise ValueError("Frozen comparison changed; use a new output directory: " + str(path))
    write_json(path, value)


def prepare_comparison(source, output, model):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Comparison output must be separate from the source evaluation")
    annotations = read_json(source / "input/annotations.hidden.json")
    episode = read_json(source / "input/episode.internal.json")
    frames = read_json(source / "frames.json")
    readouts = [f for f in frames if f["role"] == "readout"]
    context = blind_context(episode, annotations)
    context["frames"] = [{k: f[k] for k in ("label", "time", "shot", "role")} for f in frames]
    request = read_json(source / "judge/observer_primary/request.json")
    protocol = request["protocol"]
    schema = observation_schema(context)
    if (request["system"] != observation_system(protocol)
            or request["input"] != context or request["schema"] != schema):
        raise ValueError("Frozen source no longer matches the current blind observation contract")
    expected_labels = ["{} | {} | shot {} | {:.3f}s".format(
        f["label"], f["role"], f["shot"], f["time"]) for f in frames]
    if len(readouts) != len(readout_fractions(protocol)) or [m["label"] for m in request["media"]] != expected_labels:
        raise ValueError("Comparison requires the identical anchor images and protocol-specific fixed readouts")
    if any(m["kind"] != "image" or file_hash(m["path"]) != m["sha256"] for m in request["media"]):
        raise ValueError("Frozen source image kind/hash mismatch")
    files = ["input/episode.internal.json", "input/annotations.hidden.json", "frames.json",
             "alignment.json", "video.mp4", "judge/observer_primary/request.json"]
    for stage in ("observer_primary", "observer_secondary", "adjudication"):
        for name in ("request.json", "result.json"):
            relative = "judge/" + stage + "/" + name
            if relative not in files and (source / relative).exists():
                files.append(relative)
    manifest = {"protocol": protocol, "kind": "single_blind_observer_comparison",
        "case_id": source.name, "source": str(source), "model": model,
        "source_sha256": {name: file_hash(source / name) for name in files},
        "media": request["media"], "trajectory_evaluated": False,
        "note": "Same frozen observer prompt/schema/images; no task, target answers, prior judgments, or human feedback sent to the new observer."}
    freeze(output / "manifest.json", manifest)
    return annotations, context, schema, request["media"], readouts


def endpoint_score(annotations, observation, *, protocol=PROTOCOL):
    result = score_episode(annotations, observation, protocol=protocol)
    # This comparison does not run a video trajectory judge. Do not display a
    # missing diagnostic as a failed Sol trajectory judgment.
    return {k: v for k, v in result.items() if k not in ("diagnostics", "strict_trajectory_success")}


def run_comparison(source, output, model, client):
    source, output = Path(source).resolve(), Path(output).resolve()
    annotations, context, schema, media, readouts = prepare_comparison(source, output, model)
    protocol = read_json(output / "manifest.json")["protocol"]
    snapshot_path = output / "model.snapshot.json"
    if snapshot_path.exists():
        capability = read_json(snapshot_path)["model"]
    else:
        matches = [m for m in client.request("/models")["data"] if m["id"] == model]
        if len(matches) != 1:
            raise ValueError("Requested model not available: " + model)
        capability = matches[0]
        write_json(snapshot_path, {"queried_at": now(), "model": capability})
    if capability["id"] != model:
        raise ValueError("Frozen model snapshot does not match requested model")
    parameters = set(capability["supported_parameters"])
    if ("image" not in capability["architecture"]["input_modalities"]
            or not {"response_format", "structured_outputs", "max_tokens"} <= parameters):
        raise ValueError("Requested model does not support the frozen image/JSON contract")
    temperature = 0 if "temperature" in parameters else None
    observed = judge_call(client, output, "observer_comparison", model, observation_system(protocol),
        context, schema, media, lambda value: validate_observation(value, context, readouts, protocol=protocol),
        temperature=temperature, protocol=protocol)
    write_json(output / "observation.json", observed)
    write_json(output / "score.json", endpoint_score(annotations, observed, protocol=protocol))
    rows = []
    for stage in ("observer_primary", "observer_secondary", "adjudication"):
        result_path = source / "judge" / stage / "result.json"
        if result_path.exists():
            baseline = read_json(result_path)
            validate_schema(baseline, schema)
            validate_observation(baseline, context, readouts, protocol=protocol)
            rows.append({"stage": stage, "model": read_json(result_path.parent / "request.json")["model"],
                "score": endpoint_score(annotations, baseline, protocol=protocol), "observation": baseline})
    rows.append({"stage": "observer_comparison", "model": model,
        "score": endpoint_score(annotations, observed, protocol=protocol), "observation": observed})
    responses = [read_json(p) for p in sorted((output / "judge/observer_comparison").glob("attempt-*.response.json"))]
    report = {"case_id": source.name, "protocol": protocol, "trajectory_evaluated": False,
        "expected_final": [o for o in annotations["observations"] if o["scored"]][-1],
        "temperature": temperature, "reasoning": "provider default; no effort override",
        "returned_models": [r.get("model") for r in responses],
        "reported_cost_usd": sum((r.get("usage") or {}).get("cost") or 0 for r in responses),
        "rows": rows, "limitations": ["Single case, not judge accuracy validation.",
        "Existing shared readability gate is intentionally unchanged.",
        "No native video or trajectory diagnostic sent to this image observer."]}
    write_json(output / "comparison.json", report)
    print(json.dumps({"case_id": source.name, "model": model,
        "score": {k: v for k, v in rows[-1]["score"].items() if k != "frames"},
        "reported_cost_usd": report["reported_cost_usd"]}, ensure_ascii=False, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run", action="store_true", help="Explicitly send fixed images to the paid judge")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parent / ".env")
    args = parser.parse_args()
    if args.run:
        load_env_file(args.env_file)
        run_comparison(args.source_case, args.output, args.model, VideoClient(os.environ.get("OPENROUTER_API_KEY")))
    else:
        prepare_comparison(args.source_case, args.output, args.model)
        print("Comparison planned without API calls; pass --run to evaluate the fixed images.")


if __name__ == "__main__":
    main()
