#!/usr/bin/env python3
"""Predeclare a balanced 16-case acceptance subset; never call a paid API."""

import argparse
import html
import json
import os
from collections import Counter
from pathlib import Path

from worldline.annotations import digest
from worldline.core_v3 import REFERENCE_VERSION, plan_mixed_core
from worldline.video import read_json, write_json
from worldline.artifacts import index_existing_cases

BASE = Path(__file__).resolve().parent


def select_cases():
    cases = plan_mixed_core(REFERENCE_VERSION)
    selected, scenes = [], Counter()
    for ti, task in enumerate(sorted({c['task'] for c in cases})):
        for vi, view in enumerate(('reverse_axis', 'overhead')):
            for n in (3, 4):
                shots = 3 + (ti + vi + n - 3) % 2
                candidates = [c for c in cases if c['task'] == task and c['viewpoint_mode'] == view
                              and c['subject_count'] == n and c['shot_count'] == shots]
                case = min(candidates, key=lambda c: (scenes[c['scene']], c['id']))
                selected.append(case)
                scenes[case['scene']] += 1
    return selected


def prompt_report(selection, dataset, output):
    """Inspect saved outputs only; never mark a human or video acceptance as passed."""
    index = index_existing_cases(dataset, dataset_version=REFERENCE_VERSION)
    rows, errors, cards = [], [], []
    for case in selection['cases']:
        folder = dataset / case['id']
        run = index['by_id'].get(case['id'])
        if run is None:
            errors.append(case['id'] + ': missing or invalid completed construction')
            continue
        prompt = (folder / 'prompt.txt').read_text()
        row = {k: case[k] for k in ('id', 'task', 'scene', 'subject_count', 'shot_count', 'viewpoint_mode', 'source_id')}
        row.update(words=len(prompt.split()), construction_calls=len(run['trace']),
                   reported_cost_usd=sum((t.get('usage') or {}).get('cost', 0) or 0 for t in run['trace']),
                   prompt_sha256=digest(prompt), independent_llm_audit_passed=True)
        rows.append(row)
        relative = os.path.relpath(folder, output)
        links = ' · '.join('<a href="' + html.escape(relative + '/' + name) + '">' + html.escape(label) + '</a>'
                           for name, label in [('prompt.txt', '公开 Prompt'), ('run.json', '来源及全部阶段'),
                                               ('episode.internal.json', '状态与相机'), ('annotations.hidden.json', '隐藏标注')])
        source = run['source']
        cards.append('<section><h2>' + html.escape(case['id']) + '</h2><p>' +
                     html.escape(case['task'] + ' · ' + case['scene']) + '</p><p>' + links + '</p><pre>' +
                     html.escape(prompt) + '</pre><details><summary>素材与故事骨架</summary><pre>' +
                     html.escape(json.dumps({'source_id': source['id'], 'excerpt': source['excerpt'],
                                             'skeleton': run['stage_outputs']['source_abstraction']}, ensure_ascii=False, indent=2)) +
                     '</pre></details></section>')
    if len({(dataset / c['id'] / 'prompt.txt').read_text() for c in selection['cases']
            if (dataset / c['id'] / 'prompt.txt').exists()}) != len(rows):
        errors.append('Duplicate public prompts')
    report = {'version': REFERENCE_VERSION, 'selection_sha256': selection['selection_sha256'],
              'planned': len(selection['cases']), 'completed': len(rows), 'errors': errors,
              'coverage': selection['coverage'], 'cases': rows, 'release_ready': False,
              'note': 'Structural checks and independent LLM audit only; not human or video acceptance.'}
    write_json(output / 'prompt-review.json', report)
    (output / 'prompts.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WorldLine · 16 条新版候选 Prompt</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#182638;background:#f3f5f8}section{background:white;margin:24px 0;padding:24px;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}h2{font-size:20px;overflow-wrap:anywhere}</style><h1>WorldLine · 16 条新版候选 Prompt</h1><p>v3.1 · 五阶段独立 LLM 构造 · 真实素材、中间状态、修复与失败记录均保留。此页的结构检查和 LLM 审核不代表人工验收或正式 benchmark 放行。</p>' + ''.join(cards) + '</html>', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / 'experiments/acceptance-v3.1-16/selection.json')
    parser.add_argument('--phase', choices=['plan', 'prompt-report'], default='plan')
    parser.add_argument('--dataset', type=Path, default=BASE / 'outputs/v3.1')
    args = parser.parse_args()
    if args.phase == 'prompt-report':
        report = prompt_report(read_json(args.output), args.dataset, args.output.parent)
        print('Completed:', report['completed'], 'Errors:', report['errors'])
        raise SystemExit(1 if report['errors'] else 0)
    cases = select_cases()
    plan = {
        'dataset_version': REFERENCE_VERSION,
        'purpose': 'Development acceptance pilot, not a formal benchmark result or held-out judge validation',
        'selection_rule': 'One per task x viewpoint x subject count; balance shots and rotate scenes before generation',
        'replacement_policy': 'No replacements based on video outcomes; construction failures remain in the declared subset',
        'cases': cases,
        'selection_sha256': digest(cases),
        'coverage': {f: dict(Counter(str(c[f]) for c in cases)) for f in
                     ('task', 'scene', 'subject_count', 'viewpoint_mode', 'shot_count')},
        'generation': {'model': 'bytedance/seedance-2.0-fast', 'resolution': '480p',
                       'seconds_per_shot': 3, 'seed': 42, 'generate_audio': False},
        'judge': {'model': 'openai/gpt-5.6-sol', 'protocol': 'worldline-llm-judge-v4'},
    }
    if args.output.exists() and read_json(args.output) != plan:
        raise ValueError('Frozen pilot plan differs; do not overwrite an existing selection')
    write_json(args.output, plan)
    print(args.output.resolve())
    print(plan['coverage'])


if __name__ == '__main__':
    main()
