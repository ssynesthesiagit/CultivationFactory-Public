"""Focused table presentation and isolated-export regressions for Double Current."""
import hashlib
import json
from itertools import combinations

import pytest

from combat.ext.flowing_river import DOUBLE_CURRENT, DOUBLE_USED, NAMES
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, turn
from tests.h1_support import ROOT
from tests.test_auto2_flowing_river import RESPONSE, FOCUS, reload, settle, decline_steps
from tests.test_double_current_method import CHOICE, acquired


def test_source_bound_runtime_inputs_are_available_to_table_tests():
    """Literal paths retain dynamically loaded owner inputs in isolated exports."""
    rules = json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())
    digest = hashlib.sha256(rules[DOUBLE_CURRENT].encode()).hexdigest()
    reviewed = json.loads((ROOT/'authority/typed_mechanics/reviewed_final.d/double_current_method.json').read_text())
    feature = json.loads((ROOT/'combat/rules/feature_blocks.d/double_current_method.json').read_text())
    assert reviewed['mechanics'][DOUBLE_CURRENT]['text_sha256'] == digest
    assert feature['features'][DOUBLE_CURRENT]['text_sha256'] == digest
    assert feature['features'][DOUBLE_CURRENT]['kind'] == 'double_current_method'


@pytest.mark.parametrize('source,excluded,empty_focus', [
    ('.weapon.bi_shou', {'Return the Grip'}, False),
    ('.unarmed.shove_prone', {'Bend the Blade', 'River Takes the Spear'}, False),
    ('.weapon.bi_shou', {'Return the Grip', 'Bend the Blade'}, True),
])
def test_all_owned_response_pairs_use_real_compiled_trigger_facts(tmp_path, source, excluded, empty_focus):
    c, t, m = fight(tmp_path, [RESPONSE, *NAMES], left_score=50, sheet_edit=acquired,
                       spheres=['tianxia.sphere.flowing_river'],
                       extra_witness=True, prepare_target='SELF',
                       prepare=[{'type': 'spend_resource', 'resource_id': FOCUS, 'flat': 1}])
    if empty_focus:
        settle(lambda a: act(t, m, 'Prepare', a))
    turn(t, m, RIGHT)
    before = reload(c, m)
    def decline(prompt):
        return [] if prompt['context']['reaction_source_id'] == CHOICE else decline_steps(prompt)
    _, prompts = settle(lambda a: act(t, m, source, a, target_id=LEFT), decline)
    offer = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    legal_names = [name for name in NAMES.values() if name not in excluded]
    expected = {f'{first} + {second}' for first, second in combinations(legal_names, 2)}
    assert {o['label'] for o in offer['choice']['options']} == expected
    # Assert the help delivered by the table, including effects and costs.
    rules = json.loads((ROOT/'authority/typed_mechanics/rules_text.json').read_text())
    by_name = {name: talent for talent, name in NAMES.items()}
    for option in offer['choice']['options']:
        description = option['description']
        for name in option['label'].split(' + '):
            body = ' '.join(line.strip() for line in rules[by_name[name]].splitlines()
                            if line.strip() and not line.startswith(('#', 'Prerequisite:')))
            assert body in description, (name, description)
        assert 'No additional Action or Reaction' in description
        assert 'Martial Focus' in description
        assert not any(talent in description for talent in NAMES)
    e = reload(c, m)
    assert not any(v.condition_id == DOUBLE_USED for v in e.state.actors[LEFT].conditions.values())
    assert e.state.actors[LEFT].resources[FOCUS] == before.state.actors[LEFT].resources[FOCUS]
