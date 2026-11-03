"""Selected Sound riders through table commit, fresh replay and turn expiry."""
import copy
import json

import pytest

from combat.typed_executor import bears_mark
from tests.h1_support import ROOT
from tests.hunt36_support import LEFT, RIGHT, fight, turn, send, reload, act
from tests.test_sol117_attack_modifiers import IRON
from tests.test_solfsol117_review import SOUND, choose, hits

THUNDER = 'TAL_SOUND_THUNDER_MERIDIAN_STRIKE'
AUGMENT = 'TEST_SOLFSOL117R2_REACH'


def sound_table(tmp_path, monkeypatch, target_kind, augmented, owned=(SOUND,)):
    from tests import hunt36_support
    original_sheet, original_compile = hunt36_support.sheet, hunt36_support.compile_character
    authority = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    mechanic = copy.deepcopy(authority['mechanics'][SOUND])
    mechanic['name'] = 'Test reach augment'
    mechanic['modifier'] = {'targets': ['Unarmed Strike'], 'scope': 'named', 'when': 'use',
                           'optional': True, 'group': 'augment', 'extra_cp': 1, 'add_range_ft': 5, 'effects': []}
    authority['mechanics'][AUGMENT] = mechanic
    items = {'armor': 'tianxia.mortal.armor.lacquered_lamellar',
             'shield': 'tianxia.mortal.armor.shield', 'weapon': 'tianxia.mortal.weapon.bi_shou'}
    def document(mids, **kwargs):
        doc = original_sheet(mids, **kwargs)
        if IRON in mids:
            if augmented:
                doc['spheres_and_talents']['learned_talent_record_ids'].append(AUGMENT)
        else:
            doc['equipment'] = [{'starting_kit': {'items': [
                {'item_id': items[target_kind], 'quantity': 1}] if target_kind in items else []}}]
            if target_kind == 'construct':
                doc['identity']['creature_type'] = 'Construct'
        return doc
    def compiler(*args, **kwargs):
        return original_compile(*args, typed_authority=authority, **kwargs)
    monkeypatch.setattr(hunt36_support, 'sheet', document)
    monkeypatch.setattr(hunt36_support, 'compile_character', compiler)
    combat, table, mid = fight(tmp_path, [*owned, IRON], primary='Stamina', cl=5, seed='SOLFSOL117R2')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == 'Iron Fist attack')
    return combat, table, mid, parent


@pytest.mark.parametrize('augmented', [False, True])
@pytest.mark.parametrize('target_kind', ['armor', 'shield', 'weapon', 'construct', 'bare'])
def test_selected_body_resonance_mark_commit_reload_expiry(tmp_path, monkeypatch, hits, target_kind, augmented):
    combat, table, mid, parent = sound_table(tmp_path, monkeypatch, target_kind, augmented)
    for field, value in (('on', 'toggle'), ('option', '0'), ('payment', '0')):
        choose(combat, table, mid, parent, SOUND, field, value)
    attack = parent
    if augmented:
        engine = reload(combat, mid)
        # Core unarmed augments are existing attack variants, not free toggles.
        attack = next(a.source_definition_id for a in engine.action_catalog.values()
                      if a.parameters.get('typed', {}).get('variant_of') == parent
                      and a.parameters['typed'].get('modifier', {}).get('id') == AUGMENT)
    engine = reload(combat, mid)
    original_typed = copy.deepcopy(engine.action_catalog[attack].parameters['typed'])
    resources, sequence = dict(engine.state.actors[LEFT].resources), engine.state.event_sequence
    send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                                 if c.source_definition_id == attack and c.target_ids == (RIGHT,)))
    engine = reload(combat, mid)  # helper also verifies recorded events and mechanical replay
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == SOUND]) == 1
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == resources['resource:core.stamina'] - 1 - int(augmented)
    damage = [e for e in events if e.event_type == 'DAMAGE_ROLLED' and e.payload.get('damage_label') == 'Body Resonance Strike']
    assert len(damage) == 1 and damage[0].source_definition_id == attack
    assert engine.action_catalog[attack].parameters['typed'] == original_typed
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Resonance') == (target_kind != 'bare')
    if target_kind != 'bare':
        mark = next(c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id.startswith('condition:typed.mark.'))
        assert mark.source_definition_id == SOUND
        assert mark.expires_on == 'START_OF_MARKER_NEXT_TURN'
    act(combat, table, mid, 'end')
    turn(combat, table, mid, RIGHT)
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Resonance') == (target_kind != 'bare')
    act(combat, table, mid, 'end')
    turn(combat, table, mid, LEFT)
    assert not bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'Resonance')


@pytest.mark.parametrize('modifier', [SOUND, THUNDER])
def test_actual_resonance_toggle_and_ask_me_text(tmp_path, monkeypatch, hits, modifier):
    combat, table, mid, parent = sound_table(tmp_path, monkeypatch, 'construct', False, (SOUND, THUNDER))
    engine = reload(combat, mid)
    toggle = next(a for a in engine.action_catalog.values() if
                  (a.parameters.get('attack_modifier_setting') or {}).get('modifier') == modifier
                  and a.parameters['attack_modifier_setting']['family'] == parent
                  and a.parameters['attack_modifier_setting']['field'] == 'on')
    def explained(text):
        assert 'Resonance: a mark from you on the target.' in text
        assert 'Your Sound talents can gain extra effects' in text and 'Resonant Note can deafen' in text
        assert 'duration' in text
    explained(toggle.parameters['setting_description'])
    row = next(e for e in table.state(mid)['shapes'][LEFT] if e['base'] == parent)
    explained(next(m['description'] for m in row['modifiers'] if m['name'] == ('Body Resonance Strike' if modifier == SOUND else 'Thunder-Meridian Strike')))
    choose(combat, table, mid, parent, modifier, 'on', 'toggle')
    engine = reload(combat, mid)
    prompts = send(combat, table, mid, next(c.candidate_id for c in engine.legal_candidates()
                                          if c.source_definition_id == parent and c.target_ids == (RIGHT,)))
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.attack_modifier')
    explained(prompt['moment'])
