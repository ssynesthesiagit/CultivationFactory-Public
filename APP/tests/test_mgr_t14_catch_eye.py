"""Whole Catch the Eye row through compiled ownership and native table commits."""
import hashlib
import json

import pytest

from combat import table_advance
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.typed_executor import bears_mark
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

EYE = 'BEAUTY_BASE_CATCH_THE_EYE'
NAME = 'Catch the Eye'
CHOICE = 'choice:needle.effect_choices'


def cast(combat, table, mid, target=FOE, pick='Place Beauty Mark', automatic=False):
    c = candidate(combat, mid, NAME, target=target)
    if automatic:
        session = combat._load_session(mid)
        session.submit_intent(ActionIntent(intent_id='eye-auto-' + str(c.state_version),
            actor_id=c.actor_id, decision_id=c.decision_id, candidate_id=c.candidate_id,
            state_version=c.state_version, target_ids=c.target_ids), primary_decision_record=None,
            reaction_provider=session.engine._gate4_reaction_provider)
        return []
    return settle(table, mid, c.candidate_id, {CHOICE: pick})


def held(engine, who, suffix):
    return [c for c in engine.state.actors[who].conditions.values() if c.condition_id.endswith(suffix)]


def end(table, mid):
    settle(table, mid, table.state(mid)['menu']['end_turn'])


def test_source_hash_and_automatic_learning_grant_reaches_native_action(tmp_path):
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[EYE]
    assert hashlib.sha256(text.encode()).hexdigest() == '0174d5ac1fac782b9f2734ab884663bf071939446785a06f7174c9b46c3c159b'
    # The production table-advancement producer, without a learned base talent.
    doc = table_advance.apply(sheet([], dc=50), {'spheres': [{'id': 'tianxia.sphere.beauty'}]})
    assert EYE in doc['spheres_and_talents']['automatic_sphere_component_record_ids']
    assert EYE not in doc['spheres_and_talents']['learned_talent_record_ids']
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle, named=True)
    cast(combat, table, mid)
    e = reload(tmp_path, mid)
    assert held(e, FOE, '.captivated')
    assert bears_mark(e.state.actors[FOE], OWNER, 'Beauty Mark')
    assert not any(a.owner_id in (ALLY, FOE) and a.display_name == NAME for a in e.action_catalog.values())


@pytest.mark.parametrize('target', [ALLY, FOE])
def test_failed_save_action_cost_source_and_separate_lifetimes(tmp_path, target):
    combat, table, mid = fixture(tmp_path, [EYE], owner_dc=50, named=True)
    before = reload(tmp_path, mid).state.actors[OWNER].resources.copy()
    assert not cast(combat, table, mid, target)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources == before
    assert not e.state.actors[OWNER].action_available
    assert e.state.actors[OWNER].bonus_action_available
    assert held(e, target, '.captivated')[0].source_actor_id == OWNER
    assert bears_mark(e.state.actors[target], OWNER, 'Beauty Mark')
    assert not bears_mark(e.state.actors[target], ALLY, 'Beauty Mark')
    assert not held(e, target, '.resist_ability')
    end(table, mid)
    assert held(reload(tmp_path, mid), target, '.captivated')
    turn(table, mid, OWNER)
    assert held(reload(tmp_path, mid), target, '.captivated')
    end(table, mid)
    e = reload(tmp_path, mid)
    assert not held(e, target, '.captivated')
    assert bears_mark(e.state.actors[target], OWNER, 'Beauty Mark')
    # Native round/slot expiry really removes the minute mark after ten rounds.
    for _ in range(34):
        if not bears_mark(combat._load_session(mid).engine.state.actors[target], OWNER, 'Beauty Mark'):
            break
        end(table, mid)
    assert not bears_mark(reload(tmp_path, mid).state.actors[target], OWNER, 'Beauty Mark')


@pytest.mark.parametrize('automatic,pick', [(False, 'Place Beauty Mark'), (False, 'No Beauty Mark'),
                                          (True, 'Place Beauty Mark')])
