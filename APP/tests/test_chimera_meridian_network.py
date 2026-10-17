"""Chimera's source-backed CL14 import, table decisions, cold reload and replay.

The source fixture reads the authentic P2B progression by its literal path;
runtime mechanics come from the normal native compiler, not replacement data.
"""
import json
import zipfile

import pytest

from combat.ext import beast_aspects as aspects
from combat.fight_setup import SOURCE
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService, TabletopError
from tests.h1_support import ROOT, sheet
from tests.test_hunt25_mantle_setup import send

# Stable runtime-valid actor IDs (portable folders and ButtonStore share these).
OWNER, ALLY, FOE, FOE2 = [f'actor:factory.{value}' for value in ('a1000001', 'a1000002', 'b2000001', 'b2000002')]

FEATURE = aspects.PREFIX + 'chimera_meridian_network'
INITIAL = 'choice:needle.chimera_initial'
TURN = 'choice:needle.beast_aspects'
SWAP = 'choice:needle.chimera_swap'


def fixture(tmp_path, *, manual=True, ask=True, ai_first=False, ordered=False):
    ids = [OWNER, ALLY, FOE, FOE2]
    # The deterministic starting character has already acquired this Scripture.
    # Its earned features come from the real source progression at owning Path
    # CL14, not a manually installed engine row/condition or successful receipt.
    index = json.loads((ROOT / 'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json').read_text())
    subpath = next(row for row in index['entries'] if row['canonical_id'] == aspects.PREFIX.removesuffix('.feature.'))
    assert subpath['owning_path_id'] == 'tianxia.path.body_refining'
    features = [row['canonical_id'] for row in subpath['feature_progression'] if row['granted_at_cl'] <= 14]
    assert FEATURE in features
    docs = [sheet(features if aid == OWNER else [], cl=14, primary='Stamina', name=name)
            for aid, name in zip(ids, ('Chimera', 'Companion', 'Opponent', 'Second Opponent'))]
    for aid, doc in zip(ids, docs):
        doc['identity']['path'] = 'Body Refining'
        if ordered:
            # Source sheet initiative bonuses create the required boundary order;
            # no turn index, result, condition or successful receipt is installed.
            doc['ability_scores_and_statistics']['initiative'] = {'bonus': {FOE: 100, OWNER: 50, FOE2: -50, ALLY: -100}[aid]}
            # AC 0 is the floor of the printed actor model (ActorTemplate armor_class ge=0); it still lets attacks land.
            doc['ability_scores_and_statistics']['armor_class']['base_value'] = 0
            doc['equipment'] = [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou', 'quantity': 1}]}}]
        if aid == OWNER:
            doc['path_and_subpath']['subpath_id'] = 'tianxia.subpath.body.hundred_beast_scripture'
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    if ask:
        from combat.tabletop import ButtonStore
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(
            OWNER.removeprefix('actor:factory.'), {'mode': 'ask'}, {'opportunity_attack'})
    combat.tabletop_maps.save({'display_name': 'Chimera yard', 'width_squares': 12, 'height_squares': 10,
                              'walls': [], 'starts': {'team1': [[3, 6], [3, 7]], 'team2': [[4, 6], [5, 6]]}})
    mid = combat.create_factory_match(
        project_ids=[aid.removeprefix('actor:factory.') for aid in (OWNER, ALLY)], opponent_actor_ids=[FOE, FOE2],
        control_modes={aid: ('MANUAL' if manual else 'LOCAL_AUTO') if aid == OWNER else 'MANUAL' for aid in ids},
        arena_id='battlefield:map.chimera-yard', match_seed='H25-FOCUS-0', maximum_rounds=5,
        display_name='Chimera CL14')['match_id']
    first = combat._load_session(mid).engine.state.current_actor_id
    assert first != OWNER
    if ai_first:
        combat.set_controller_mode(mid, actor_id=first, controller_mode='LOCAL_AUTO')
    return combat, TabletopService(combat, tmp_path), mid


def load(tmp_path, mid):
    return CombatService(ROOT, tmp_path)._load_session(mid)


def answer(prompt, picks):
    return {**prompt['context'], 'selection': 'USE', 'option_ids': picks}


def setup(table, mid, picks=('Ox', 'Turtle', 'Falcon')):
    prompt = send(table, mid)['reaction']
    assert prompt['context']['reaction_source_id'] == INITIAL
    assert send(table, mid, [answer(prompt, list(picks))])['status'] == 'COMMITTED'


def end(table, mid, picks=None):
    state = table.state(mid)
    menu = state['menu']
    answers, prompts = [], []
    for _ in range(8):
        result = table.act(mid, menu['end_turn'], menu['decision_id'], menu['state_version'],
                           state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']; prompts.append(p)
        rid = p['context']['reaction_source_id']
        selected = (picks or {}).get(rid)
        if selected is not None:
            answers.append(answer(p, selected))
        elif p.get('choice', {}).get('allow_decline'):
            answers.append({**p['context'], 'selection': 'DECLINE'})
        else:
            count = p['choice'].get('minimum', 1)
            answers.append(answer(p, [o['id'] for o in p['choice']['options']][:count]))
    raise AssertionError('Unbounded turn choices')


def evidence(combat, mid, a, b, value):
    session = combat._load_session(mid)
    combat.change_relations(mid, change={'kind': 'SCENE_OPPOSITION', 'subject': a, 'other': b,
                                        'opposition': value}, expected_state_version=session.engine.state.state_version)


def strike(combat, table, mid):
    from tests.worker2_support import settle
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if OWNER in c.target_ids
                     and c.kind == 'ACTION' and c.source_definition_id in engine.action_catalog
                     and any(e.get('type') == 'attack' for e in
                             (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('effects', [])))
    settle(table, mid, candidate.candidate_id)


def test_turtle_history_survives_loss_regain_and_completed_attack_is_unchanged(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    assert load(tmp_path, mid).engine.state.current_actor_id == FOE
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    evidence(combat, mid, OWNER, FOE2, 'GENUINE')
    strike(combat, table, mid)
    before = load(tmp_path, mid); owner = before.engine.state.actors[OWNER]
    assert owner.turn_flags['_round_turtle'] == 1
    old_events = [e.model_dump(mode='json') for e in before.engine.events]
    old_rolls = [r.model_dump(mode='json') for r in before.engine.rolls]
    packets = [e for e in before.engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert packets and packets[0].payload['reduced_to'] == max(0, packets[0].payload['rolled_or_pending_damage'] - owner.proficiency_bonus)
    prompts = end(table, mid, {SWAP: ['Turtle>Crane'], TURN: ['Tiger', 'Turtle', 'Falcon']})
    assert {p['context']['reaction_source_id'] for p in prompts} >= {SWAP, TURN}
    after = load(tmp_path, mid)
    assert after.engine.state.round_number == 1 and after.engine.state.current_actor_id == OWNER
    assert set(aspects.active(after.engine, after.engine.state.actors[OWNER])) == {'Tiger', 'Turtle', 'Falcon'}
    assert [e.model_dump(mode='json') for e in after.engine.events[:len(old_events)]] == old_events
    assert [r.model_dump(mode='json') for r in after.engine.rolls[:len(old_rolls)]] == old_rolls
    assert after.engine.state.actors[OWNER].turn_flags['_round_turtle'] == 1
    end(table, mid)
    assert load(tmp_path, mid).engine.state.current_actor_id == FOE2
    strike(combat, table, mid)
    session = load(tmp_path, mid)
    packets = [e for e in session.engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert len(packets) >= 2
    assert packets[-1].payload['reduced_to'] == packets[-1].payload['rolled_or_pending_damage']
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_gaining_unused_turtle_begins_now_and_round_reset_allows_next_use(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid, ('Tiger', 'Ox', 'Falcon'))
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    evidence(combat, mid, OWNER, FOE2, 'GENUINE')
    strike(combat, table, mid)
    before = load(tmp_path, mid)
    assert '_round_turtle' not in before.engine.state.actors[OWNER].turn_flags
    first = next(e.model_dump(mode='json') for e in before.engine.events
                 if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids)
    assert first['payload']['reduced_to'] == first['payload']['rolled_or_pending_damage']
    end(table, mid, {SWAP: ['Tiger>Turtle'], TURN: ['Wolf', 'Ape', 'Turtle']})
    session = load(tmp_path, mid)
    assert set(aspects.active(session.engine, session.engine.state.actors[OWNER])) == {'Wolf', 'Ape', 'Turtle'}
    applied = next(i for i, e in enumerate(session.engine.events)
                   if e.event_type == 'CONDITION_APPLIED' and e.source_definition_id == FEATURE
                   and e.payload.get('condition_id', '').endswith('beast_aspect_turtle'))
    own_start = next(i for i, e in enumerate(session.engine.events)
                     if e.event_type == 'TURN_STARTED' and e.actor_id == OWNER)
    assert applied < own_start  # The hostile-end replacement begins immediately.
    assert next(e.model_dump(mode='json') for e in session.engine.events
                if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids) == first
    end(table, mid)
    strike(combat, table, mid)
    session = load(tmp_path, mid); owner = session.engine.state.actors[OWNER]
    assert owner.turn_flags['_round_turtle'] == 1
    end(table, mid)  # second foe -> ally
    end(table, mid)  # ally -> round two, first foe
    assert load(tmp_path, mid).engine.state.round_number == 2
    strike(combat, table, mid)
    session = load(tmp_path, mid); owner = session.engine.state.actors[OWNER]
    assert owner.turn_flags['_round_turtle'] == 2
    packets = [e.payload for e in session.engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert len(packets) >= 3
    assert packets[-1]['reduced_to'] == max(0, packets[-1]['rolled_or_pending_damage'] - owner.proficiency_bonus)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_exact_printed_source():
    # Clause-level checks: the rule's substance is pinned without freezing every wording edit.
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[FEATURE]
    for clause in ('select three different active Aspects before any creature takes a turn',
                   'Once per round, immediately after a hostile creature ends its turn, replace one active Aspect',
                   'A creature counts as hostile only when it is genuinely opposing you in the current scene; '
                   'staged hostility cannot farm replacement timings.'):
        assert clause in text, clause
    index = json.loads((ROOT / 'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json').read_text())
    subpath = next(row for row in index['entries'] if row['canonical_id'] == aspects.PREFIX.removesuffix('.feature.'))
    feature = next(row for row in subpath['feature_progression'] if row['canonical_id'] == FEATURE)
    assert feature['granted_at_cl'] == 14 and feature['minimum_realm_band'] == 'Core Formation'
    assert subpath['access']['canonical_category'] == 'Restricted Scripture'
    assert subpath['access']['access_source_record_required'] is True


@pytest.mark.parametrize('ask', [False, True])
@pytest.mark.parametrize('ai_first', [False, True])
def test_three_before_any_turn_pending_cold_reload_and_real_effects(tmp_path, ask, ai_first):
    combat, table, mid = fixture(tmp_path, ask=ask, ai_first=ai_first)
    before = load(tmp_path, mid).engine.state.model_dump(mode='json')
    assert all(a['turns_started'] == 0 for a in before['actors'].values())
    assert not aspects.active(combat._load_session(mid).engine, combat._load_session(mid).engine.state.actors[OWNER])
    result = send(table, mid)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['choice']['minimum'] == prompt['choice']['maximum'] == 3
    assert {o['id'] for o in prompt['choice']['options']} == set(aspects.ASPECTS)
    assert 'before any creature' in prompt['moment']
    assert load(tmp_path, mid).engine.state.model_dump(mode='json') == before
    combat = CombatService(ROOT, tmp_path); table = TabletopService(combat, tmp_path)
    assert send(table, mid)['reaction'] == prompt
    assert send(table, mid, [answer(prompt, ['Crane', 'Turtle', 'Ox'])])['status'] == 'COMMITTED'
    session = load(tmp_path, mid); engine = session.engine; actor = engine.state.actors[OWNER]
    assert set(aspects.active(engine, actor)) == {'Crane', 'Turtle', 'Ox'}
    assert aspects.known(engine, actor) == list(aspects.ASPECTS)
    assert engine._effective_speed(actor) == actor.speed_ft + 10
    from combat import ext
    assert sum(ext.run('ac', engine, actor)) == 1
    assert actor.resources == before['actors'][OWNER]['resources']
    assert actor.action_available and actor.bonus_action_available and actor.reaction_available
    events = engine.events
    applied = next(i for i, e in enumerate(events) if e.event_type == 'CONDITION_APPLIED'
                   and e.payload.get('condition_id', '').startswith('condition:typed.state.beast_aspect_'))
    started = next(i for i, e in enumerate(events) if e.event_type == 'TURN_STARTED')
    assert applied < started and not engine.state.setup_tasks
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_automatic_three_before_first_turn(tmp_path):
    combat, table, mid = fixture(tmp_path, manual=False)
    assert send(table, mid)['status'] == 'COMMITTED'
    session = load(tmp_path, mid); engine = session.engine
    assert aspects.active(engine, engine.state.actors[OWNER]) == list(aspects.ASPECTS[:3])
    assert session.verify()['status'] == 'PASS'


@pytest.mark.parametrize('picks', [['Tiger', 'Tiger', 'Ox'], ['Tiger', 'Ox', 'Dragon'], ['Tiger', 'Ox']])
def test_invalid_initial_selection_cannot_start_turn_or_install_states(tmp_path, picks):
    _, table, mid = fixture(tmp_path)
    prompt = send(table, mid)['reaction']
    before = load(tmp_path, mid).engine.state.model_dump(mode='json')
    result = None
    try:
        result = send(table, mid, [answer(prompt, picks)])
    except (ValueError, TabletopError, CombatServiceError):
        pass  # A structured rejection. Any other exception is a crash and fails the test.
    assert result is None or result['status'] != 'COMMITTED', result
    assert load(tmp_path, mid).engine.state.model_dump(mode='json') == before


@pytest.mark.parametrize('opposition', ['ABSENT', 'UNKNOWN', 'STAGED', 'GENUINE'])
def test_hostile_end_swap_requires_scene_evidence_and_is_once_per_round(tmp_path, opposition):
    combat, table, mid = fixture(tmp_path)
    setup(table, mid)
    if opposition != 'ABSENT':
        evidence(combat, mid, OWNER, FOE, opposition)
        evidence(combat, mid, OWNER, FOE2, opposition)
    # End real initiative turns; all own-turn choices retain the requested three.
    seen = []
    for _ in range(4):
        seen += end(table, mid, {TURN: ['Ox', 'Turtle', 'Falcon'], SWAP: ['Falcon>Crane']})
    swaps = [p for p in seen if p['context']['reaction_source_id'] == SWAP]
    assert bool(swaps) == (opposition == 'GENUINE')
    if swaps:
        assert len(swaps) == 1
        options = {o['id'] for o in swaps[0]['choice']['options']}
        assert len(options) == 15 and 'Falcon>Crane' in options
        assert 'Turtle>Turtle' not in options and 'Turtle>Ox' not in options
    session = load(tmp_path, mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_chimera_initial_choice_explains_the_fight_start_choice(tmp_path):
    _, table, mid = fixture(tmp_path)
    prompt = send(table, mid)['reaction']
    assert prompt['context']['reaction_source_id'] == INITIAL
    assert 'before any creature' in prompt['moment']
    assert 'Beast Aspects' in prompt['summary'] and 'Chimera' in prompt['summary']
    assert 'next legal Aspect selection or replacement' in prompt['summary']
    assert prompt['cost'] == 'No action or Stamina cost'
    descriptions = {o['id']: o['description'] for o in prompt['choice']['options']}
    assert 'Proficiency Bonus' in descriptions['Tiger'] and 'No action or Stamina cost' in descriptions['Tiger']


def test_scene_evidence_alone_leaves_legacy_fight_rules_unchanged(tmp_path):
    from combat.relations import ENEMY, enabled, relation
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    assert combat._load_session(mid).engine.state.relations is None
    assert not enabled(combat._load_session(mid).engine)
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    engine = load(tmp_path, mid).engine
    assert engine.state.relations.opposition and not engine.state.relations.teams and not engine.state.relations.actors
    assert not enabled(engine)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert relation(engine, owner, foe) == ENEMY
    # An allegiance row is what switches the relation rules on.
    session = combat._load_session(mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': ALLY,
                                        'relation': 'ALLY'}, expected_state_version=session.engine.state.state_version)
    assert enabled(load(tmp_path, mid).engine)


def test_automatic_later_selections_need_no_player_prompt(tmp_path):
    combat, table, mid = fixture(tmp_path, manual=False, ordered=True)
    assert send(table, mid)['status'] == 'COMMITTED'
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    prompts = end(table, mid)
    assert not prompts
    session = load(tmp_path, mid); owner = session.engine.state.actors[OWNER]
    assert session.engine.state.current_actor_id == OWNER
    assert len(set(aspects.active(session.engine, owner))) == 3
    assert aspects.known(session.engine, owner) == list(aspects.ASPECTS)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('relation', ['ALLY', 'NEUTRAL'])
def test_scene_evidence_does_not_override_current_nonhostile_relation(tmp_path, relation):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    evidence(combat, mid, OWNER, FOE, 'GENUINE')
    session = combat._load_session(mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': FOE,
                                        'relation': relation}, expected_state_version=session.engine.state.state_version)
    prompts = end(table, mid, {TURN: ['Tiger', 'Ox', 'Falcon']})
    assert not any(p['context']['reaction_source_id'] == SWAP for p in prompts)
    session = load(tmp_path, mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_genuine_enemy_on_same_roster_team_still_grants_timing(tmp_path):
    combat, table, mid = fixture(tmp_path, ordered=True)
    setup(table, mid)
    evidence(combat, mid, OWNER, ALLY, 'GENUINE')
    session = combat._load_session(mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': ALLY,
                                        'relation': 'ENEMY'}, expected_state_version=session.engine.state.state_version)
    end(table, mid, {TURN: ['Ox', 'Turtle', 'Falcon']})
    end(table, mid)
    end(table, mid)
    assert load(tmp_path, mid).engine.state.current_actor_id == ALLY
    prompts = end(table, mid, {SWAP: ['Falcon>Serpent']})
    assert len([p for p in prompts if p['context']['reaction_source_id'] == SWAP]) == 1
    session = load(tmp_path, mid)
    assert set(aspects.active(session.engine, session.engine.state.actors[OWNER])) == {'Ox', 'Turtle', 'Serpent'}
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
