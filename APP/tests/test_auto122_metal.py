"""AUTO122 — Metal Sphere: White Tiger Glance printed target prerequisite.

The printed Glance targets "one creature you can see that you damaged this turn with a
Metal attack or technique".  This gate makes that prerequisite resolve from committed
Metal damage on the owner's own turn instead of remaining a GM line.

Focused engine checks use synthetic damage receipts to isolate eligibility; a separate
engine check executes a compiled Metal attack to test action-catalog provenance. The
table regressions commit real Metal abilities through TabletopService, reopen the fight
with a fresh CombatService between actions, verify replay, and advance turns.
"""
import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService, _combat_preview
from tests.auto_worker1_support import LEFT, RIGHT, fight
from tests.hunt15_support import act, reload, turn
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTH = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
T = 'TAL_METAL_'
GLANCE = T + 'WHITE_TIGER_GLANCE'
# Any Metal-catalogued damage counts as "a Metal attack or technique".
NEEDLE_FLICK = T + 'NEEDLE_FLICK'


def test_bell_metal_counter_player_note_explains_which_resource_pays():
    """The generated authority's table note explains the printed CP price."""
    mechanic = AUTH[T + 'BELL_METAL_COUNTER']
    note = ' '.join(_combat_preview(mechanic)['gm'])
    assert 'Spend 2 points from the resource pool powering this ability' in note
    assert 'such as Qi or Stamina' in note
    assert '2 CP' not in note
    assert mechanic['cost'][0][0]['resource'] == 'cp'
    assert mechanic['cost'][0][0]['amount'] == 2


@lru_cache(maxsize=None)
def _compiled(key, cl=20, dc=50):
    sphere = AUTH[key]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    sheet = {**SHEET, 'equipment': [],
             'identity': {**SHEET['identity'], 'cultivation_level': cl},
             'ability_scores_and_statistics': {**SHEET['ability_scores_and_statistics'],
                 'technique_save_dc': dc, 'technique_attack_bonus': 40,
                 'primary_resource': {'name': 'Qi', 'maximum': 100}},
             'spheres_and_talents': {'sphere_record_ids': [sphere],
                 'learned_talent_record_ids': list(dict.fromkeys([*bases, key]))}}
    return compile_character(sheet, actor_id=ME)


