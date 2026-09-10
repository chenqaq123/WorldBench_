#!/usr/bin/env python3
"""Offline audit of a frozen video evaluation: evidence, leakage and reproducible scores."""

import argparse
from functools import partial
from pathlib import Path

from run_evaluation import DEFAULT_OUTPUT, generation_parameters
from worldline.evaluation import REFERENCE_PROTOCOLS, EVIDENCE_PROTOCOLS, blind_context, readout_fractions, score_episode, validate_observation
from worldline.evidence_evaluation import (evidence_system, evidence_schema, required_evidence_ready,
                                          score_evidence_episode, validate_evidence_observation)
from worldline.reference_evaluation import (REFERENCE_SYSTEM, reference_context, reference_schema,
                                           score_reference_episode, validate_reference_observation)
from worldline.video import file_hash, read_json, write_json


def validate_run(root):
    root = Path(root).resolve()
    manifest = read_json(root / "manifest.json")
    protocol = manifest["judge"]["protocol"]
    if tuple(manifest["judge"]["readout_fractions"]) != readout_fractions(protocol):
        raise ValueError("Manifest sampling differs from its frozen protocol")
    errors, pending, records, warnings = [], [], [], []
    for case in manifest["cases"]:
        directory = root / case["id"]
        try:
            for name, sha256 in case["input_sha256"].items():
                if file_hash(directory / "input" / name) != sha256:
                    raise ValueError("Frozen input hash differs: " + name)
            annotations = read_json(directory / "input" / "annotations.hidden.json")
            episode = read_json(directory / "input" / "episode.internal.json")
            if not (directory / "video.mp4").exists() or not (directory / "score.json").exists():
                pending.append(case["id"])
                continue
            request = read_json(directory / "generation.request.json")
            expected = {**generation_parameters(manifest["generation"], case),
                        "prompt": (directory / "input" / "prompt.txt").read_text().strip()}
            if request != expected:
                raise ValueError("Video request differs from frozen public input or generation settings")
            metadata = read_json(directory / "video.metadata.json")
            if file_hash(directory / "video.mp4") != metadata["sha256"]:
                raise ValueError("Video hash differs")
            if abs(metadata["duration"] - request["duration"]) > 0.2:
                raise ValueError("Generated duration differs from requested duration")
            if request["resolution"].endswith("p") and min(metadata["width"], metadata["height"]) != int(request["resolution"][:-1]):
                warnings.append({"id": case["id"], "requested_resolution": request["resolution"],
                    "actual_dimensions": [metadata["width"], metadata["height"]],
                    "note": "Provider returned dimensions different from nominal request; video is preserved without resizing."})
            frames = read_json(directory / "frames.json")
            alignment = read_json(directory / "alignment.json")
            final_range = alignment["shots"][-1]
            readouts = [f for f in frames if f["role"] == "readout"]
            if final_range["start"] is not None:
                fractions = manifest["judge"]["readout_fractions"]
                if len(readouts) != len(fractions):
                    raise ValueError("Fixed readout count differs from protocol")
                for frame, fraction in zip(readouts, fractions):
                    wanted = final_range["start"] + fraction * (final_range["end"] - final_range["start"])
                    if abs(frame["time"] - wanted) > 0.00001:
                        raise ValueError("Readout timestamp differs from frozen sampling rule")
            for frame in frames:
                if file_hash(frame["path"]) != frame["sha256"]:
                    raise ValueError("Frame hash differs: " + frame["label"])
            reference = protocol in REFERENCE_PROTOCOLS
            evidence_only = protocol in EVIDENCE_PROTOCOLS
            scorer = partial(score_evidence_episode, protocol=protocol) if evidence_only else score_reference_episode
            context = reference_context(episode, annotations) if reference else blind_context(episode, annotations)
            observation = read_json(directory / "observation.json") if (directory / "observation.json").exists() else None
            if observation:
                if reference:
                    (validate_evidence_observation if evidence_only else validate_reference_observation)(observation, context, readouts)
                else:
                    validate_observation(observation, context, readouts, protocol=protocol)
            score = read_json(directory / "score.json")
            diagnostics = None if reference else read_json(directory / "diagnostics.json")
            reproduced = (scorer(context, observation, failure=score.get("failure")) if reference else
                          score_episode(annotations, observation, diagnostics, failure=score.get("failure"), protocol=protocol))
            if score != reproduced:
                raise ValueError("Saved score cannot be reproduced from frozen observations")
            if reference:
                packet = {**context, "frames": [{k: f[k] for k in ("label", "time", "shot", "role")} for f in frames]}
                expected_frames = []
                for shot in alignment["shots"]:
                    if shot["start"] is None or shot["index"] not in set(annotations["identity_anchor_shots"].values()):
                        continue
                    role = "opening" if shot["index"] == 1 else "anchor"
                    for i, fraction in enumerate(readout_fractions(protocol), 1):
                        expected_frames.append(("anchor_s{}_{}".format(shot["index"], i), role, shot["index"],
                                                shot["start"] + fraction * (shot["end"] - shot["start"])))
                if final_range["start"] is not None:
                    for i, fraction in enumerate(readout_fractions(protocol), 1):
                        expected_frames.append(("readout_" + str(i), "readout", final_range["index"],
                                                final_range["start"] + fraction * (final_range["end"] - final_range["start"])))
                if len(frames) != len(expected_frames):
                    raise ValueError("Reference evidence contains missing or extra frames")
                for frame, (label, role, shot_index, time) in zip(frames, expected_frames):
                    if (frame["label"], frame["role"], frame["shot"]) != (label, role, shot_index) or abs(frame["time"] - time) > 0.00001:
                        raise ValueError("Reference evidence roles or timing differ from the protocol")
                if read_json(directory / "reference.context.json") != packet:
                    raise ValueError("Reference context differs from frozen requests and frames")
                if score["target"] is not None and read_json(directory / "reference.target.json") != score["target"]:
                    raise ValueError("Reference target cannot be reproduced from opening and requested events")
                opening_frames = [f for f in frames if f["role"] == "opening"]
                first = alignment["shots"][0]
                if first["start"] is not None:
                    if len(opening_frames) != 2:
                        raise ValueError("Two fixed opening-reference frames required")
                    for frame, fraction in zip(opening_frames, readout_fractions(protocol)):
                        wanted = first["start"] + fraction * (first["end"] - first["start"])
                        if frame["shot"] != 1 or abs(frame["time"] - wanted) > 0.00001:
                            raise ValueError("Opening frame timing differs from protocol")
                if observation:
                    ready = (required_evidence_ready(alignment, frames, annotations) if evidence_only else
                             len(opening_frames) == 2 and len(readouts) == 2 and not alignment['uncertain'])
                    if not ready:
                        raise ValueError("Cannot judge unresolved opening/final evidence")
                    trace = read_json(directory / "judge/reference_observer/request.json")
                    system = evidence_system(protocol) if evidence_only else REFERENCE_SYSTEM
                    schema = evidence_schema(context) if evidence_only else reference_schema(context)
                    if trace["system"] != system or trace["schema"] != schema or trace["input"] != packet:
                        raise ValueError("Reference observer request differs from frozen protocol")
                    if read_json(directory / "judge/reference_observer/result.json") != observation:
                        raise ValueError("Published observation differs from the model result")
                    if [m["sha256"] for m in trace["media"]] != [f["sha256"] for f in frames]:
                        raise ValueError("Reference observer did not receive exactly the saved evidence")
            for request_path in directory.glob("judge/*/request.json"):
                trace = read_json(request_path)
                if trace["protocol"] != protocol:
                    raise ValueError("Judge trace protocol differs from manifest")
                single = manifest["judge"].get("mode") == "single"
                if single:
                    stages = {"reference_observer", "alignment"} if reference else {"observer_primary", "alignment", "trajectory_diagnostics"}
                    if request_path.parent.name not in stages:
                        raise ValueError("Unexpected review/adjudication stage in single-judge run")
                    if trace["model"] != manifest["judge"]["primary"] or any(m["kind"] != "image" for m in trace["media"]):
                        raise ValueError("Single-judge run must use the specified model and images only")
                for media in trace["media"]:
                    if file_hash(media["path"]) != media["sha256"]:
                        raise ValueError("Judge media hash mismatch")
                if request_path.parent.name.startswith("observer_") or request_path.parent.name == "adjudication":
                    allowed = set(context) | {"frames", "independent_observations", "instruction"}
                    if single:
                        allowed = set(context) | {"frames"}
                    if set(trace["input"]) - allowed:
                        raise ValueError("Unexpected unblinded observer input")
                    for key in context:
                        if trace["input"][key] != context[key]:
                            raise ValueError("Observer context differs from allowlist")
            records.append({"id": case["id"], "video_sha256": metadata["sha256"], "score_reproduced": True})
        except Exception as error:
            errors.append({"id": case["id"], "error": str(error)})
    report = {"case_count": len(manifest["cases"]), "verified_count": len(records),
              "errors": errors, "warnings": warnings, "pending": pending, "records": records,
              "note": "Verifies artifact and scoring integrity, not visual-judge accuracy or human agreement."}
    write_json(root / "validation.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()
    result = validate_run(args.output)
    print("Verified {}/{}; errors {}; pending {}".format(result["verified_count"], result["case_count"], len(result["errors"]), len(result["pending"])))
    if result["errors"]:
        print(result["errors"])
    raise SystemExit(1 if result["errors"] or result["pending"] else 0)


if __name__ == "__main__":
    main()
