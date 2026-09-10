"""Local, answer-blind human calibration packets; no network calls."""

import html
import json
from pathlib import Path

from .annotations import digest
from .evaluation import (PROTOCOL, READOUT_FRACTIONS, blind_context,
                         score_episode, validate_observation)
from .judge import observation_schema, validate_schema
from .video import extract_frame, file_hash, read_json, write_json


def packet_hash(context, frames):
    return digest({"protocol": PROTOCOL, "context": context,
                   "frames": [{k: f[k] for k in ("label", "time", "shot", "role", "sha256")} for f in frames]})


def observation_template(context, frames):
    return {
        "anchors": [{"subject": a["id"], "reliable": None, "evidence": ""} for a in context["identity_references"]],
        "frames": [{"frame": f["label"], "view_compliant": None, "readable": None, "count": None,
                    "occupants": {seat: "unset" for seat in context["seats"]}, "evidence": ""}
                   for f in frames if f["role"] == "readout"],
        "uncertainties": [],
    }


def review_html(item_id, context, frames, input_hash):
    payload = json.dumps({"item": item_id, "input_sha256": input_hash,
                          "observation": observation_template(context, frames)}, ensure_ascii=False).replace("<", "\\u003c")
    parts = ['<!doctype html><html lang="zh"><meta charset="utf-8"><title>WorldLine calibration</title>',
             '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#182331}img{max-width:100%;display:block}figure{margin:20px 0}section{border-top:1px solid #ccd5df;padding:16px 0}label{display:inline-block;margin:8px 16px 8px 0}select,input,textarea,button{font:inherit;padding:7px}textarea{display:block;width:95%;height:55px}button{cursor:pointer;margin:16px 0}pre{white-space:pre-wrap;background:#f2f5f8;padding:16px}.references{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.references figcaption{font-size:13px}</style>',
             '<h1>WorldLine · ' + item_id + '</h1><p>独立人工标注，不显示任务、预期答案或已有裁判结果。只记录图片事实；不要从身份名单推断人数。</p>',
             '<p>可见空座选 empty；有人但身份不确定选 unknown；座位区域不可观察选 unobservable。可见但身份未知不是“看不清座位”。数量包含互动区域内额外站立或重复人物。</p>',
             '<p>俯拍要求直接向下，不是斜俯拍；反打要求沿场景地标反向观察。空座也可满足区域覆盖。不能从前一帧推断当前帧被遮住的占用；无法确定方向时将视角合规标为否并说明。</p>',
             '<h2>场景与观察要求</h2><p>' + html.escape(context["scene"]) + '</p>',
             '<p><strong>开场参照：</strong>' + html.escape(context["opening_view"]) + '</p>',
             '<p><strong>最终全景：</strong>' + html.escape(context["final_view"]) + '</p>',
             '<ul>' + "".join('<li>' + html.escape(a["id"] + ": " + a["descriptor"]) +
                              '（身份建立镜头 ' + str(a["anchor_shot"]) + '）</li>'
                              for a in context["identity_references"]) + '</ul>',
             '<h2>身份参照（不评分）</h2><div class="references">']
    for f in frames:
        if f["role"] == "anchor":
            parts.append('<figure><img loading="lazy" src="' + html.escape(f["path"]) + '"><figcaption>' + html.escape(f["label"]) + '</figcaption></figure>')
    parts.append('</div><div id="anchors"></div>')
    for i, f in enumerate(f for f in frames if f["role"] == "readout"):
        parts.append('<section><h2>最终全景 · ' + html.escape(f["label"]) + '</h2><img src="' + html.escape(f["path"]) + '"><div id="frame-' + str(i) + '"></div></section>')
    parts.append('<p>不确定性备注</p><textarea id="uncertainties"></textarea><button id="export">导出人工标注 JSON</button><p id="status"></p><script>')
    parts.append("const data=" + payload + ";const seatLabels=" +
                 json.dumps(context["seats"], ensure_ascii=False).replace("<", "\\u003c") + ";")
    parts.append(r"""
const obs=data.observation;
function select(parent,label,values,current,save){
  const l=document.createElement('label'); l.append(document.createTextNode(label+' '));
  const s=document.createElement('select');
  for(const [value,text] of values){const o=document.createElement('option');o.value=value;o.textContent=text;s.append(o);}
  s.value=current;s.onchange=()=>save(s.value);l.append(s);parent.append(l);
}
function booleanField(parent,label,value,save){select(parent,label,[['','请选择'],['true','是'],['false','否']],value===null?'':String(value),v=>save(v===''?null:v==='true'));}
function evidence(parent,save){const e=document.createElement('textarea');e.placeholder='依据（描述可见事实）';e.oninput=()=>save(e.value);parent.append(e);}
for(const a of obs.anchors){
 const p=document.getElementById('anchors');
 booleanField(p,a.subject+' 身份参照可靠',a.reliable,v=>a.reliable=v);evidence(p,v=>a.evidence=v);
}
obs.frames.forEach((f,i)=>{
 const p=document.getElementById('frame-'+i);
 booleanField(p,'视角与区域覆盖符合要求',f.view_compliant,v=>f.view_compliant=v);
 booleanField(p,'人数与座位占用可观察',f.readable,v=>f.readable=v);
 const l=document.createElement('label');l.textContent='实际人数（不可判断时留空） ';
 const n=document.createElement('input');n.type='number';n.min=0;n.step=1;n.oninput=()=>f.count=n.value===''?null:Number(n.value);l.append(n);p.append(l);
 for(const seat of Object.keys(f.occupants)){
  select(p,seatLabels[seat],[['unset','请选择'],['empty','empty / 空座'],['unknown','unknown / 身份未知'],['unobservable','unobservable / 不可观察'],...obs.anchors.map(a=>[a.subject,a.subject])],
    'unset',v=>f.occupants[seat]=v==='empty'?null:v);
 }
 evidence(p,v=>f.evidence=v);
});
document.getElementById('export').onclick=()=>{
 const bad=obs.anchors.some(a=>a.reliable===null||!a.evidence.trim()) ||
 obs.frames.some(f=>f.view_compliant===null||f.readable===null||!f.evidence.trim()||
 Object.values(f.occupants).includes('unset')||(f.count!==null&&(!Number.isInteger(f.count)||f.count<0))||
 (f.readable&&(f.count===null||Object.values(f.occupants).includes('unobservable')))||
 (f.count!==null&&f.count<Object.values(f.occupants).filter(v=>v!==null&&v!=='unobservable').length));
 if(bad){document.getElementById('status').textContent='请填写全部判断、座位与依据；检查人数和可观察性是否一致。';return;}
 const note=document.getElementById('uncertainties').value.trim();obs.uncertainties=note?[note]:[];
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
 const a=document.createElement('a');a.href=url;a.download=data.item+'.human.json';a.click();URL.revokeObjectURL(url);
 document.getElementById('status').textContent='已导出。请将文件放入校准目录的 human 文件夹；这不代表 benchmark 评测完成。';
};
""")
    parts.append('</script></html>')
    return "".join(parts)


