"""Four-metric report for the opening-reference protocol."""

import csv
import html
import json
from functools import partial
from pathlib import Path

from .evaluation import REFERENCE_PROTOCOLS, EVIDENCE_PROTOCOLS, SCOPED_EVIDENCE_PROTOCOL, READOUT_FRACTIONS
from .reference_evaluation import reference_context, score_reference_episode
from .video import read_json, write_json

METRICS = ("valid_observation_rate", "count_accuracy", "position_accuracy", "end_to_end_success")
NOTE = ("Valid = 开场满足基本人数、身份与布局条件，且最终两帧视角合规、人数与位置对应可观察。"
        "Count / Position 在 Valid 样本内计算，且各自要求两帧都正确；SR 在全部计划样本上计算。"
        "开场仅提供参照，partial 不计主分。未评测不冒充失败，未完成批次汇总为临时结果。"
        "本协议尚未经过人工校准，不能视为已验证的正式 benchmark 结果。")
EVIDENCE_NOTE = ("Valid = 开场可建立可靠参照，且最终两帧证据足以判断人数与位置是否正确；不要求精确执行摄影或预设座位布局。"
                 "明确的多/少人计为 Count 错误，明确的位置或布局改变计为 Position 错误，不能据此排除样本。"
                 "Count / Position 在 Valid 样本内计算，各自要求两帧都正确；SR 在全部计划样本上计算。"
                 "开场仅提供参照，partial 不计主分。未完成批次仅为临时结果；裁判尚需人工校准。")


def summary(rows):
    total = len(rows)
    evaluated = sum(r["evaluated"] for r in rows)
    valid = sum(r["valid"] for r in rows)
    return {
        "total": total, "evaluated": evaluated, "valid": valid,
        "valid_observation_rate": valid / total if total and evaluated else None,
        "count_accuracy": sum(r["count_correct"] is True for r in rows) / valid if valid else None,
        "position_accuracy": sum(r["position_correct"] is True for r in rows) / valid if valid else None,
        "end_to_end_success": sum(r["joint_success"] for r in rows) / total if total and evaluated else None,
    }


def pct(value):
    return "N/A" if value is None else "{:.1%}".format(value)


def mark(value):
    return "—" if value is None else ("✓" if value else "✗")


def case_card(root, row, context):
    directory = root / row["id"]
    esc = html.escape
    observed = read_json(directory / "observation.json") if (directory / "observation.json").exists() else {}
    frames = read_json(directory / "frames.json") if (directory / "frames.json").exists() else []
    body = '<video controls preload="metadata" src="{}/video.mp4"></video>'.format(esc(row["id"])) if row["generated"] else "<p>视频尚未生成</p>"
    for role, title in (("opening", "开场空间参照（不计主分）"), ("anchor", "入场身份参照（不计主分）"), ("readout", "最终全景：两个固定评分点")):
        selected = [f for f in frames if f["role"] == role]
        if selected:
            body += "<h3>" + title + '</h3><div class="frames">'
            for frame in selected:
                rel = Path(frame["path"]).resolve().relative_to(root.resolve()).as_posix()
                body += '<figure><img loading="lazy" src="{}"><figcaption>{} · {:.3f}s</figcaption></figure>'.format(
                    esc(rel), esc(frame["label"]), frame["time"])
            body += "</div>"
    body += "<h3>要求的中间 Update</h3><p>" + esc(" ".join(u["content"] for u in context["updates"])) + "</p>"
    body += "<p>最终镜头要求：" + esc(context["final_view"]) + "</p>"
    target = row["target"]
    if target:
        body += "<p>开场参照有效：" + mark(target["valid"]) + "；问题：" + esc(", ".join(target["issues"]) or "无") + "</p>"
        body += "<table><tr><th>开场物理位置</th><th>开场实际</th><th>按 Update 推导目标</th><th>最终帧 1</th><th>最终帧 2</th></tr>"
        for place, value in observed["opening"]["places"].items():
            expected = target["expected_occupants"][place] if target["valid"] else "不可推导"
            values = [place + ": " + value["description"], value["occupant"], expected]
            values += [f["observed_occupants"][place] for f in row["frames"]]
            body += "<tr>" + "".join("<td>" + esc("空位" if v is None else str(v)) + "</td>" for v in values) + "</tr>"
        body += "</table><p>目标人数：{}；两帧实际人数：{}</p>".format(
            target["expected_count"] if target["valid"] else "不可推导",
            esc(" / ".join(str(f["observed_count"]) for f in row["frames"])))
    body += "<p>" + esc(row.get("failure") or row.get("execution_error") or "") + "</p>"
    if row['protocol'] in EVIDENCE_PROTOCOLS:
        for frame in row['frames']:
            body += '<p>{}：证据足够 {} · 人数 {} · 位置 {} · 物理布局改变 {}</p>'.format(
                esc(frame['frame']), mark(frame['valid']), mark(frame['count_correct']),
                mark(frame['position_correct']), mark(frame['layout_changed']))
    body += "<details><summary>生成 Prompt 与原始裁判观察</summary><pre>" + esc(
        (directory / "input/prompt.txt").read_text()) + "</pre><pre>" + esc(json.dumps(observed, ensure_ascii=False, indent=2)) + "</pre></details>"
    scores = [mark(row[k] if row["evaluated"] else None) for k in ("valid", "count_correct", "position_correct", "joint_success")]
    return "<section><h2>" + esc(row["id"]) + "</h2><p>" + esc(row["task"]) + "</p><p>Valid {} · Count {} · Position {} · SR {}</p>".format(*scores) + body + "</section>"


