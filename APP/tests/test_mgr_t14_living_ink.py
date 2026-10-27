"""Living Ink supply through real character compilation and committed tables."""
import hashlib
import json

import pytest

from combat.ext.living_ink import BASE, ORIGINS, SUPPLY
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_r1i_round3 import resolve, reload

CHOICE = "choice:needle.living_ink_origin"
LABEL = "Living Ink: conjure a supply"


def held_supply(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == SUPPLY), None)


def test_source_hash_and_automatic_acquisition():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[BASE]
    assert hashlib.sha256(text.encode()).hexdigest() == '58042e4127f072b339869886c52aba64aa1a5855441b65f93c760a9115d8266f'
    doc = sheet(['tianxia.talent.ink.binding_script'])
    projected = doc['spheres_and_talents']
    assert BASE in projected['automatic_sphere_component_record_ids']
    assert BASE not in projected['learned_talent_record_ids']
    compiled = compile_character(doc, actor_id=OWNER)
    # The portable sheet projects the automatic sphere grant separately from
    # learned talents; no manually injected compiled passive is necessary.
    assert any(a['display_name'] == LABEL for a in compiled['action_catalog'])


@pytest.mark.parametrize('origin', ORIGINS)
def test_free_personal_supply_all_origins_commits_and_cold_replays(tmp_path, origin):
    combat, table, mid, send, commit = fixture(tmp_path, [BASE])
    before, prompts = resolve(combat, mid, send, candidate(table, mid, LABEL), {CHOICE: origin})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    held = held_supply(actor)
    assert held.data['origin'] == origin
    assert held.source_actor_id == OWNER
    assert held.expires_on == f"START_OF_SLOT_AT:{engine.state.round_number + 600}:{engine.state.current_slot_index}"
    assert actor.resources == before['actors'][OWNER]['resources']
    assert actor.action_available == before['actors'][OWNER]['action_available']
    assert actor.bonus_action_available == before['actors'][OWNER]['bonus_action_available']
    assert held_supply(engine.state.actors[FOE]) is None
    assert len([c for c in actor.conditions.values() if c.condition_id == SUPPLY]) == 1
    assert len(prompts) == 1
    assert set(o['id'] for o in prompts[0]['choice']['options']) == set(ORIGINS)
    assert all(s in str(prompts[0]) for s in ('Living Ink', 'Owner', '1 hour', 'No extra action', 'cannot be sold'))
    # Re-conjuring replaces the sufficient personal supply rather than making
    # transferable commodity stacks; the native action remains available.
    resolve(combat, mid, send, candidate(table, mid, LABEL), {CHOICE: 'shadow'})
    assert held_supply(reload(tmp_path, mid).state.actors[OWNER]).data['origin'] == 'shadow'


@pytest.mark.parametrize('prepared', [False, True])
def test_native_ink_technique_provides_and_uses_its_medium(tmp_path, prepared):
    combat, table, mid, send, commit = fixture(tmp_path, ['tianxia.talent.ink.binding_script'])
    if prepared:
        resolve(combat, mid, send, candidate(table, mid, LABEL), {CHOICE: 'brush'})
    _, prompts = resolve(combat, mid, send, candidate(table, mid, 'Binding Script', FOE), {CHOICE: 'fingertips'})
    engine = reload(tmp_path, mid)
    assert held_supply(engine.state.actors[OWNER]) is None
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    assert any(e.event_type == 'CONDITION_APPLIED' and e.actor_id == OWNER
               and e.payload.get('condition_id') == SUPPLY for e in engine.events)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events)


def test_wrong_owner_has_no_supply_or_menu(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [], foe_talents=[BASE])
    assert not any(LABEL in g['label'] for g in table.state(mid)['menu']['actions'])
    engine = reload(tmp_path, mid)
    assert held_supply(engine.state.actors[OWNER]) is None
    assert not any(a.owner_id == OWNER and a.display_name == LABEL for a in engine.action_catalog.values())


def test_ai_chooses_origin_without_player_prompt(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [BASE])
    cid = candidate(table, mid, LABEL)
    force_ai_candidate(combat, mid, OWNER, cid)
    _, prompts = resolve(combat, mid, send, cid, {}, auto=True)
    assert not prompts
    assert held_supply(reload(tmp_path, mid).state.actors[OWNER]).data['origin'] == 'fingertips'