def prepare_packet(source_run, output):
    source_run, output = Path(source_run).resolve(), Path(output).resolve()
    if output == source_run or source_run in output.parents or output in source_run.parents:
        raise ValueError("Calibration output must be separate from the source run")
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Calibration packet already exists; preserve it or choose a new directory")
    source_manifest = read_json(source_run / "manifest.json")
    records = []
    # Select all existing pilot videos, never by their prior judge scores.
    for i, case in enumerate(sorted(source_manifest["cases"], key=lambda c: c["id"]), 1):
        source = source_run / case["id"]
        alignment = read_json(source / "alignment.json")
        if alignment["uncertain"] or alignment["shots"][-1]["start"] is None:
            raise ValueError(case["id"] + ": unresolved alignment needs separate calibration")
        annotation = read_json(source / "input/annotations.hidden.json")
        if annotation.get("version") == "3.1":
            raise ValueError("Legacy seat calibration cannot relabel dataset 3.1; use a separately designed opening-reference calibration")
        episode = read_json(source / "input/episode.internal.json")
        video = source / "video.mp4"
        if not video.exists():
            raise FileNotFoundError(video)
        # Validate the complete packet before extracting any frame.
        for shot in alignment["shots"]:
            if shot["start"] is None or shot["end"] <= shot["start"]:
                raise ValueError(case["id"] + ": incomplete identity/shot alignment")
        input_hashes = {name: file_hash(source / name) for name in
                        ("video.mp4", "alignment.json", "input/episode.internal.json", "input/annotations.hidden.json")}
        records.append((source, annotation, episode, alignment, input_hashes, "item-{:03d}".format(i)))
    items, links = [], []
    for source, annotation, episode, alignment, hashes, item_id in records:
        folder = output / "blind" / item_id
        frames = []
        anchors = set(annotation["identity_anchor_shots"].values())
        for shot in alignment["shots"]:
            if shot["index"] not in anchors:
                continue
            for i, fraction in enumerate((0.2, 0.5, 0.8), 1):
                label = "anchor_s{}_{}".format(shot["index"], i)
                frame = extract_frame(source / "video.mp4", shot["start"] + fraction * (shot["end"] - shot["start"]),
                                      folder / "images" / (label + ".jpg"))
                frames.append({**frame, "path": "images/" + label + ".jpg", "label": label, "shot": shot["index"], "role": "anchor"})
        final = alignment["shots"][-1]
        for i, fraction in enumerate(READOUT_FRACTIONS, 1):
            label = "readout_" + str(i)
            frame = extract_frame(source / "video.mp4", final["start"] + fraction * (final["end"] - final["start"]),
                                  folder / "images" / (label + ".jpg"))
            frames.append({**frame, "path": "images/" + label + ".jpg", "label": label,
                           "shot": final["index"], "role": "readout", "fraction": fraction})
        context = blind_context(episode, annotation)
        context["frames"] = [{k: f[k] for k in ("label", "time", "shot", "role")} for f in frames]
        input_hash = packet_hash(context, frames)
        write_json(folder / "context.json", context)
        write_json(folder / "frames.json", frames)
        write_json(folder / "human.template.json", {"item": item_id, "input_sha256": input_hash,
                                                   "observation": observation_template(context, frames)})
        (folder / "review.html").write_text(review_html(item_id, context, frames, input_hash), encoding="utf-8")
        # Private targets and provenance are excluded from the blind HTML/context.
        write_json(output / "private" / (item_id + ".annotations.json"), annotation)
        items.append({"id": item_id, "source_case": source.name, "source_sha256": hashes,
                      "input_sha256": input_hash, "annotation_sha256": digest(annotation)})
        links.append('<li><a href="' + item_id + '/review.html">' + item_id + '</a></li>')
    (output / "human").mkdir(parents=True, exist_ok=True)
    (output / "blind" / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>WorldLine · 人工校准</title><h1>WorldLine · 两帧人工校准</h1>'
        '<p>仅供评测器开发校准，不是 v3 新样本结果。请先独立完成人工标注，再查看自动裁判输出。'
        '每例三张/每身份建立镜头参照图，以及两张最终评分图。不要阅读 private 目录或历史报告。</p><ol>'
        + "".join(links) + '</ol>', encoding="utf-8")
    manifest = {"protocol": PROTOCOL, "kind": "development_calibration", "source_run": str(source_run),
                "selection": "all source pilot cases, sorted by ID; no score-based selection",
                "human_status": "pending", "judge_status": "pending", "items": items}
    write_json(output / "manifest.json", manifest)
    return manifest