def test_success_optional_mark_and_unconditional_resistance(tmp_path, pick, automatic):
    modes = {OWNER: 'LOCAL_AUTO' if automatic else 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'}
    combat, table, mid = fixture(tmp_path, [EYE], owner_dc=-40, modes=modes, named=True)
    prompts = cast(combat, table, mid, pick=pick, automatic=automatic)
    if not automatic:
        p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
        assert NAME in str(p) and 'Mara' in str(p)
        assert 'Wisdom' in str(p)
    e = reload(tmp_path, mid)
    assert not held(e, FOE, '.captivated')
    assert bears_mark(e.state.actors[FOE], OWNER, 'Beauty Mark') is (pick == 'Place Beauty Mark')
    protection = held(e, FOE, '.resist_ability')[0]
    assert protection.source_actor_id == OWNER
    assert protection.data['ability'] == EYE
    assert protection.data['mode'] == 'advantage'
    assert protection.expires_on.startswith('START_OF_SLOT_AT:')
    deadline = int(protection.expires_on.split(':')[1])
    assert deadline == e.state.round_number + 100
    if not automatic:
        end(table, mid); turn(table, mid, OWNER)
        assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Beauty Mark') is (pick == 'Place Beauty Mark')
        end(table, mid)
        assert not bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, 'Beauty Mark')


def test_resistance_only_to_original_caster_after_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [EYE], ally_talents=[EYE], owner_dc=-40, named=True)
    cast(combat, table, mid, pick='No Beauty Mark')
    reload(tmp_path, mid)
    end(table, mid); turn(table, mid, ALLY)
    cast(combat, table, mid, pick='No Beauty Mark')
    e = reload(tmp_path, mid)
    assert [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED'][-1].payload['mode'] == 'NORMAL'
    end(table, mid); turn(table, mid, OWNER)
    cast(combat, table, mid, pick='No Beauty Mark')
    e = reload(tmp_path, mid)
    rolls = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED' and ev.source_definition_id.endswith(EYE)]
    assert rolls[-1].payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('feet,lane,allowed', [(60, 5, True), (65, 5, False), (60, 6, False)])
def test_range_and_nonowners_have_no_action(tmp_path, feet, lane, allowed):
    combat, table, mid = fixture(tmp_path, [EYE], owner_dc=50,
        positions={OWNER: {'x': 3, 'y': lane}, ALLY: {'x': 4, 'y': lane},
                   FOE: {'x': 3 + feet // 5, 'y': lane}}, cl=1)
    e = reload(tmp_path, mid)
    offered = [c for c in e.legal_candidates() if c.display_name == NAME and c.target_ids == (FOE,)]
    assert bool(offered) is allowed
    if offered:
        cast(combat, table, mid)
        assert held(reload(tmp_path, mid), FOE, '.captivated')
    else:
        end(table, mid)
        assert not held(reload(tmp_path, mid), FOE, '.captivated')


def test_native_blindfold_hearing_and_true_silence_boundaries_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [EYE, 'TAL_DARK_BLINDFOLD'], owner_dc=50, cl=5,
        ally_talents=['TAL_SOUND_DAMPEN_SOUND', 'TAL_SOUND_TRUE_SILENCE'],
        foe_position={'x': 3, 'y': 5})
    settle(table, mid, candidate(combat, mid, 'Meld: Blindfold', target=FOE).candidate_id)
    assert held(reload(tmp_path, mid), FOE, '.blinded')
    end(table, mid); turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    from combat.senses import perceives
    assert not perceives(e, e.state.actors[FOE], e.state.actors[OWNER])
    # Voice is a printed delivery: Blindfold alone must not remove a legal option.
    cast(combat, table, mid)
    assert held(reload(tmp_path, mid), FOE, '.captivated')
    end(table, mid); turn(table, mid, ALLY)
    assert held(reload(tmp_path, mid), FOE, '.captivated')
    settle(table, mid, candidate(combat, mid, 'True Silence', at=(3, 6)).candidate_id)
    end(table, mid); turn(table, mid, OWNER)
    e = reload(tmp_path, mid)
    from combat.speech import can_hear_from
    assert not can_hear_from(e, e.state.actors[OWNER], e.state.actors[FOE])
    assert not held(e, FOE, '.captivated')
    assert not [c for c in e.legal_candidates() if c.display_name == NAME and c.target_ids == (FOE,)]
    assert [c for c in e.legal_candidates() if c.display_name == NAME and c.target_ids == (ALLY,)]
