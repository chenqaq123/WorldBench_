import copy
import tempfile
import unittest
from pathlib import Path

from calibrate_reference import prepare, compare, validate_label
from test_reference_evaluation import context_and_observation
from worldline.evaluation import REFERENCE_PROTOCOL
from worldline.video import write_json, file_hash, read_json


def fixture(root):
    context, observation = context_and_observation()
    context.update(opening_request={'content': 'Three people at a table.', 'viewpoint': 'Wide shot.'},
                   final_view='Reverse wide shot of the table.')
    for a in context['identity_references']:
        a.update(descriptor='a man in a colored shirt', anchor_shot=1)
    source = root / 'source'
    directory = source / 'case-a'
    frames = []
    for role in ('opening', 'readout'):
        for i in (1, 2):
            path = directory / (role + str(i) + '.jpg')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'synthetic fixture; no actual image interpretation')
            frames.append({'label': role + '_' + str(i), 'role': role, 'shot': 1 if role == 'opening' else 3,
                           'time': float(i), 'path': str(path), 'sha256': file_hash(path)})
    write_json(source / 'manifest.json', {'judge': {'protocol': REFERENCE_PROTOCOL}, 'cases': [{'id': 'case-a'}]})
    write_json(directory / 'frames.json', frames)
    write_json(directory / 'reference.context.json', context)
    observation['opening']['evidence'] = 'PRIVATE_JUDGE_EVIDENCE'
    write_json(directory / 'observation.json', observation)
    return source, observation


class ReferenceCalibrationTests(unittest.TestCase):
    def test_blind_packet_pending_without_human_labels(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, _ = fixture(root)
            target = root / 'calibration'
            manifest = prepare(source, target)
            page = (target / 'blind/item-001/review.html').read_text()
            self.assertNotIn('PRIVATE_JUDGE_EVIDENCE', page)
            self.assertNotIn('expected_occupants', page)
            self.assertIn('localStorage', page)
            self.assertEqual(len(manifest['items']), 1)
            report = compare(target)
            self.assertFalse(report['complete'])
            self.assertEqual(report['score_agreement']['Valid']['total'], 0)
            self.assertFalse(report['release_ready'])
            with self.assertRaises(FileExistsError):
                prepare(source, target)

    def test_import_contract_and_human_valid_denominator(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, observed = fixture(root)
            target = root / 'calibration'
            item = prepare(source, target)['items'][0]
            value = {'protocol': REFERENCE_PROTOCOL, 'item': item['id'],
                     'input_sha256': item['input_sha256'], 'observation': observed}
            validate_label(target, item, value)
            write_json(target / 'human/item-001.human.json', value)
            report = compare(target)
            self.assertTrue(report['complete'])
            self.assertFalse(report['release_ready'])
            self.assertEqual(report['score_agreement']['Position']['rate'], 1)
            value['observation']['opening']['readable'] = False
            write_json(target / 'human/item-001.human.json', value)
            self.assertEqual(compare(target)['score_agreement']['Count']['total'], 0)
            bad = copy.deepcopy(value)
            bad['input_sha256'] = 'wrong'
            with self.assertRaises(ValueError):
                validate_label(target, item, bad)
            image = next((target / 'blind/item-001/images').glob('*.jpg'))
            image.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                validate_label(target, item, value)

    def test_missing_evidence_remains_in_denominator(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source, _ = fixture(root)
            m = read_json(source / 'manifest.json')
            m['cases'].append({'id': 'case-b'})
            write_json(source / 'manifest.json', m)
            target = root / 'calibration'
            manifest = prepare(source, target)
            self.assertEqual(manifest['planned_items'], 2)
            self.assertEqual(len(manifest['pending_evidence']), 1)
            self.assertFalse(compare(target)['complete'])


if __name__ == '__main__':
    unittest.main()
