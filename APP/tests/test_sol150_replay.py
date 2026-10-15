"""Opt-in original-lane base/head bytes, with explicit affected fight differences."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

APP = Path(__file__).resolve().parents[1]
BASE = os.environ.get('SOL150_REPLAY_BASE')
pytestmark = pytest.mark.skipif(not BASE, reason='requires explicit retained SOL150 base')
SCENARIOS = ['stock:' + seed for seed in ('LOCK5-A', 'LOCK5-B', 'LOCK5-C', 'GATE4-TEST', 'GATE4-AN-1', 'GATE4-LEE')]


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def differences(before, after, path=''):
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        return [p for key in sorted(before.keys() | after.keys())
                for p in (differences(before[key], after[key], f'{path}/{key}')
                          if key in before and key in after else [f'{path}/{key}'])]
    if isinstance(before, list):
        return ([f'{path}/length'] if len(before) != len(after) else []) + [
            p for i, (left, right) in enumerate(zip(before, after))
            for p in differences(left, right, f'{path}/{i}')]
    return [] if before == after else [path]


@pytest.mark.parametrize('scenario', SCENARIOS + ['fireball', 'meld'])
def test_base_head_ai_bytes(tmp_path, scenario):
    authority = tmp_path / 'base-authority.json'
    authority.write_bytes(subprocess.check_output(['git', 'show', f'{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json'], cwd=APP.parent))
    def run(label):
        args = [sys.executable, '-m', 'tests.sol150_replay_capture', str(tmp_path / label), scenario]
        if label == 'base':
            args += [BASE, str(authority)]
        result = subprocess.run(args, cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                                capture_output=True, text=True, timeout=600)
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        return json.loads(result.stdout.splitlines()[-1])
    before, after = run('base'), run('head')
    evidence = {'scenario': scenario, 'base': BASE, 'fields': {key: {
        'base_sha256': hashlib.sha256(encoded(before[key])).hexdigest(),
        'head_sha256': hashlib.sha256(encoded(after[key])).hexdigest(),
        'identical': encoded(before[key]) == encoded(after[key]),
        'base_count': len(before[key]), 'head_count': len(after[key])} for key in before},
        'base_terminal': before['state'].get('terminal_result') is not None,
        'head_terminal': after['state'].get('terminal_result') is not None,
        'changed_paths': differences(before, after)}
    if os.environ.get('SOL150_REPLAY_EVIDENCE'):
        output = Path(os.environ['SOL150_REPLAY_EVIDENCE'])
        output.mkdir(parents=True, exist_ok=True)
        (output / (scenario.replace(':', '-') + '.json')).write_text(json.dumps(evidence, indent=2) + '\n')
    if scenario.startswith('stock:'):
        assert encoded(before) == encoded(after), evidence
    else:
        assert len(before['choices']) == len(after['choices']) == 12
        checkpoint_before = before['ability_checkpoint']
        checkpoint_after = after['ability_checkpoint']
        assert checkpoint_before['rolls'] == checkpoint_after['rolls']
        assert evidence['changed_paths'], 'affected captures must exercise the intended change'
        # Detailed field-path evidence is retained for review; neither event nor
        # controller records are normalized away before hashing/comparing.
        if scenario == 'fireball':
            for actor_id, actor in checkpoint_before['state']['actors'].items():
                other = checkpoint_after['state']['actors'][actor_id]
                for field in ('current_hp', 'resources', 'position'):
                    assert actor[field] == other[field], (actor_id, field)
            old = [e for e in checkpoint_before['events'] if e['event_type'] == 'GM_RIDER']
            new = [e for e in checkpoint_after['events'] if e['event_type'] == 'GM_RIDER']
            assert len(old) > len(new)
            assert any('Unattended flammable objects ignite' in e['payload'].get('rider', '') for e in new)
        else:
            removed = [e for e in checkpoint_after['events'] if e['event_type'] == 'CONDITION_REMOVED'
                       and e['payload'].get('instance_id', '').startswith('condition-instance:condition:typed.meld_set:')]
            assert removed and any(e['event_type'] == 'CONCENTRATION_ENDED' for e in checkpoint_after['events'])
            from tests.test_sol150_text_sweep import ME
            def markers(point):
                return [c for c in point['state']['actors'][ME]['conditions'].values()
                        if c['condition_id'] == 'condition:typed.meld_set']
            # Ending the current concentration resumes the older held Meld.
            # Only Clearsight ends; Darkvision must remain in both captures.
            assert sorted(c['data']['talent'] for c in markers(checkpoint_before)) == [
                'TAL_DARK_CLEARSIGHT', 'TAL_DARK_DARKVISION']
            assert [c['data']['talent'] for c in markers(checkpoint_after)] == ['TAL_DARK_DARKVISION']
            assert markers(checkpoint_after)[0]['expires_on'] == 'CONCENTRATION_END'
