#!/usr/bin/env python3
"""Local, answer-blind opening-reference calibration. No API calls or fake labels."""

import argparse
import html
import json
import shutil
from functools import partial
from pathlib import Path

from worldline.annotations import digest
from worldline.evaluation import REFERENCE_PROTOCOL, EVIDENCE_PROTOCOLS, SCOPED_EVIDENCE_PROTOCOL
from worldline.evidence_evaluation import COUNT_SCOPE_HELP, score_evidence_episode, validate_evidence_observation
from worldline.reference_evaluation import score_reference_episode, validate_reference_observation
from worldline.video import file_hash, read_json, write_json


def protocol_functions(protocol):
    if protocol in EVIDENCE_PROTOCOLS:
        return validate_evidence_observation, partial(score_evidence_episode, protocol=protocol)
    if protocol == REFERENCE_PROTOCOL:
        return validate_reference_observation, score_reference_episode
    raise ValueError('Calibration requires a v4, v5 or v5.1 reference run')


def packet_hash(context, frames, protocol=REFERENCE_PROTOCOL):
    protocol_functions(protocol)
    return digest({'protocol': protocol, 'context': context,
                   'frames': [{k: f[k] for k in ('label', 'role', 'shot', 'time', 'sha256')} for f in frames]})


def blank_observation(context, protocol=REFERENCE_PROTOCOL):
    protocol_functions(protocol)
    observed = {
        'anchors': [{'subject': a['id'], 'reliable': None, 'evidence': ''} for a in context['identity_references']],
        'opening': {'view_compliant': None, 'readable': None, 'layout_usable': None, 'count': None,
                    'places': {p: {'description': '', 'occupant': 'unset'} for p in context['places']}, 'evidence': ''},
        'frames': [{'frame': 'readout_' + str(i), 'view_compliant': None, 'readable': None, 'count': None,
                    'occupants': {p: 'unset' for p in context['places']}, 'evidence': ''} for i in (1, 2)],
        'uncertainties': [],
    }
    if protocol in EVIDENCE_PROTOCOLS:
        for key in ('view_compliant', 'layout_usable'):
            observed['opening'].pop(key)
        for frame in observed['frames']:
            for key in ('view_compliant', 'readable'):
                frame.pop(key)
            frame['layout_changed'] = 'unset'
    return observed


