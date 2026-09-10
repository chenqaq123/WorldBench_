"""Answer-blind observation contracts, deterministic temporal scoring, and reports."""

import csv
import html
import json
from pathlib import Path

from .annotations import score_wide_observation
from .video import read_json, write_json

READOUT_FRACTIONS = (0.25, 0.75)
PROTOCOL = "worldline-llm-judge-v3"
REFERENCE_PROTOCOL = "worldline-llm-judge-v4"
EVIDENCE_PROTOCOL = "worldline-llm-judge-v5"
SCOPED_EVIDENCE_PROTOCOL = "worldline-llm-judge-v5.1"
EVIDENCE_PROTOCOLS = {EVIDENCE_PROTOCOL, SCOPED_EVIDENCE_PROTOCOL}
REFERENCE_PROTOCOLS = {REFERENCE_PROTOCOL} | EVIDENCE_PROTOCOLS
LEGACY_PROTOCOL = "worldline-llm-judge-v2"


def readout_fractions(protocol=PROTOCOL):
    if protocol in {PROTOCOL} | REFERENCE_PROTOCOLS:
        return READOUT_FRACTIONS
    if protocol == LEGACY_PROTOCOL:
        return (0.2, 0.35, 0.5, 0.65, 0.8)
    raise ValueError("Unknown evaluation protocol: " + str(protocol))


def blind_context(episode, annotations):
    """Allowlist only: no task, event, expected count, initial or final occupants."""
    if annotations.get("version") == "3.1":
        raise ValueError("Dataset 3.1 requires the opening/update/final context, not legacy blind seats")
    layout = annotations["layout"]
    final = [o for o in annotations["observations"] if o["scored"]][-1]
    return {
        "scene": layout["public_intro"],
        "seats": {seat: layout["seats"][seat] for seat in final["expected_occupants"]},
        "opening_view": layout["cameras"][episode["shots"][0]["camera"]]["public_view"],
        "final_view": layout["cameras"][final["camera"]]["public_view"],
        "identity_references": [{"id": s["id"], "descriptor": s["appearance"],
            "anchor_shot": annotations["identity_anchor_shots"][s["id"]]} for s in episode["subjects"]],
    }


def validate_observation(observation, context, frames, *, protocol=PROTOCOL):
    identities = {s["id"] for s in context["identity_references"]}
    anchors = observation["anchors"]
    if len(anchors) != len(identities) or {a["subject"] for a in anchors} != identities:
        raise ValueError("Observer must record every identity anchor exactly once")
    if len(frames) != len(readout_fractions(protocol)) or len(observation["frames"]) != len(frames):
        raise ValueError("Observer must record all {} fixed readouts".format(len(readout_fractions(protocol))))
    for observed, frame in zip(observation["frames"], frames):
        if observed["frame"] != frame["label"]:
            raise ValueError("Readout IDs must match in chronological order")
        if set(observed["occupants"]) != set(context["seats"]):
            raise ValueError("Every designated seat needs an observation, including empty seats")
        if any(v not in identities | {None, "unknown", "unobservable"} for v in observed["occupants"].values()):
            raise ValueError("Unknown identity/seat status")
        count = observed["count"]
        if count is not None and (type(count) is not int or count < 0):
            raise ValueError("Count must be a nonnegative integer or null")
        occupied = sum(v not in {None, "unobservable"} for v in observed["occupants"].values())
        if count is not None and count < occupied:
            raise ValueError("Total count cannot be smaller than the number of observed occupied seats")


def observation_signature(observation):
    # Evidence wording is not a disagreement. Identity matching, observability and counts are.
    return {
        "anchors": sorted((a["subject"], a["reliable"]) for a in observation["anchors"]),
        "frames": [{k: f[k] for k in ("frame", "view_compliant", "readable", "count", "occupants")}
                   for f in observation["frames"]],
    }


