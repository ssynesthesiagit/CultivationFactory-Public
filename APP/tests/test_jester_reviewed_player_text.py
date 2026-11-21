"""Keep newly reviewed Jester player text free of implementation terminology.

Compare with the reviewed batch-3 parent, so inherited reminders are not
silently treated as this lane's additions. Only display fields are inspected;
effect identifiers, provenance and other machine data are deliberately excluded.
"""
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / 'fixtures/typed_jester_reviewed_baseline.json'
GENERATED = ROOT / 'APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json'
SHARDS = ('expiry_fixes.json', 'riders_lane9.json', 'sys_menus-forms.json')
DISPLAY_FIELDS = {'riders', 'name', 'label', 'options', 'description', 'prompt'}
ENGINE_TERMS = re.compile(
    r'\b(?:receipts?|checkpoints?|callbacks?|continuations?|source-owned|'
    r'post-resolution|protected-save|shared next-attack-or-ability-check|'
    r'failed-save end-of-next-turn|ordinary-action target|'
    r'combat/ext|typed_executor|condition:|tianxia\.talent\.)', re.I)


def reviewed_shard(shard):
    return json.loads((ROOT / 'APP/authority/typed_mechanics/reviewed_final.d' / shard).read_text())['mechanics']


def jester_rows(current):
    return [
        row for row in current
        if row.startswith(('JESTER_BASE_', 'tianxia.talent.jester.'))
    ]


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
    fixture = json.loads(FIXTURE.read_text())
    baseline = fixture['shards'][shard]
    current = reviewed_shard(shard)
    violations = []
    for row in jester_rows(current):
        data = current[row]
        inherited = set(display_strings(baseline.get(row, {})))
        for text in set(display_strings(data)) - inherited:
            if ENGINE_TERMS.search(text):
                violations.append(f'{row}: {text}')
    assert not violations, '\n'.join(sorted(violations))


@pytest.mark.parametrize('shard', SHARDS)
def test_new_reviewed_jester_reminders_reach_generated_authority(shard):
    fixture = json.loads(FIXTURE.read_text())
    reviewed = reviewed_shard(shard)
    generated = json.loads(GENERATED.read_text())['mechanics']
    for row in jester_rows(reviewed):
        source_riders = reviewed[row]['riders']
        assert set(source_riders) <= set(generated[row]['riders']), row