def review_html(item, context, frames, input_hash, protocol=REFERENCE_PROTOCOL):
    esc = html.escape
    data = {'protocol': protocol, 'item': item, 'input_sha256': input_hash,
            'observation': blank_observation(context, protocol)}
    intro = ('证据标准 ' + protocol.rsplit('-', 1)[-1] + '：不要求精确摄影或预设布局；明确的人数和位置错误进入评分，不判 Invalid。'
             if protocol in EVIDENCE_PROTOCOLS else '开场参照协议 v4')
    scope = ('<p>' + esc(COUNT_SCOPE_HELP) + '</p>') if protocol == SCOPED_EVIDENCE_PROTOCOL else ''
    parts = ['<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>WorldLine · 开场参照盲标</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#182638}section{border-top:1px solid #ccc;padding:20px 0}.images{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%}figure{margin:0}label{display:inline-block;margin:8px 16px 8px 0}select,input,textarea,button{font:inherit;padding:6px}textarea{display:block;width:95%;min-height:48px}pre{white-space:pre-wrap}#status{white-space:pre-wrap;color:#963d22}.place{padding:10px;background:#f4f6f8;margin:8px 0}button{margin:16px 8px 0 0}@media(max-width:650px){.images{grid-template-columns:1fr}}</style>',
             '<h1>WorldLine · ' + esc(item) + '</h1><p>' + intro + ' · 独立人工标注。此页不显示模型判断、目标占位或自动分数。请先完成标注，再查看评测报告。</p>',
             '<p>先根据开场图定义物理位置 P1…PN：按第一张图从左到右编号，同横坐标按近到远。包括入场案例的空位。之后位置编号不随反打后的画面左右改变，不以预期人物反推位置。</p>',
             '<p>多出、漏掉或站立的人都计入互动区域人数；可见错误不是不可观察。空位选 empty；可见但无法匹配身份选 unknown；位置被遮挡或跨视角对应确实无法确定选 unobservable。</p>',
             '<p>自动保存在本浏览器。开场可观察时，必须简述每个物理位置，不能只写人物衣服颜色。v5 若判断物理布局已改变，必须写明视觉依据；其他备注可选。人数必须是互动区域完整总数，不能确定总数时留空。</p>',
             scope + '<h2>人物身份</h2><ul>' + ''.join('<li>' + esc(a['id'] + ': ' + a['descriptor']) + '</li>' for a in context['identity_references']) + '</ul>',
             '<div id="anchors"></div><h2>开场要求</h2><p>' + esc(context['opening_request']['content']) + '</p><p>' + esc(context['opening_request']['viewpoint']) + '</p>']
    for role, title in (('opening', '开场两帧：建立参照，不计主分'), ('anchor', '入场身份参照：不证明更新成功'), ('readout', '最终全景两帧：独立记录当前事实')):
        selected = [f for f in frames if f['role'] == role]
        if role == 'readout':
            parts.append('<section><h2>要求的中间 Update</h2><p>' + esc(' '.join(u['content'] for u in context['updates'])) + '</p><p>最终镜头：' + esc(context['final_view']) + '</p></section>')
        if selected:
            parts.append('<section><h2>' + title + '</h2><div class="images">')
            for f in selected:
                parts.append('<figure><img src="' + esc(f['path']) + '"><figcaption>' + esc(f['label']) + ' · ' + str(f['time']) + 's</figcaption></figure>')
            parts.append('</div>')
            if role == 'opening':
                parts.append('<div id="opening"></div>')
            elif role == 'readout':
                parts.append('<div id="frame-0"></div><div id="frame-1"></div>')
            parts.append('</section>')
    parts.append('<label>不确定性备注</label><textarea id="uncertainties"></textarea><button id="export">导出人工标注 JSON</button><p id="status"></p><script>')
    parts.append('let data=' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + ';')
    parts.append(r'''
const v5=['worldline-llm-judge-v5','worldline-llm-judge-v5.1'].includes(data.protocol);
const key='worldline-'+data.protocol.split('-').pop()+'-human:'+data.item+':'+data.input_sha256;
try{const old=JSON.parse(localStorage.getItem(key)||'null');if(old&&old.input_sha256===data.input_sha256)data=old;}catch(e){}
const obs=data.observation;
function save(){try{localStorage.setItem(key,JSON.stringify(data));}catch(e){document.getElementById('status').textContent='浏览器无法保存草稿，请及时导出。';}}
function select(parent,label,options,current,change){const l=document.createElement('label');l.append(document.createTextNode(label+' '));const s=document.createElement('select');for(const [value,text]of options){const o=document.createElement('option');o.value=value;o.textContent=text;s.append(o);}s.value=current;s.onchange=()=>{change(s.value);save();};l.append(s);parent.append(l);}
function bool(parent,label,obj,k){select(parent,label,[['','请选择'],['true','是'],['false','否']],obj[k]===null?'':String(obj[k]),v=>obj[k]=v===''?null:v==='true');}
function note(parent,label,obj,k){const t=document.createElement('textarea');t.placeholder=label;t.value=obj[k];t.oninput=()=>{obj[k]=t.value;save();};parent.append(t);}
function occupant(parent,label,obj,k){select(parent,label,[['unset','请选择'],['empty','empty / 空位'],['unknown','unknown / 身份未知'],['unobservable','unobservable / 无法观察'],...obs.anchors.map(a=>[a.subject,a.subject])],obj[k]===null?'empty':obj[k],v=>obj[k]=v==='empty'?null:v);}
function count(parent,obj){const l=document.createElement('label');l.textContent='实际人数（不可判断时留空） ';const n=document.createElement('input');n.type='number';n.min=0;n.step=1;n.value=obj.count===null?'':obj.count;n.oninput=()=>{obj.count=n.value===''?null:Number(n.value);save();};l.append(n);parent.append(l);}
for(const a of obs.anchors){const p=document.getElementById('anchors');bool(p,a.subject+' 身份参照可靠',a,'reliable');}
const op=document.getElementById('opening');if(!v5){bool(op,'开场是建立场景的全景',obs.opening,'view_compliant');bool(op,'基本布局与物理位置可用',obs.opening,'layout_usable');}bool(op,'两帧初始状态稳定且可观察',obs.opening,'readable');count(op,obs.opening);
for(const [p,v]of Object.entries(obs.opening.places)){const d=document.createElement('div');d.className='place';occupant(d,p+' 开场占用',v,'occupant');note(d,p+' 物理位置描述，如桌子远端；不要只写人物身份',v,'description');op.append(d);}note(op,'开场依据（可选）',obs.opening,'evidence');
obs.frames.forEach((f,i)=>{const p=document.getElementById('frame-'+i);const h=document.createElement('h3');h.textContent='最终帧 '+(i+1);p.append(h);if(v5){const help=document.createElement('p');help.textContent='物理布局改变指相对实际开场的空间结构变化，不是未遵守文本、视角改变或要求的人物入场/离场/换位。部分位置无法对应但有明确错误，仍可以评分。';p.append(help);select(p,'物理布局是否改变',[['unset','请选择'],['true','是，有明确证据'],['false','否，布局保持'],['null','无法确定']],f.layout_changed===null?'null':String(f.layout_changed),v=>f.layout_changed=v==='unset'?'unset':v==='null'?null:v==='true');}else{bool(p,'要求的视角与区域覆盖合规',f,'view_compliant');bool(p,'人数及同一物理位置对应可观察',f,'readable');}count(p,f);for(const k of Object.keys(f.occupants))occupant(p,k+' 当前占用',f.occupants,k);note(p,v5?'该帧依据（物理布局改变时必填）':'该帧依据（可选）',f,'evidence');});
const notes=document.getElementById('uncertainties');notes.value=obs.uncertainties.join('\n');notes.oninput=()=>{obs.uncertainties=notes.value.trim()?[notes.value.trim()]:[];save();};
document.getElementById('export').onclick=()=>{
 const errors=[];
 for(const a of obs.anchors)if(a.reliable===null)errors.push(a.subject+'：未判断身份参照是否可靠');
 const rows=[['开场',obs.opening,Object.fromEntries(Object.entries(obs.opening.places).map(([p,v])=>[p,v.occupant]))],...obs.frames.map((f,i)=>['最终帧 '+(i+1),f,f.occupants])];
 for(const [label,row,occ]of rows){for(const k of (v5?(row===obs.opening?['readable']:[]):['view_compliant','readable']))if(row[k]===null)errors.push(label+'：未填写 '+k);for(const[p,v]of Object.entries(occ))if(v==='unset')errors.push(label+'：未填写 '+p+' 占用');if(row.count!==null&&(!Number.isInteger(row.count)||row.count<0))errors.push(label+'：人数必须是非负整数');if(row.readable&&(row.count===null||Object.values(occ).includes('unobservable')))errors.push(label+'：可观察与人数/位置无法判断矛盾');if(row.count!==null&&row.count<Object.values(occ).filter(v=>v!==null&&v!=='unobservable'&&v!=='unset').length)errors.push(label+'：人数少于可见占用位置数');if(v5&&row!==obs.opening){if(row.layout_changed==='unset')errors.push(label+'：未判断物理布局变化');if(row.layout_changed===true&&!row.evidence.trim())errors.push(label+'：请说明物理布局改变的视觉依据');}}
 if(!v5&&obs.opening.layout_usable===null)errors.push('开场：未判断基本布局');
 if(obs.opening.readable)for(const[p,v]of Object.entries(obs.opening.places))if(!v.description.trim())errors.push('开场 '+p+'：请简述物理位置');
 if(errors.length){document.getElementById('status').textContent=errors.join('\n');return;}
 save();const u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=data.item+'.human.json';a.click();URL.revokeObjectURL(u);document.getElementById('status').textContent='已导出。导入校准工具后才计入人工一致性统计；不会自动通过正式验收。';
};
''')
    return ''.join(parts) + '</script></html>'


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError('Calibration must be separate from the evaluation directory')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Preserve the existing calibration packet; use another directory')
    run = read_json(source / 'manifest.json')
    protocol = run['judge']['protocol']
    validator, _ = protocol_functions(protocol)
    items, pending, links = [], [], []
    for i, case in enumerate(sorted(run['cases'], key=lambda c: c['id']), 1):
        item, directory = 'item-{:03d}'.format(i), source / case['id']
        if not (directory / 'frames.json').exists() or not (directory / 'reference.context.json').exists():
            pending.append({'item': item, 'case': case['id'], 'reason': 'evidence_not_ready'})
            continue
        context, frames = read_json(directory / 'reference.context.json'), read_json(directory / 'frames.json')
        if sum(f['role'] == 'opening' for f in frames) != 2 or sum(f['role'] == 'readout' for f in frames) != 2:
            pending.append({'item': item, 'case': case['id'], 'reason': 'alignment_requires_separate_review'})
            continue
        folder = output / 'blind' / item
        copied = []
        for f in frames:
            if file_hash(f['path']) != f['sha256']:
                raise ValueError('Source image hash mismatch')
            relative = 'images/' + f['label'] + '.jpg'
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f['path'], target)
            copied.append({**f, 'path': relative})
        hashed = packet_hash(context, copied, protocol)
        write_json(folder / 'context.json', context)
        write_json(folder / 'frames.json', copied)
        (folder / 'review.html').write_text(review_html(item, context, copied, hashed, protocol), encoding='utf-8')
        record = {'id': item, 'source_case': case['id'], 'input_sha256': hashed, 'judge_sha256': None}
        if (directory / 'observation.json').exists():
            observation = read_json(directory / 'observation.json')
            validator(observation, context, [f for f in frames if f['role'] == 'readout'])
            write_json(output / 'private' / (item + '.judge.json'), observation)
            record['judge_sha256'] = digest(observation)
        items.append(record)
        links.append('<li><a href="' + item + '/review.html">' + item + '</a></li>')
    (output / 'human').mkdir(parents=True, exist_ok=True)
    (output / 'blind').mkdir(parents=True, exist_ok=True)
    (output / 'blind/index.html').write_text('<!doctype html><meta charset="utf-8"><title>WorldLine · 人工校准</title><h1>WorldLine · 开场参照人工校准</h1><p>' + html.escape(protocol) + '</p><p>开发校准集，不是正式结果或独立留出集验证。请先独立标注，再看自动报告；不要读取 private 目录。每例开场两帧、最终两帧；入场例另有两张身份参照。草稿在浏览器保存，物理布局改变须说明依据。</p><ol>' + ''.join(links) + '</ol><p>待解决证据：' + str(len(pending)) + '</p>', encoding='utf-8')
    manifest = {'protocol': protocol, 'kind': 'development_calibration', 'source_run': str(source),
                'planned_items': len(run['cases']), 'items': items, 'pending_evidence': pending,
                'selection': 'All predeclared pilot cases; no score-based exclusion', 'human_status': 'pending'}
    write_json(output / 'manifest.json', manifest)
    return manifest