def score_episode(annotations, observation=None, diagnostics=None, *, failure=None, protocol=PROTOCOL):
    if annotations.get("version") == "3.1" or protocol in REFERENCE_PROTOCOLS:
        raise ValueError("Dataset 3.1 uses observed opening references, not the legacy prescribed-seat scorer")
    fractions = readout_fractions(protocol)
    finals = [o for o in annotations["observations"] if o["scored"]]
    if len(finals) != 1:
        raise ValueError("This evaluator requires exactly one scored final wide; add an explicit multi-probe reducer for other protocols")
    result = {"protocol": protocol, "view_compliant": False, "readable": False,
              "valid": False, "count_correct": None, "position_correct": None,
              "joint_success": False, "strict_trajectory_success": False,
              "frames": [], "failure": failure}
    if observation is None:
        return result
    if len(observation["frames"]) != len(fractions):
        raise ValueError("Temporal scoring requires all {} fixed frames".format(len(fractions)))
    reliable = {a["subject"]: a["reliable"] for a in observation["anchors"]}
    for frame in observation["frames"]:
        occupants = {seat: ("unknown" if value in reliable and not reliable[value] else value)
                     for seat, value in frame["occupants"].items()}
        readable = frame["readable"] and frame["count"] is not None and "unobservable" not in occupants.values()
        valid = frame["view_compliant"] and readable
        score = score_wide_observation(finals[0], observed_count=frame["count"],
            observed_occupants=occupants, view_compliant=valid)
        result["frames"].append({"frame": frame["frame"], "view_compliant": frame["view_compliant"],
            "readable": readable, "valid": valid, "observed_count": frame["count"],
            "observed_occupants": occupants, **score})
    result["view_compliant"] = all(f["view_compliant"] for f in result["frames"])
    result["readable"] = all(f["readable"] for f in result["frames"])
    result["valid"] = result["view_compliant"] and result["readable"]
    if result["valid"]:
        result["count_correct"] = all(f["count_correct"] for f in result["frames"])
        result["position_correct"] = all(f["position_correct"] for f in result["frames"])
        result["joint_success"] = result["count_correct"] and result["position_correct"]
    result["diagnostics"] = diagnostics
    result["strict_trajectory_success"] = bool(result["joint_success"] and diagnostics and all(
        diagnostics.get(key) is True for key in ("establishment_correct", "partial_views_correct", "event_fidelity", "shot_sequence_correct")))
    return result


def summarize(rows):
    total = len(rows)
    evaluated = sum(r.get("evaluated", True) for r in rows)
    valid = sum(r["valid"] for r in rows)
    return {"total": total, "evaluated": evaluated, "valid": valid,
            "view_compliance_rate": sum(r["view_compliant"] for r in rows) / total if total and evaluated else None,
            "valid_observation_rate": valid / total if total and evaluated else None,
            "count_accuracy": sum(r["count_correct"] is True for r in rows) / valid if valid else None,
            "position_accuracy": sum(r["position_correct"] is True for r in rows) / valid if valid else None,
            "end_to_end_success": sum(r["joint_success"] for r in rows) / total if total and evaluated else None,
            "strict_trajectory_success": sum(r["strict_trajectory_success"] for r in rows) / total if total and evaluated else None}


def observer_agreement_breakdown(root, cases, *, protocol=PROTOCOL):
    totals = {key: {"agree": 0, "total": 0} for key in
              ("view_compliant", "readable", "count", "seat_occupant", "identity_anchor", "episode_valid", "episode_joint_success")}
    def add(key, left, right):
        totals[key]["total"] += 1
        totals[key]["agree"] += left == right
    for case in cases:
        directory = Path(root) / case["id"]
        paths = [directory / "judge" / name / "result.json" for name in ("observer_primary", "observer_secondary")]
        if not all(path.exists() for path in paths):
            continue
        first, second = map(read_json, paths)
        for a, b in zip(first["frames"], second["frames"]):
            for key in ("view_compliant", "readable", "count"):
                add(key, a[key], b[key])
            for seat in a["occupants"]:
                add("seat_occupant", a["occupants"][seat], b["occupants"][seat])
        other = {a["subject"]: a["reliable"] for a in second["anchors"]}
        for anchor in first["anchors"]:
            add("identity_anchor", anchor["reliable"], other[anchor["subject"]])
        annotation = read_json(directory / "input" / "annotations.hidden.json")
        a, b = score_episode(annotation, first, protocol=protocol), score_episode(annotation, second, protocol=protocol)
        add("episode_valid", a["valid"], b["valid"])
        add("episode_joint_success", a["joint_success"], b["joint_success"])
    for value in totals.values():
        value["rate"] = value["agree"] / value["total"] if value["total"] else None
    return totals