def load_item(root, item):
    folder = Path(root) / "blind" / item["id"]
    context, frames = read_json(folder / "context.json"), read_json(folder / "frames.json")
    if packet_hash(context, frames) != item["input_sha256"]:
        raise ValueError("Calibration context or frame metadata changed")
    for frame in frames:
        if file_hash(folder / frame["path"]) != frame["sha256"]:
            raise ValueError("Calibration image changed")
    return folder, context, frames


def refresh_review_pages(root):
    """Refresh presentation only while no human/judge labels have been collected."""
    root = Path(root)
    if list((root / "human").glob("*.json")) or list((root / "judge-results").glob("*.json")):
        raise ValueError("Do not change a calibration packet after labeling has started")
    for item in read_json(root / "manifest.json")["items"]:
        folder, context, frames = load_item(root, item)
        (folder / "review.html").write_text(
            review_html(item["id"], context, frames, item["input_sha256"]), encoding="utf-8")


def compare_labels(root):
    root = Path(root)
    manifest = read_json(root / "manifest.json")
    totals = {k: {"agree": 0, "total": 0} for k in ("Valid", "Count", "Position", "SR")}
    raw = {k: {"agree": 0, "total": 0} for k in ("count", "occupants")}
    confusion, missing = {}, []
    for item in manifest["items"]:
        human_path = root / "human" / (item["id"] + ".human.json")
        judge_path = root / "judge-results" / (item["id"] + ".judge.json")
        if not human_path.exists() or not judge_path.exists():
            missing.append(item["id"])
            continue
        _, context, frames = load_item(root, item)
        observed = []
        for path in (human_path, judge_path):
            value = read_json(path)
            if value.get("input_sha256") != item["input_sha256"] or value.get("item") != item["id"]:
                raise ValueError("Labels refer to different calibration evidence: " + str(path))
            observation = value["observation"]
            validate_schema(observation, observation_schema(context))
            validate_observation(observation, context, [f for f in frames if f["role"] == "readout"])
            observed.append(observation)
        annotation = read_json(root / "private" / (item["id"] + ".annotations.json"))
        if digest(annotation) != item["annotation_sha256"]:
            raise ValueError("Frozen calibration targets changed")
        human, judge = [score_episode(annotation, o) for o in observed]
        for h, j in zip(observed[0]["frames"], observed[1]["frames"]):
            for field in raw:
                readable = h["count"] is not None if field == "count" else "unobservable" not in h["occupants"].values()
                if readable:
                    raw[field]["total"] += 1
                    raw[field]["agree"] += h[field] == j[field]
        key = "human_{}_judge_{}".format(human["valid"], judge["valid"])
        confusion[key] = confusion.get(key, 0) + 1
        for label, field in (("Valid", "valid"), ("SR", "joint_success")):
            totals[label]["total"] += 1
            totals[label]["agree"] += human[field] == judge[field]
        # Denominator is human-valid cases; judge rejection counts as disagreement.
        for label, field in (("Count", "count_correct"), ("Position", "position_correct")):
            if human["valid"]:
                totals[label]["total"] += 1
                totals[label]["agree"] += human[field] == judge[field]
    for value in list(totals.values()) + list(raw.values()):
        value["rate"] = value["agree"] / value["total"] if value["total"] else None
    return {"protocol": PROTOCOL, "complete": not missing, "pending_items": missing,
            "score_agreement": totals, "observation_agreement": raw, "valid_confusion": confusion,
            "release_ready": False,
            "note": "Development agreement only, not independent held-out judge validation or benchmark results."}