def load_item(root, item):
    protocol = read_json(Path(root) / 'manifest.json')['protocol']
    folder = Path(root) / 'blind' / item['id']
    context, frames = read_json(folder / 'context.json'), read_json(folder / 'frames.json')
    if packet_hash(context, frames, protocol) != item['input_sha256']:
        raise ValueError('Frozen context or image metadata changed')
    for f in frames:
        if file_hash(folder / f['path']) != f['sha256']:
            raise ValueError('Frozen image changed')
    return context, frames


def validate_label(root, item, value):
    protocol = read_json(Path(root) / 'manifest.json')['protocol']
    validator, scorer = protocol_functions(protocol)
    if value.get('protocol') != protocol or value.get('item') != item['id'] or value.get('input_sha256') != item['input_sha256']:
        raise ValueError('Label belongs to different evidence or protocol')
    context, frames = load_item(root, item)
    validator(value['observation'], context, [f for f in frames if f['role'] == 'readout'])
    return scorer(context, value['observation'])


def compare(root):
    root = Path(root)
    manifest = read_json(root / 'manifest.json')
    _, scorer = protocol_functions(manifest['protocol'])
    totals = {k: {'agree': 0, 'total': 0} for k in ('Valid', 'Count', 'Position', 'SR')}
    pending, cases = [], []
    for item in manifest['items']:
        path = root / 'human' / (item['id'] + '.human.json')
        if not path.exists() or item['judge_sha256'] is None:
            pending.append(item['id'])
            continue
        human = validate_label(root, item, read_json(path))
        context, _ = load_item(root, item)
        observed = read_json(root / 'private' / (item['id'] + '.judge.json'))
        if digest(observed) != item['judge_sha256']:
            raise ValueError('Frozen judge observation changed')
        judge = scorer(context, observed)
        for label, field in (('Valid', 'valid'), ('Count', 'count_correct'), ('Position', 'position_correct'), ('SR', 'joint_success')):
            if label in ('Count', 'Position') and not human['valid']:
                continue
            totals[label]['total'] += 1
            totals[label]['agree'] += human[field] == judge[field]
        cases.append({'item': item['id'], 'human': human, 'judge': judge})
    for row in totals.values():
        row['rate'] = row['agree'] / row['total'] if row['total'] else None
    report = {'protocol': manifest['protocol'], 'complete': bool(manifest['items']) and not pending and not manifest['pending_evidence'],
              'pending_items': pending, 'pending_evidence': manifest['pending_evidence'], 'score_agreement': totals,
              'cases': cases, 'release_ready': False,
              'note': 'Human labels required. Development agreement is not independent held-out judge validation.'}
    write_json(root / 'agreement.report.json', report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=['prepare', 'import', 'compare'], default='prepare')
    p.add_argument('--source-run', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--human-file', action='append', type=Path)
    args = p.parse_args()
    if args.phase == 'prepare':
        if not args.source_run:
            p.error('--source-run is required')
        result = prepare(args.source_run, args.output)
        print('Ready:', len(result['items']), 'Pending evidence:', len(result['pending_evidence']))
    elif args.phase == 'import':
        if not args.human_file:
            p.error('--human-file is required')
        items = {i['id']: i for i in read_json(args.output / 'manifest.json')['items']}
        for path in args.human_file:
            value = read_json(path)
            item = items[value['item']]
            validate_label(args.output, item, value)
            dest = args.output / 'human' / (item['id'] + '.human.json')
            if dest.exists() and read_json(dest) != value:
                raise FileExistsError('Do not overwrite an existing human label: ' + str(dest))
            write_json(dest, value)
    if args.phase != 'prepare':
        result = compare(args.output)
        print('Complete:', result['complete'], 'Pending human/judge:', len(result['pending_items']))


if __name__ == '__main__':
    main()