def write_report(root, manifest):
    if manifest["judge"].get("protocol") in REFERENCE_PROTOCOLS:
        from .reference_report import write_reference_report
        return write_reference_report(root, manifest)
    root = Path(root)
    single = manifest["judge"].get("mode") == "single"
    protocol = manifest["judge"].get("protocol", PROTOCOL)
    fractions = readout_fractions(protocol)
    if tuple(manifest["judge"].get("readout_fractions", fractions)) != fractions:
        raise ValueError("Manifest sampling differs from its frozen protocol")
    sample_count = len(fractions)
    rows, cost_video, cost_judge = [], 0.0, 0.0
    for case in manifest["cases"]:
        directory = root / case["id"]
        score_path = directory / "score.json"
        score = read_json(score_path) if score_path.exists() else score_episode(
            read_json(directory / "input" / "annotations.hidden.json"), failure="not_evaluated", protocol=protocol)
        if score["protocol"] != protocol:
            raise ValueError("Saved score and manifest use different protocols")
        status = read_json(directory / "status.json") if (directory / "status.json").exists() else {"status": "pending"}
        decision = read_json(directory / "decision.json") if (directory / "decision.json").exists() else {}
        job_path = directory / "generation.job.json"
        cost_video += ((read_json(job_path).get("usage") or {}).get("cost") or 0) if job_path.exists() else 0
        for response in directory.glob("judge/*/attempt-*.response.json"):
            cost_judge += (read_json(response).get("usage") or {}).get("cost") or 0
        rows.append({**case, **score, "execution_status": status["status"],
            "evaluated": score_path.exists(), "generated": (directory / "video.mp4").exists(),
            "execution_error": status.get("error"), "adjudicated": decision.get("adjudicated", False),
            "observer_agreement": decision.get("agreement"),
            "human_review_required": False if single else decision.get("human_review_required", not score_path.exists()),
            "uncertain": decision.get("uncertain") if single else None})
    by_task = {task: summarize([r for r in rows if r["task"] == task]) for task in sorted({r["task"] for r in rows})}
    macro = {}
    for metric in ("view_compliance_rate", "valid_observation_rate", "count_accuracy", "position_accuracy", "end_to_end_success", "strict_trajectory_success"):
        values = [m[metric] for m in by_task.values()]
        macro[metric] = sum(values) / len(values) if values and all(v is not None for v in values) else None
    compared = [r for r in rows if r["observer_agreement"] is not None]
    report = {"protocol": protocol, "caveat": "Exploratory pilot; automated LLM judgments, not human-validated benchmark scores. Unevaluated cases are not observed model failures; any partial aggregate retains the full planned denominator and is provisional.",
        "generation": manifest["generation"], "judge": manifest["judge"], "micro": summarize(rows), "by_task": by_task,
        "macro_equal_task": macro, "complete": all(r["evaluated"] for r in rows),
        "generated_count": sum(r["generated"] for r in rows),
        "evaluated_count": sum(r["evaluated"] for r in rows),
        "by_viewpoint": {v: summarize([r for r in rows if r["viewpoint_mode"] == v]) for v in sorted({r["viewpoint_mode"] for r in rows})},
        "by_subject_count": {str(n): summarize([r for r in rows if r["subject_count"] == n]) for n in sorted({r["subject_count"] for r in rows})},
        "observer_agreement": None if single else {"agree": sum(r["observer_agreement"] for r in compared), "compared": len(compared)},
        "observer_agreement_breakdown": None if single else observer_agreement_breakdown(root, manifest["cases"], protocol=protocol),
        "adjudicated_cases": sum(r["adjudicated"] for r in rows),
        "human_review_cases": [r["id"] for r in rows if r["human_review_required"]],
        "uncertain_cases": [r["id"] for r in rows if r["uncertain"]],
        "cost_usd_reported": {"video": cost_video, "judge": cost_judge, "total": cost_video + cost_judge},
        "cases": rows}
    if single and (root / "generation.reuse.json").exists():
        report["cost_usd_reported"] = {"video": 0.0, "judge": cost_judge, "total": cost_judge,
            "reused_video_historical": cost_video}
    write_json(root / "report.json", report)
    fields = ["id", "task", "scene", "subject_count", "viewpoint_mode", "generated", "evaluated", "execution_status", "view_compliant", "valid", "count_correct", "position_correct", "joint_success", "strict_trajectory_success", "adjudicated", "human_review_required"]
    if single:
        fields = [f for f in fields if f not in {"adjudicated", "human_review_required"}] + ["uncertain"]
    with (root / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **({key: None for key in ("view_compliant", "valid", "joint_success", "strict_trajectory_success")} if not row["evaluated"] else {})})
    def pct(value):
        return "N/A" if value is None else "{:.1%}".format(value)
    def mark(value):
        return "—" if value is None else ("✓" if value else "✗")
    md = ["# WorldLine · Seedance 2.0 Fast Pilot", "", report["caveat"], "",
          "{}-case 固定清单；已生成 {}，已评测 {}。每条一次生成；仅最终全景的 {} 个固定时点计主分。".format(len(rows), report["generated_count"], report["evaluated_count"], sample_count), "",
          "Valid（可评测）= 视角与覆盖合规，并且人数和座位占用可观察；它不是人数或位置正确。全部评分帧都满足才为真。", "",
          "裁判先记录观察，代码后对照隐藏答案。尚未评测不等于模型失败；零条评测时不输出成功率，未完成批次的汇总仅为临时结果。", "",
          "|Task|全部 / 有效|视角合规|人数（条件）|位置（条件）|端到端|", "|---|---|---|---|---|---|"]
    for task, value in by_task.items():
        md.append("|{}|{} / {}|{}|{}|{}|{}|".format(task, value["total"], value["valid"], pct(value["view_compliance_rate"]), pct(value["count_accuracy"]), pct(value["position_accuracy"]), pct(value["end_to_end_success"])))
    judge_summary = ("单裁判：{}；不进行第二裁判复核、仲裁或人工复核流程。不确定性标记：{} 条。事件诊断基于 2 fps 加片段中点抽帧，不代表逐帧验证。".format(
        manifest["judge"]["primary"], len(report["uncertain_cases"])) if single else
        "两位裁判严格记录一致：{}/{}；LLM 仲裁：{}；待人工复核：{}。".format(report["observer_agreement"]["agree"], len(compared), report["adjudicated_cases"], len(report["human_review_cases"])))
    md += ["", "Task 等权端到端：{}；整体端到端：{}。无有效样本时条件分数为 N/A，不以零代替。".format(pct(macro["end_to_end_success"]), pct(report["micro"]["end_to_end_success"])), "",
           judge_summary, "",
           "API 已报告费用：本批视频 ${:.4f}，裁判 ${:.4f}。".format(report["cost_usd_reported"]["video"], cost_judge), "",
           "|Case|有效|人数|位置|端到端|", "|---|---|---|---|---|"]
    for row in rows:
        md.append("|{}|{}|{}|{}|{}|".format(row["id"], *[mark(row[k] if row["evaluated"] else None) for k in ("valid", "count_correct", "position_correct", "joint_success")] ))
    md += ["", "详见 report.html：视频、固定读帧、裁判证据、冻结答案以及执行失败原因。"]
    if not single:
        md += ["", "裁判一致性（原始观察、仲裁前）：", "", "|字段|一致 / 全部|一致率|", "|---|---|---|"]
        for key, value in report["observer_agreement_breakdown"].items():
            md.append("|{}|{} / {}|{}|".format(key, value["agree"], value["total"], pct(value["rate"])))
    md += ["",
           "限制：未完成独立人工标注一致性验证；固定 {} 帧不代表未采样时刻也正确；小规模 pilot 不足以推断总体性能。".format(sample_count)]
    (root / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    cards = []
    for row in rows:
        cid = row["id"]
        observation_path = root / cid / "observation.json"
        observation = read_json(observation_path) if observation_path.exists() else {}
        annotation = read_json(root / cid / "input" / "annotations.hidden.json")
        final = [o for o in annotation["observations"] if o["scored"]][-1]
        evidence = next((name for name in ("evidence.jpg", "overview.jpg") if (root / cid / name).exists()), None)
        media_html = '<video controls preload="metadata" src="{}/video.mp4"></video>'.format(cid) if row["generated"] else '<p>视频尚未生成</p>'
        if evidence:
            media_html += '<a href="{0}/{1}"><img loading="lazy" src="{0}/{1}" alt="Saved visual evidence"></a>'.format(cid, evidence)
        if row["evaluated"]:
            counts = " / ".join("?" if f["observed_count"] is None else str(f["observed_count"]) for f in row["frames"])
            media_html += '<p>View {} · Readable {} · {} 帧实际人数：{} · 目标人数：{}</p>'.format(
                mark(row["view_compliant"]), mark(row["readable"]), sample_count, html.escape(counts), final["expected_count"])
            if not row["valid"]:
                media_html += '<p>主分 — 表示观察条件未通过而不计分，不表示人数或位置正确；原始人数读数保留在上方。</p>'
        cards.append('<section><h2>{}</h2><p>{} · {} people · {}</p><p>Generated {} · Evaluated {}</p>{}<p>可评测（Valid）{} · Count {} · Position {} · E2E {}</p><details><summary>Prompt / hidden target / observed evidence</summary><pre>{}</pre><pre>{}</pre><pre>{}</pre></details><p>{}</p></section>'.format(
            html.escape(cid), html.escape(row["task"]), row["subject_count"], html.escape(row["viewpoint_mode"]), mark(row["generated"]), mark(row["evaluated"]), media_html,
            *[mark(row[k] if row["evaluated"] else None) for k in ("valid", "count_correct", "position_correct", "joint_success")],
            html.escape((root / cid / "input" / "prompt.txt").read_text()),
            html.escape(json.dumps(final, ensure_ascii=False, indent=2)),
            html.escape(json.dumps(observation, ensure_ascii=False, indent=2)), html.escape(row.get("execution_error") or "")))
    style = '<style>body{max-width:1100px;margin:40px auto;font:16px/1.6 system-ui;background:#f3f5f8;color:#152338}section{background:white;padding:24px;margin:24px 0;border-radius:12px}video,img{max-width:100%}video{width:720px}pre{white-space:pre-wrap;overflow-wrap:anywhere}h2{font-size:19px}</style>'
    heading = '<!doctype html><html lang="zh"><meta charset="utf-8"><title>WorldLine Evaluation</title>' + style + '<h1>WorldLine · Seedance 2.0 Fast</h1>'
    heading += '<p>固定 {} 条 · 已生成 {} · 已评测 {} · 人工验证尚未完成</p>'.format(len(rows), report["generated_count"], report["evaluated_count"])
    heading += '<p>{}</p>'.format(html.escape(judge_summary))
    heading += '<p>本报告按 {} 帧协议评分。Valid（可评测）要求视角和座位覆盖合规、人数与座位占用可观察；不代表人数或位置正确。</p>'.format(sample_count)
    (root / "report.html").write_text(heading + '<p>End-to-end {} · View compliance {} · Valid {}/{} · Count {} · Position {}</p><p><a href="REPORT.md">完整指标</a> · <a href="report.json">JSON</a> · <a href="results.csv">CSV</a></p>{}</html>'.format(
        pct(report["micro"]["end_to_end_success"]), pct(report["micro"]["view_compliance_rate"]), report["micro"]["valid"], len(rows), pct(report["micro"]["count_accuracy"]), pct(report["micro"]["position_accuracy"]), "".join(cards)), encoding="utf-8")
    return report