def _fight(key, cl=20, dc=50):
    bundle = copy.deepcopy(_compiled(key, cl, dc))
    engine = _engine(bundle, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    return bundle, engine, me, foe


def _metal_and_glance_fight(cl=20, dc=50):
    """One owner holding both a real Metal attack and Glance, so the gate reads provenance."""
    sphere = AUTH[GLANCE]['sphere_id']
    bases = [k for k, v in AUTH.items() if v.get('sphere_id') == sphere and v.get('kind') == 'base_ability']
    bundle = compile_character({**SHEET, 'equipment': [],
                                'identity': {**SHEET['identity'], 'cultivation_level': cl},
                                'ability_scores_and_statistics': {
                                    **SHEET['ability_scores_and_statistics'],
                                    'technique_save_dc': dc, 'technique_attack_bonus': 40,
                                    'primary_resource': {'name': 'Qi', 'maximum': 100}},
                                'spheres_and_talents': {
                                    'sphere_record_ids': [sphere],
                                    'learned_talent_record_ids': list(
                                        dict.fromkeys([*bases, NEEDLE_FLICK, GLANCE]))}},
                               actor_id=ME)
    engine = _engine(copy.deepcopy(bundle), foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    return engine, me, foe


def _glance_candidate(engine, target_id):
    return next((c for c in engine.legal_candidates()
                 if 'White Tiger Glance' in c.display_name and target_id in c.target_ids), None)


def _metal_hit_this_turn(engine, me, target, amount=5):
    """Record the same DAMAGE_COMMITTED event the engine emits for a real Metal hit."""
    engine._append_event('DAMAGE_COMMITTED', NEEDLE_FLICK, actor_id=me.entity_id,
                         target_ids=(target.entity_id,),
                         payload={'rolled_or_pending_damage': amount, 'reduced_to': amount,
                                  'temporary_hp_absorbed': 0, 'hp_damage': amount,
                                  'damage_type': 'Piercing', 'remaining_hp': target.current_hp})


def test_glance_is_not_offered_on_a_target_the_owner_has_not_metal_damaged():
    _, engine, me, foe = _fight(GLANCE)
    assert _glance_candidate(engine, foe.entity_id) is None


def test_glance_is_offered_on_a_target_the_owner_metal_damaged_this_turn():
    _, engine, me, foe = _fight(GLANCE)
    _metal_hit_this_turn(engine, me, foe)
    assert _glance_candidate(engine, foe.entity_id) is not None


def test_glance_still_refuses_a_sibling_the_owner_did_not_metal_damage():
    _, engine, me, foe = _fight(GLANCE)
    _metal_hit_this_turn(engine, me, foe)
    sibling = me.model_copy(deep=True)
    sibling.entity_id = 'actor:auto122.other'
    sibling.position = foe.position.model_copy(update={'x': foe.position.x + 1})
    engine.state.actors[sibling.entity_id] = sibling
    assert _glance_candidate(engine, foe.entity_id) is not None
    assert _glance_candidate(engine, sibling.entity_id) is None


def test_glance_refuses_another_owners_damage_in_the_current_turn_window():
    _, engine, me, foe = _fight(GLANCE)
    # Deliberately inside the current turn window, isolating actor provenance
    # from the independent rollover rejection covered by the persisted table.
    engine._append_event('DAMAGE_COMMITTED', NEEDLE_FLICK, actor_id='actor:other-owner',
                         target_ids=(foe.entity_id,), payload={'reduced_to': 5})
    assert _glance_candidate(engine, foe.entity_id) is None
    _metal_hit_this_turn(engine, me, foe)
    assert _glance_candidate(engine, foe.entity_id) is not None


def test_glance_resolves_metal_provenance_through_the_compiled_action_catalog():
    engine, me, foe = _metal_and_glance_fight()
    assert _glance_candidate(engine, foe.entity_id) is None
    needle = next(c for c in engine.legal_candidates() if c.display_name == 'Needle Flick')
    # The compiled row id is action:typed.<hash>.<mechanic id>, so only a catalog lookup
    # can resolve it to Metal; the id-prefix shortcut must not be the thing that passes.
    assert not needle.source_definition_id.startswith(
        ('METAL_BASE_', 'TAL_METAL_', 'tianxia.talent.metal.')), needle.source_definition_id
    engine.execute_intent(ActionIntent(intent_id='auto122.needle', decision_id=needle.decision_id,
                                       candidate_id=needle.candidate_id, state_version=needle.state_version,
                                       actor_id=ME, target_ids=needle.target_ids, destination=needle.destination))
    committed = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']
    assert committed and {e.source_definition_id for e in committed} == {needle.source_definition_id}
    assert max(int(e.payload['reduced_to'] or 0) for e in committed) > 0
    assert _glance_candidate(engine, foe.entity_id) is not None


def test_glance_casts_on_a_metal_damaged_target_and_applies_the_printed_penalty():
    _, engine, me, foe = _fight(GLANCE, dc=50)
    _metal_hit_this_turn(engine, me, foe)
    candidate = _glance_candidate(engine, foe.entity_id)
    assert candidate is not None
    engine.execute_intent(ActionIntent(intent_id='auto122', decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    # A failed WIS save denies the target's Reactions until the start of its next turn.
    denied = [c for c in foe.conditions.values() if c.condition_id == 'condition:typed.reaction_denied']
    assert denied, 'White Tiger Glance should deny Reactions on a failed Wisdom save'
    assert denied[0].data['origin_save']['ability'] == 'WIS'


# --- Table level: real abilities, real commits, real reloads, real turn rollover. ---

def _reload_table(combat, mid):
    engine = reload(combat, mid)
    fresh = CombatService(ROOT, combat.userdata_root)
    return fresh, TabletopService(fresh, combat.userdata_root), engine

def _settle(send, answers=()):
    """Drive a table action to a commit, answering any Needle choice it raises."""
    sent = list(answers)
    for _ in range(20):
        result = send(sent)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return result
        prompt = result['reaction']
        choice = prompt.get('choice') or {}
        picked = [o['id'] for o in choice.get('options', [])][:max(1, choice.get('minimum', 1))]
        sent = sent + [{**prompt['context'], 'selection': 'USE' if picked else 'DECLINE',
                        'option_ids': picked}]
    raise AssertionError('too many choices')


def _glance_offered(table, mid, target_id):
    """Whether the persisted table currently offers Glance against ``target_id``."""
    return any(target_id in o.get('target_ids', [])
               for group in table.state(mid)['menu']['actions']
               if group['label'] == 'White Tiger Glance' for o in group['options'])


def _use(table, mid, label, target_id=None):
    return _settle(lambda answers: act(table, mid, label, answers, target_id=target_id))


def _damaging_sources(engine, actor_id, target_id):
    return [e for e in engine.events
            if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == actor_id
            and target_id in (e.target_ids or ())
            and int((e.payload or {}).get('reduced_to') or 0) > 0]


def _reaction_denied(engine, actor_id):
    return [c for c in engine.state.actors[actor_id].conditions.values()
            if c.condition_id == 'condition:typed.reaction_denied']


def _certain_hits(bundle):
    """Make every compiled Needle Flick land, on whichever fighter owns it."""
    for row in bundle['action_catalog']:
        if row['display_name'] == 'Needle Flick':
            row['parameters']['typed']['numbers']['attack_bonus'] = 100


def test_glance_through_the_table_after_a_real_metal_hit_survives_commit_and_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [GLANCE, NEEDLE_FLICK], left_attack_bonus=100)
    _use(table, mid, 'Needle Flick', RIGHT)
    combat, table, engine = _reload_table(combat, mid)
    hits = _damaging_sources(engine, LEFT, RIGHT)
    assert hits, 'the printed Metal attack should have committed real damage'
    assert hits[-1].source_definition_id.endswith(NEEDLE_FLICK), \
        'the damage must come from the compiled catalogued Metal ability, not a test stand-in'
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert _glance_offered(table, mid, RIGHT), 'a committed Metal hit should qualify the target'
    _use(table, mid, 'White Tiger Glance', RIGHT)
    combat, table, engine = _reload_table(combat, mid)
    denied = _reaction_denied(engine, RIGHT)
    assert denied, 'a failed Wisdom save should deny the target Reactions'
    assert denied[0].data['origin_save']['ability'] == 'WIS'
    assert not _glance_offered(table, mid, RIGHT), 'Glance has spent the Bonus Action'


def test_glance_is_refused_after_the_owners_turn_has_rolled_over(tmp_path):
    combat, table, mid = fight(tmp_path, [GLANCE, NEEDLE_FLICK], left_attack_bonus=100)
    _use(table, mid, 'Needle Flick', RIGHT)
    assert _glance_offered(table, mid, RIGHT)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert table.state(mid)['menu']['actor_id'] == LEFT
    combat, table, _ = _reload_table(combat, mid)
    assert not _glance_offered(table, mid, RIGHT), \
        "the printed prerequisite is 'this turn', so it lapses once the owner's turn ends"


def test_glance_refuses_non_metal_damage_and_another_owners_metal_damage(tmp_path):
    combat, table, mid = fight(tmp_path, [GLANCE, NEEDLE_FLICK], right_talents=[NEEDLE_FLICK],
                               left_attack_bonus=100, bundle_edit=_certain_hits,
                               prepare=[{'type': 'damage', 'flat': 2, 'damage_types': ['fire'],
                                         'applies_to': 'target'}])
    _use(table, mid, 'Prepare', RIGHT)
    combat, table, engine = _reload_table(combat, mid)
    plain = _damaging_sources(engine, LEFT, RIGHT)
    assert plain and plain[-1].source_definition_id.startswith('action:test.')
    assert not _glance_offered(table, mid, RIGHT), 'a non-Metal source is not "a Metal attack or technique"'
    _use(table, mid, 'Needle Flick', RIGHT)
    assert _glance_offered(table, mid, RIGHT), 'the Metal hit on the same turn qualifies the target'
    turn(table, mid, RIGHT)
    _use(table, mid, 'Needle Flick', LEFT)
    combat, table, engine = _reload_table(combat, mid)
    other = _damaging_sources(engine, RIGHT, LEFT)
    assert other and other[-1].source_definition_id.endswith(NEEDLE_FLICK)
    turn(table, mid, LEFT)
    assert not _glance_offered(table, mid, LEFT), \
        "Metal damage from someone else is not damage 'you' dealt"


def test_glance_still_needs_sight_after_a_qualifying_metal_hit(tmp_path):
    combat, table, mid = fight(tmp_path, [GLANCE, NEEDLE_FLICK], left_attack_bonus=100,
                               positions={LEFT: {'x': 8, 'y': 5}, RIGHT: {'x': 11, 'y': 5}})
    _use(table, mid, 'Needle Flick', RIGHT)
    combat, table, engine = _reload_table(combat, mid)
    assert engine._line_of_sight_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[RIGHT])
    assert _glance_offered(table, mid, RIGHT)
    state = table.state(mid)
    step = next(m for m in state['menu']['moves'] if m['destination'] == {'x': 8, 'y': 6})
    assert table.act(mid, step['candidate_id'], state['menu']['decision_id'],
                     state['menu']['state_version'], state['last_sequence'], [])['status'] == 'COMMITTED'
    combat, table, engine = _reload_table(combat, mid)
    observer, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert observer.position.model_dump(mode='json') == {'x': 8, 'y': 6}
    assert not engine._line_of_sight_actor_to_actor(observer, target)
    assert engine._distance_actor_to_actor(observer, target) <= 30, 'the stone pillar, not range, must block'
    assert _damaging_sources(engine, LEFT, RIGHT), 'the Metal prerequisite still holds'
    assert not _glance_offered(table, mid, RIGHT), \
        "the printed target is 'one creature you can see', so a blocked sight ends eligibility"
