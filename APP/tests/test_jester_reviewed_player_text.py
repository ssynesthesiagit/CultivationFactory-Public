"""Keep newly reviewed Jester player text free of implementation terminology.

Compare with the reviewed batch-3 parent, so inherited reminders are not
silently treated as this lane's additions. Only display fields are inspected;
effect identifiers, provenance and other machine data are deliberately excluded.
"""
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = 'bd7aa9834fbe721356fa391efe6e95cf0e12ef68'
SHARDS = ('expiry_fixes.json', 'riders_lane9.json', 'sys_menus-forms.json')
DISPLAY_FIELDS = {'riders', 'name', 'label', 'options', 'description', 'prompt'}
ENGINE_TERMS = re.compile(
    r'\b(?:receipts?|checkpoints?|callbacks?|continuations?|source-owned|'
    r'post-resolution|protected-save|shared next-attack-or-ability-check|'
    r'failed-save end-of-next-turn|ordinary-action target|'
    r'combat/ext|typed_executor|condition:|tianxia\.talent\.)', re.I)


def display_strings(value, display=False):
    if isinstance(value, str):
        if display:
            yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from display_strings(child, display or key in DISPLAY_FIELDS)
    elif isinstance(value, list):
        for child in value:
            yield from display_strings(child, display)


@pytest.mark.parametrize('shard', SHARDS)
def test_new_reviewed_jester_player_text_has_no_engine_terms(shard):
    path = f'APP/authority/typed_mechanics/reviewed_final.d/{shard}'
    baseline = json.loads(subprocess.check_output(
        ['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True))['mechanics']
    current = json.loads((ROOT / path).read_text())['mechanics']
    violations = []
    for row, data in current.items():
        if 'jester' not in row.lower():
            continue
        inherited = set(display_strings(baseline.get(row, {})))
        for text in set(display_strings(data)) - inherited:
            if ENGINE_TERMS.search(text):
                violations.append(f'{row}: {text}')
    assert not violations, '\n'.join(sorted(violations))


@pytest.mark.parametrize('shard', SHARDS)
def test_new_reviewed_jester_reminders_reach_generated_authority(shard):
    path = f'APP/authority/typed_mechanics/reviewed_final.d/{shard}'
    baseline = json.loads(subprocess.check_output(
        ['git', 'show', f'{BASE}:{path}'], cwd=ROOT, text=True))['mechanics']
    current = json.loads((ROOT / path).read_text())['mechanics']
    generated = json.loads((ROOT / 'APP/authority/'
        'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    for row, data in current.items():
        if 'jester' not in row.lower():
            continue
        new_riders = set(data.get('riders', [])) - set(
            baseline.get(row, {}).get('riders', []))
        assert new_riders <= set(generated[row]['riders']), row