def write_reference_report(root, manifest):
    root = Path(root)
    protocol = manifest['judge']['protocol']
    if protocol not in REFERENCE_PROTOCOLS or tuple(manifest["judge"]["readout_fractions"]) != READOUT_FRACTIONS:
        raise ValueError("Reference report requires its own frozen two-readout protocol")
    from .evidence_evaluation import COUNT_SCOPE_HELP, score_evidence_episode
    scorer = partial(score_evidence_episode, protocol=protocol) if protocol in EVIDENCE_PROTOCOLS else score_reference_episode
    note = EVIDENCE_NOTE if protocol in EVIDENCE_PROTOCOLS else NOTE
    if protocol == SCOPED_EVIDENCE_PROTOCOL:
        note += COUNT_SCOPE_HELP
    rows, cards, video_cost, judge_cost = [], [], 0.0, 0.0
    for case in manifest["cases"]:
        directory = root / case["id"]
        context = reference_context(read_json(directory / "input/episode.internal.json"), read_json(directory / "input/annotations.hidden.json"))
        score_path = directory / "score.json"
        score = read_json(score_path) if score_path.exists() else scorer(context, failure="not_evaluated")
        if score["protocol"] != protocol:
            raise ValueError("Cannot mix scoring protocols in a report")
        status = read_json(directory / "status.json") if (directory / "status.json").exists() else {"status": "pending"}
        decision = read_json(directory / "decision.json") if (directory / "decision.json").exists() else {}
        row = {**case, **score, "generated": (directory / "video.mp4").exists(), "evaluated": score_path.exists(),
               "execution_status": status["status"], "execution_error": status.get("error"), "uncertain": decision.get("uncertain")}
        rows.append(row)
        cards.append(case_card(root, row, context))
        if (directory / "generation.job.json").exists():
            video_cost += (read_json(directory / "generation.job.json").get("usage") or {}).get("cost") or 0
        for path in directory.glob("judge/*/attempt-*.response.json"):
            judge_cost += (read_json(path).get("usage") or {}).get("cost") or 0
    cost = {"video": video_cost, "judge": judge_cost, "total": video_cost + judge_cost}
    if (root / "generation.reuse.json").exists():
        cost = {"video": 0.0, "judge": judge_cost, "total": judge_cost, "reused_video_historical": video_cost}
    by_task = {task: summary([r for r in rows if r["task"] == task]) for task in sorted({r["task"] for r in rows})}
    macro = {}
    for metric in METRICS:
        values = [v[metric] for v in by_task.values()]
        macro[metric] = sum(values) / len(values) if values and all(v is not None for v in values) else None
    report = {"protocol": protocol, "caveat": note, "generation": manifest["generation"], "judge": manifest["judge"],
              "micro": summary(rows), "by_task": by_task, "macro_equal_task": macro,
              "by_viewpoint": {v: summary([r for r in rows if r["viewpoint_mode"] == v]) for v in sorted({r["viewpoint_mode"] for r in rows})},
              "by_subject_count": {str(n): summary([r for r in rows if r["subject_count"] == n]) for n in sorted({r["subject_count"] for r in rows})},
              "complete": bool(rows) and all(r["evaluated"] for r in rows), "generated_count": sum(r["generated"] for r in rows),
              "evaluated_count": sum(r["evaluated"] for r in rows), "uncertain_cases": [r["id"] for r in rows if r["uncertain"]],
              "cost_usd_reported": cost, "cases": rows}
    write_json(root / "report.json", report)
    fields = ["id", "task", "scene", "subject_count", "shot_count", "viewpoint_mode", "generated", "evaluated",
              "reference_valid", "valid", "count_correct", "position_correct", "joint_success", "uncertain"]
    with (root / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **({k: None for k in ("reference_valid", "valid", "joint_success")} if not row["evaluated"] else {})})
    md = ["# WorldLine · Opening-reference Evaluation", "", note, "", "协议：" + protocol + "；裁判：" + manifest["judge"]["primary"] + "。单裁判，无复核。",
          "", "|Task|全部 / 有效|Valid|Count|Position|SR|", "|---|---|---|---|---|---|"]
    for task, value in {"All cases": report["micro"], **by_task}.items():
        md.append("|{}|{} / {}|{}|".format(task, value["total"], value["valid"], "|".join(pct(value[k]) for k in METRICS)))
    md += ["", "位置目标由实际开场和指定 Update 推导，不使用构造时的最终座位表。没有计算中间动作或完整轨迹正确率。",
           "开场和最终帧在同一次模型调用中可见，仍需人工校准以检查反向猜测和空间映射误差。",
           "", "已生成 {}；已评测 {}；费用（API 已报告）USD {:.4f}。".format(report["generated_count"], report["evaluated_count"], cost["total"])]
    (root / "REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    style = "<style>body{max-width:1100px;margin:32px auto;padding:0 20px;font:16px/1.6 system-ui;color:#182638;background:#f3f5f8}section{padding:24px;margin:24px 0;background:white;border-radius:12px}video{width:720px;max-width:100%}.frames{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0}img{max-width:100%}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}h2{overflow-wrap:anywhere;font-size:20px}@media(max-width:650px){.frames{grid-template-columns:1fr}section{padding:12px}}</style>"
    heading = '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WorldLine · Opening-reference Evaluation</title>' + style
    heading += "<h1>WorldLine · 初始场景 + Update + 最终全景</h1><p>" + html.escape(note) + "</p>"
    heading += "<p>协议 {} · 已生成 {} · 已评测 {} / {}</p>".format(protocol, report["generated_count"], report["evaluated_count"], len(rows))
    heading += "<p>Valid {} · Count {} · Position {} · SR {}</p>".format(*[pct(report["micro"][k]) for k in METRICS])
    heading += '<p><a href="REPORT.md">指标说明</a> · <a href="report.json">JSON</a> · <a href="results.csv">CSV</a></p>'
    finding_path = root / 'calibration.findings.json'
    if finding_path.exists():
        findings = read_json(finding_path)
        heading += '<section style="border:2px solid #b45309"><h2>校准警告：以下仍是未修正的原始自动评分</h2><p>证据核查发现裁判可能漏数或误判。本页保留原始输出，不代表正式验收通过；此核查不是独立人工标注。</p>'
        for finding in findings.get('findings', []):
            heading += '<p><strong>' + html.escape(finding['case_id']) + '</strong> · ' + html.escape(finding['kind']) + '</p><p>' + html.escape(finding['evidence']) + '</p>'
        heading += '<p><a href="calibration.findings.json">独立问题记录（原评分未覆盖）</a></p></section>'
    (root / "report.html").write_text(heading + "".join(cards) + "</html>", encoding="utf-8")
    return report
