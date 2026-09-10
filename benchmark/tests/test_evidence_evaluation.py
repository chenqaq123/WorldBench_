"""v5 regression tests use synthetic observations only; no paid API calls."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from calibrate_reference import (blank_observation, compare, packet_hash,
                                prepare as prepare_calibration, validate_label)
from run_evaluation import DEFAULT_JUDGE, generation_parameters, prepare
from test_reference_calibration import fixture as calibration_fixture
from test_reference_evaluation import context_and_observation, constructed
from validate_evaluation import validate_run
from worldline.artifacts import write_pipeline_result
from worldline.core_v3 import plan_mixed_core
from worldline.evaluation import EVIDENCE_PROTOCOL, SCOPED_EVIDENCE_PROTOCOL, REFERENCE_PROTOCOL, write_report
from worldline.evidence_evaluation import (EVIDENCE_SYSTEM, COUNT_SCOPE_HELP, evidence_system, derive_evidence_target, evidence_schema,
    required_evidence_ready, score_evidence_episode, validate_evidence_observation)
from worldline.judge import evaluate_video
from worldline.video import file_hash, read_json, write_json


def convert_fixture(observed):
    """Only synthetic test fixtures may be converted; never upgrade real v4 results."""
    observed = copy.deepcopy(observed)
    for field in ('view_compliant', 'layout_usable'):
        observed['opening'].pop(field)
    for frame in observed['frames']:
        for field in ('view_compliant', 'readable'):
            frame.pop(field)
        frame['layout_changed'] = False
    return observed


def fixture(task='position_swap'):
    context, observed = context_and_observation(task)
    return context, convert_fixture(observed)


class EvidenceEvaluationTests(unittest.TestCase):
    def test_all_tasks_and_two_fixed_readouts(self):
        for task in ('static_viewpoint_change', 'person_entry', 'person_exit', 'position_swap'):
            context, observed = fixture(task)
            score = score_evidence_episode(context, observed)
            self.assertTrue(score['joint_success'], task)
            self.assertIsNone(score['view_compliant'])
            self.assertEqual(score['target']['expected_occupants']['P3'], 'C')

    def test_no_photography_or_prescribed_layout_gate(self):
        context, old = context_and_observation()
        old['opening']['view_compliant'] = False
        old['opening']['layout_usable'] = False
        old['frames'][0]['view_compliant'] = False
        self.assertTrue(score_evidence_episode(context, convert_fixture(old))['valid'])
        schema = evidence_schema(context)
        self.assertNotIn('view_compliant', json.dumps(schema))
        self.assertNotIn('layout_usable', json.dumps(schema))
        self.assertIn('Do not assume reverse was executed', EVIDENCE_SYSTEM)

    def test_actual_initial_order_and_final_independent_target(self):
        context, observed = fixture()
        observed['opening']['places']['P1']['occupant'] = 'B'
        observed['opening']['places']['P2']['occupant'] = 'A'
        target = derive_evidence_target(context, observed['opening'], observed['anchors'])
        self.assertEqual(target['expected_occupants'], {'P1': 'A', 'P2': 'B', 'P3': 'C'})
        for frame in observed['frames']:
            frame['occupants'] = target['expected_occupants'].copy()
        self.assertTrue(score_evidence_episode(context, observed)['joint_success'])
        observed['frames'][0]['occupants']['P3'] = 'unknown'
        self.assertEqual(score_evidence_episode(context, observed)['target'], target)

    def test_extra_person_is_count_failure_not_invalid(self):
        context, observed = fixture()
        observed['frames'][1]['count'] += 1
        score = score_evidence_episode(context, observed)
        self.assertTrue(score['valid'])
        self.assertFalse(score['count_correct'])
        self.assertTrue(score['position_correct'])
        self.assertFalse(score['joint_success'])

    def test_missing_subject_is_count_and_position_failure(self):
        context, observed = fixture()
        observed['frames'][0]['count'] -= 1
        observed['frames'][0]['occupants']['P3'] = None
        score = score_evidence_episode(context, observed)
        self.assertTrue(score['valid'])
        self.assertFalse(score['count_correct'])
        self.assertFalse(score['position_correct'])

    def test_count_correct_position_wrong_even_outside_swap(self):
        context, observed = fixture('person_exit')
        observed['frames'][1]['occupants'] = {'P1': 'A', 'P2': 'C', 'P3': None}
        score = score_evidence_episode(context, observed)
        self.assertTrue(score['valid'])
        self.assertTrue(score['count_correct'])
        self.assertFalse(score['position_correct'])

    def test_visible_layout_error_wins_over_unmapped_places(self):
        context, observed = fixture()
        frame = observed['frames'][0]
        frame.update(layout_changed=True, occupants={p: 'unobservable' for p in context['places']},
                     evidence='Synthetic evidence: chairs formerly on opposite sides are now all on one side.')
        score = score_evidence_episode(context, observed)
        self.assertTrue(score['valid'])
        self.assertTrue(score['count_correct'])
        self.assertFalse(score['position_correct'])

    def test_one_known_mismatch_is_sufficient_for_position_failure(self):
        context, observed = fixture()
        observed['frames'][0]['occupants'] = {'P1': None, 'P2': 'unobservable', 'P3': 'unobservable'}
        score = score_evidence_episode(context, observed)
        self.assertTrue(score['valid'])
        self.assertFalse(score['position_correct'])

    def test_unobservable_without_contradiction_is_invalid(self):
        context, observed = fixture()
        observed['frames'][0]['occupants']['P3'] = 'unobservable'
        score = score_evidence_episode(context, observed)
        self.assertFalse(score['valid'])
        self.assertIsNone(score['count_correct'])
        self.assertIsNone(score['position_correct'])

    def test_complete_count_required_even_with_position_error(self):
        context, observed = fixture()
        observed['frames'][0].update(count=None, layout_changed=True)
        self.assertFalse(score_evidence_episode(context, observed)['valid'])

    def test_layout_evidence_required_and_legacy_schema_rejected(self):
        context, observed = fixture()
        observed['frames'][0].update(layout_changed=True, evidence=' ')
        with self.assertRaisesRegex(ValueError, 'explicit visual evidence'):
            score_evidence_episode(context, observed)
        _, legacy = context_and_observation()
        with self.assertRaises(ValueError):
            score_evidence_episode(context, legacy)

    def test_unknown_visible_identity_is_wrong_not_unobservable(self):
        context, observed = fixture()
        observed['frames'][0]['occupants']['P3'] = 'unknown'
        score = score_evidence_episode(context, observed)
        self.assertTrue(score['valid'])
        self.assertFalse(score['position_correct'])

    def test_reference_identity_and_count_guards_retained(self):
        context, observed = fixture()
        observed['anchors'][0]['reliable'] = False
        self.assertFalse(score_evidence_episode(context, observed)['reference_valid'])
        context, observed = fixture()
        observed['opening']['count'] += 1
        self.assertFalse(score_evidence_episode(context, observed)['reference_valid'])

    def test_two_readouts_are_both_mandatory_and_ordered(self):
        context, observed = fixture()
        for frames in (observed['frames'][:1], list(reversed(observed['frames']))):
            with self.assertRaises(ValueError):
                score_evidence_episode(context, {**observed, 'frames': frames})

    def test_unused_partial_uncertainty_not_gate_but_entry_anchor_is(self):
        alignment = {'uncertain': True, 'shots': [
            {'index': i, 'start': (i-1)*3, 'end': i*3, 'transition': 'uncertain' if i == 2 else 'cut'}
            for i in range(1, 5)]}
        frames = [{'shot': shot, 'role': role} for shot, role in ((1, 'opening'), (2, 'anchor'), (4, 'readout')) for _ in (1, 2)]
        annotations = {'identity_anchor_shots': {'A': 1, 'B': 1}}
        self.assertTrue(required_evidence_ready(alignment, frames, annotations))
        self.assertFalse(required_evidence_ready(alignment, frames, {'identity_anchor_shots': {'A': 1, 'B': 2}}))
        alignment['shots'][-1]['transition'] = 'uncertain'
        self.assertFalse(required_evidence_ready(alignment, frames, annotations))
        alignment['shots'][-1]['transition'] = 'cut'
        self.assertFalse(required_evidence_ready(alignment, frames[1:], annotations))

    def test_offline_end_to_end_and_legacy_output_isolation(self):
        self._offline_end_to_end(EVIDENCE_PROTOCOL)

    def test_scoped_offline_end_to_end_and_report(self):
        self._offline_end_to_end(SCOPED_EVIDENCE_PROTOCOL)

    def _offline_end_to_end(self, protocol):
        case = next(c for c in plan_mixed_core('3.1') if c['task'] == 'position_swap' and c['subject_count'] == 3 and c['shot_count'] == 4)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            result = constructed(case)
            write_pipeline_result(result, root / 'dataset')
            write_json(root / 'dataset/core_matrix.manifest.json', {'version': '3.1', 'cases': [{**case, 'status': 'complete'}]})
            args = SimpleNamespace(output=root / 'evaluation', dataset=root / 'dataset', model='test-video',
                judge=DEFAULT_JUDGE, protocol=protocol, seconds_per_shot=3, resolution='480p',
                seed=42, case_id=[case['id']], all_cases=False, phase='plan')
            manifest = prepare(args)
            pending = write_report(args.output, manifest)
            self.assertIsNone(pending['micro']['valid_observation_rate'])
            self.assertEqual(pending['protocol'], protocol)
            directory = args.output / case['id']
            video = directory / 'video.mp4'
            video.write_bytes(b'synthetic video fixture')
            write_json(directory / 'video.metadata.json', {'sha256': file_hash(video), 'duration': 12, 'width': 864, 'height': 480})
            write_json(directory / 'generation.request.json', {**generation_parameters(manifest['generation'], manifest['cases'][0]),
                'prompt': result['rendered_prompt'].strip()})
            alignment = {'uncertain': True, 'extra_cuts': False, 'shots': [
                {'index': i, 'start': (i-1)*3, 'end': i*3, 'transition': 'uncertain' if i == 2 else 'cut'} for i in range(1, 5)]}
            write_json(directory / 'alignment.json', alignment)
            _, observed = fixture()
            observed['frames'][0].update(layout_changed=True, occupants={p: 'unobservable' for p in ('P1', 'P2', 'P3')})
            client = Mock()
            client.request.return_value = {'choices': [{'message': {'content': json.dumps(observed)}}], 'usage': {'cost': 0}}
            def extract(video, time, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'synthetic image fixture')
                return {'path': str(path), 'time': time, 'sha256': file_hash(path)}
            with patch('worldline.judge.align_video', return_value=alignment), patch('worldline.judge.extract_frame', side_effect=extract), patch(
                    'worldline.judge.contact_sheet'), patch('worldline.judge.prepare_overview'):
                score = evaluate_video(client, directory, manifest['judge'])
            client.request.assert_called_once()
            trace = read_json(directory / 'judge/reference_observer/request.json')
            self.assertEqual(trace['protocol'], protocol)
            self.assertEqual(trace['system'], evidence_system(protocol))
            self.assertTrue(score['valid'])
            self.assertFalse(score['position_correct'])
            audit = validate_run(args.output)
            self.assertFalse(audit['errors'], audit['errors'])
            report = write_report(args.output, manifest)
            self.assertEqual(report['micro']['valid_observation_rate'], 1)
            self.assertEqual(report['micro']['position_accuracy'], 0)
            self.assertIn('不要求精确执行摄影', (args.output / 'report.html').read_text())
            if protocol == SCOPED_EVIDENCE_PROTOCOL:
                self.assertIn(COUNT_SCOPE_HELP, (args.output / 'report.html').read_text())
            # A blocked required range must not invoke the observer at all.
            alignment['shots'][0]['transition'] = 'uncertain'
            client.reset_mock()
            before_score = (directory / 'score.json').read_bytes()
            with patch('worldline.judge.align_video', return_value=alignment), patch('worldline.judge.build_evidence', return_value=[]):
                with self.assertRaisesRegex(ValueError, 'Saved observation conflicts'):
                    evaluate_video(client, directory, manifest['judge'])
            self.assertEqual((directory / 'score.json').read_bytes(), before_score)
            client.request.assert_not_called()
            # A fresh unresolved case records failure without stale observations.
            fresh = root / 'fresh-evaluation'
            write_json(fresh / 'input/episode.internal.json', result['episode'])
            write_json(fresh / 'input/annotations.hidden.json', result['annotations'])
            (fresh / 'video.mp4').write_bytes(b'synthetic video fixture')
            with patch('worldline.judge.align_video', return_value=alignment), patch('worldline.judge.build_evidence', return_value=[]):
                blocked = evaluate_video(client, fresh, manifest['judge'])
            self.assertFalse(blocked['valid'])
            self.assertFalse((fresh / 'observation.json').exists())
            client.request.assert_not_called()
            # Direct API calls cannot relabel a v4 output as v5.
            write_json(directory / 'score.json', {'protocol': REFERENCE_PROTOCOL})
            before = (directory / 'score.json').read_bytes()
            with self.assertRaisesRegex(ValueError, 'separate output'):
                evaluate_video(client, directory, manifest['judge'])
            self.assertEqual((directory / 'score.json').read_bytes(), before)

    def test_v5_human_calibration_is_blind_and_protocol_bound(self):
        self._human_calibration(EVIDENCE_PROTOCOL)

    def test_scoped_human_calibration_is_blind_and_protocol_bound(self):
        self._human_calibration(SCOPED_EVIDENCE_PROTOCOL)

    def _human_calibration(self, protocol):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, old = calibration_fixture(root)
            manifest = read_json(source / 'manifest.json')
            manifest['judge']['protocol'] = protocol
            write_json(source / 'manifest.json', manifest)
            observed = convert_fixture(old)
            write_json(source / 'case-a/observation.json', observed)
            context = read_json(source / 'case-a/reference.context.json')
            frames = read_json(source / 'case-a/frames.json')
            self.assertNotEqual(packet_hash(context, frames), packet_hash(context, frames, protocol))
            blank = blank_observation(context, protocol)
            self.assertNotIn('view_compliant', json.dumps(blank))
            self.assertNotIn('layout_usable', json.dumps(blank))
            target = root / 'calibration'
            item = prepare_calibration(source, target)['items'][0]
            self.assertNotIn('PRIVATE_JUDGE_EVIDENCE', (target / 'blind/item-001/review.html').read_text())
            self.assertFalse(compare(target)['complete'])
            if protocol == SCOPED_EVIDENCE_PROTOCOL:
                self.assertIn(COUNT_SCOPE_HELP, (target / 'blind/item-001/review.html').read_text())
                self.assertNotEqual(packet_hash(context, frames, EVIDENCE_PROTOCOL), packet_hash(context, frames, protocol))
            value = {'protocol': protocol, 'item': item['id'], 'input_sha256': item['input_sha256'], 'observation': observed}
            self.assertTrue(validate_label(target, item, value)['valid'])
            write_json(target / 'human/item-001.human.json', value)
            self.assertEqual(compare(target)['score_agreement']['Position']['rate'], 1)
            self.assertFalse(compare(target)['release_ready'])
            with self.assertRaises(ValueError):
                validate_label(target, item, {**value, 'protocol': REFERENCE_PROTOCOL})
            if protocol == SCOPED_EVIDENCE_PROTOCOL:
                with self.assertRaises(ValueError):
                    validate_label(target, item, {**value, 'protocol': EVIDENCE_PROTOCOL})

    def test_background_rule_covers_opening_final_and_identity_scope(self):
        original = evidence_system(EVIDENCE_PROTOCOL)
        scoped = evidence_system(SCOPED_EVIDENCE_PROTOCOL)
        self.assertEqual(original, EVIDENCE_SYSTEM)
        self.assertNotIn('COUNTING SCOPE (v5.1)', original)
        self.assertTrue(scoped.startswith(original))
        for rule in ('BOTH opening images and EACH final readout', 'identity-reference selection',
                     'customers at other tables', 'people merely crossing the aisle',
                     'staff working elsewhere', 'Never exclude a same-table extra',
                     'not in the identity list', 'standing participants',
                     'A worker directly serving or interacting with this group counts',
                     'do not borrow a similarly dressed background person',
                     'set count=null', 'do not add fields'):
            self.assertIn(rule, scoped)

    def test_scope_revision_does_not_change_schema_or_score_reducer(self):
        context, observed = fixture()
        # Synthetic observation: the observer excluded unrelated other-table diners.
        observed['opening']['evidence'] += ' Two unrelated other-table diners excluded.'
        for frame in observed['frames']:
            frame['evidence'] += ' One aisle passerby excluded; target table has three people.'
        before = score_evidence_episode(context, observed)
        after = score_evidence_episode(context, observed, protocol=SCOPED_EVIDENCE_PROTOCOL)
        self.assertTrue(after['joint_success'])
        self.assertEqual({**before, 'protocol': SCOPED_EVIDENCE_PROTOCOL}, after)
        self.assertEqual(blank_observation(context, EVIDENCE_PROTOCOL), blank_observation(context, SCOPED_EVIDENCE_PROTOCOL))
        self.assertNotIn('background_count', json.dumps(evidence_schema(context)))

    def test_scope_revision_still_counts_extras_and_retains_opening_guard(self):
        context, observed = fixture()
        observed['frames'][0]['count'] += 1
        observed['frames'][0]['evidence'] = 'Synthetic same-table extra; not unrelated background.'
        score = score_evidence_episode(context, observed, protocol=SCOPED_EVIDENCE_PROTOCOL)
        self.assertTrue(score['valid'])
        self.assertFalse(score['count_correct'])
        observed['opening']['count'] += 1
        score = score_evidence_episode(context, observed, protocol=SCOPED_EVIDENCE_PROTOCOL)
        self.assertIn('opening_count_mismatch', score['target']['issues'])

    def test_scope_revision_cannot_overwrite_v5_artifacts(self):
        from run_evaluation import judge_settings
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for filename in ('score.json', 'judge/reference_observer/request.json'):
                with self.subTest(filename=filename):
                    directory = root / filename.replace('/', '_')
                    write_json(directory / filename, {'protocol': EVIDENCE_PROTOCOL})
                    before = (directory / filename).read_bytes()
                    client = Mock()
                    with self.assertRaisesRegex(ValueError, 'separate output'):
                        evaluate_video(client, directory, judge_settings(DEFAULT_JUDGE, SCOPED_EVIDENCE_PROTOCOL))
                    client.request.assert_not_called()
                    self.assertEqual(before, (directory / filename).read_bytes())

    def test_cli_defaults_to_new_scope_without_paid_action(self):
        import run_evaluation
        class Prepared(Exception):
            pass
        def capture(args):
            self.assertEqual(args.protocol, SCOPED_EVIDENCE_PROTOCOL)
            self.assertEqual(args.phase, 'plan')
            self.assertTrue(str(args.output).endswith('evidence-v5.1'))
            raise Prepared()
        with patch('sys.argv', ['run_evaluation.py']), patch('run_evaluation.load_env_file'), patch(
                'run_evaluation.prepare', side_effect=capture), patch('run_evaluation.VideoClient') as client:
            with self.assertRaises(Prepared):
                run_evaluation.main()
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
