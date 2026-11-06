import pytest
from combat.ext import fate_riders as F
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r9i_choices import action, finish_turn, resolve
from tests.test_r9i_fate_persistence import ALLY, FOE, PLAYER, fixture
from tests.test_r9i_karma_persistence import act


def turn(table, mid, aid):
    for _ in range(40):
        if table.state(mid)['menu']['actor_id'] == aid:
            return
        finish_turn(table, mid)
    raise AssertionError('No turn')


def cold(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded


def grant(table, mid, name):
    turn(table, mid, PLAYER)
    resolve(lambda answers: act(table, mid, action(table, mid, name, ALLY), answers), {})
    finish_turn(table, mid)
    turn(table, mid, ALLY)


@pytest.mark.parametrize('release', [False, True])
def test_wheel_release_before_native_attack_no_die_revealed_and_no_double_bonus(tmp_path, release):
    combat, table, mid = fixture(tmp_path, F.WHEEL_ID, ally_ask=True)
    grant(table, mid, 'Turning Wheel Auspice')
    loaded = cold(tmp_path, mid)
    held = F._held(loaded.engine.state.actors[ALLY], F.WHEEL)[0]
    amount = held.data['bonus']
    cid = action(table, mid, 'Bi Shou (Dagger) attack', FOE)
    prompts = []
    def send(answers):
        result = act(table, mid, cid, answers)
        if result['status'] == 'REACTION_REQUIRED' and result['reaction']['context']['reaction_source_id'] == 'choice:needle.wheel_release':
            prompts.append(result['reaction']['moment'])
        return result
    resolve(send, {'choice:needle.wheel_release': ['release'] if release else None})
    loaded = cold(tmp_path, mid)
    assert prompts and all('before' in p and 'Reaction' in p and 'd20 ' not in p for p in prompts)
    roll = next(r for r in reversed(loaded.engine.rolls) if r.actor_id == ALLY and r.reason.startswith('ATTACK:'))
    spec = next(a for a in loaded.engine.action_catalog.values() if a.display_name == 'Bi Shou (Dagger) attack' and a.owner_id == ALLY)
    base = spec.parameters["typed"]["numbers"]["attack_bonus"]
    assert roll.modifier == base + (2 * amount if release else amount if held.data['kind'] == 'attack' else 0)
    assert bool(F._held(loaded.engine.state.actors[ALLY], F.WHEEL)) == (not release)
    assert loaded.engine.state.actors[ALLY].reaction_available == (not release)


@pytest.mark.parametrize('release', [False, True])
def test_lantern_release_requires_reaction_and_nearby_allies_prevent_advantage(tmp_path, release):
    combat, table, mid = fixture(tmp_path, F.LANTERN_ID, ally_ask=True)
    grant(table, mid, 'Lone Lantern Auspice')
    cold(tmp_path, mid)
    cid = action(table, mid, 'Bi Shou (Dagger) attack', FOE)
    seen = resolve(lambda answers: act(table, mid, cid, answers), {'choice:needle.lantern_release': ['release'] if release else None})
    assert 'choice:needle.lantern_release' in seen
    loaded = cold(tmp_path, mid)
    bearer = loaded.engine.state.actors[ALLY]
    assert bool(F._held(bearer, F.LANTERN)) == (not release)
    assert bool(F._held(bearer, F.LANTERN_RELEASED)) == release
    assert bearer.reaction_available == (not release)
    roll = next(r for r in reversed(loaded.engine.rolls) if r.actor_id == ALLY and r.reason.startswith('ATTACK:'))
    # The ally is adjacent to the foe, but the caster is 10ft from it; the
    # bearer itself is not its own ally for this printed proximity restriction.
    assert roll.mode == ('ADVANTAGE' if release else 'NORMAL')


def test_lantern_self_help_is_withheld_when_any_creature_is_near(tmp_path):
    combat, table, mid = fixture(tmp_path, F.LANTERN_ID,
        ally_skills=[{'skill': 'Sleight of Hand', 'bonus': 10, 'proficiency_multiplier': 1}])
    grant(table, mid, 'Lone Lantern Auspice')
    loaded = cold(tmp_path, mid)
    assert F._held(loaded.engine.state.actors[ALLY], F.LANTERN)
    assert not any('Help yourself' in g['label'] for g in table.state(mid)['menu']['actions'])


def test_lantern_self_help_real_move_check_and_single_use_survive_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, F.LANTERN_ID, ally_talents=['TAL_SCOUNDREL_DIRTY_TRICK'],
        ally_skills=[{'skill': 'Sleight of Hand', 'bonus': 10, 'proficiency_multiplier': 1}], ally_ask=True)
    grant(table, mid, 'Lone Lantern Auspice')
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 8})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    cold(tmp_path, mid)
    cid = action(table, mid, 'Help yourself')
    resolve(lambda answers: act(table, mid, cid, answers), {'choice:needle.lantern_help': ['Sleight of Hand']})
    loaded = cold(tmp_path, mid)
    assert not loaded.engine.state.actors[ALLY].bonus_action_available
    assert F._held(loaded.engine.state.actors[ALLY], F.LANTERN_HELP)[0].data['used'] is False
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 6})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    cid = action(table, mid, 'DIRTY TRICK', FOE)
    resolve(lambda answers: act(table, mid, cid, answers), {})
    loaded = cold(tmp_path, mid)
    roll = next(r for r in reversed(loaded.engine.rolls) if r.actor_id == ALLY and 'SLEIGHT_OF_HAND' in r.reason)
    assert roll.mode == 'ADVANTAGE'
    held = F._held(loaded.engine.state.actors[ALLY], F.LANTERN_HELP)[0]
    assert held.data['used'] is True and held.data['rule'] == {}
    finish_turn(table, mid)
    turn(table, mid, ALLY)
    loaded = cold(tmp_path, mid)
    assert not F._held(loaded.engine.state.actors[ALLY], F.LANTERN_HELP)


def test_consequence_ai_exempts_only_own_side_with_mixed_creatures_in_range(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fixture(tmp_path, F.CONSEQUENCE, caster_pb=4)
    turn(table, mid, PLAYER)
    cid = action(table, mid, 'Consequence Edict')
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode='LOCAL_AUTO')
    resolve(lambda answers: table.auto_step(mid, 0, answers), {})
    loaded = cold(tmp_path, mid)
    zone = F._zones(loaded.engine, F.CONSEQUENCE)[0]
    assert set(zone.trigger_profile['fate_designated']) == {PLAYER, ALLY}
    assert FOE not in zone.trigger_profile['fate_designated']
    for aid in (PLAYER, ALLY, FOE):
        assert F._inside(loaded.engine, loaded.engine.state.actors[aid], zone)


def test_lantern_self_help_blocks_later_feint_assistance_until_next_turn(tmp_path):
    combat, table, mid = fixture(tmp_path, F.LANTERN_ID, caster_talents=['TAL_FENCING_FEINT'],
        ally_skills=[{'skill': 'Sleight of Hand', 'bonus': 10, 'proficiency_multiplier': 1}], ally_ask=True)
    grant(table, mid, 'Lone Lantern Auspice')
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 8})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    resolve(lambda answers: act(table, mid, action(table, mid, 'Help yourself'), answers),
            {'choice:needle.lantern_help': ['Sleight of Hand']})
    cold(tmp_path, mid)
    finish_turn(table, mid)
    turn(table, mid, PLAYER)
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 6})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    cid = action(table, mid, 'Feint', FOE)
    recipients = []
    def send(answers):
        result = act(table, mid, cid, answers)
        if result['status'] == 'REACTION_REQUIRED' and result['reaction']['context']['reaction_source_id'] == 'choice:needle.feint_aid':
            recipients.append([o['id'] for o in result['reaction']['choice']['options']])
        return result
    resolve(send, {'choice:needle.feint_aid': [PLAYER]})
    assert recipients and all(ALLY not in choices for choices in recipients)
    loaded = cold(tmp_path, mid)
    assert not any(m.source_definition_id.startswith('needle:feint:') for m in loaded.engine.state.actors[ALLY].modifiers.values())


@pytest.mark.parametrize('release', [False, True])
def test_wheel_release_on_native_hazard_save(tmp_path, monkeypatch, release):
    from combat.tabletop import TabletopMapStore
    from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY as A
    original_save = TabletopMapStore.save
    def save_map(store, document):
        return original_save(store, {**document, 'starts': {'team1': [[3, 4], [3, 5]], 'team2': [[9, 4]]},
                                      'terrain': [{'type': 'QI_HAZARD', 'cells': [[3, 6]]}]})
    monkeypatch.setattr(TabletopMapStore, 'save', save_map)
    combat, table, mid = table_fight(tmp_path, [F.WHEEL_ID], ally_talents=[], ask=True)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Turning Wheel Auspice', A), answers), {})
    finish_turn(table, mid)
    turn(table, mid, A)
    loaded = cold(tmp_path, mid)
    held = F._held(loaded.engine.state.actors[A], F.WHEEL)[0]
    base = loaded.engine.state.actors[A].saving_throws['DEX']
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 3, 'y': 6})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers),
            {'choice:needle.wheel_release': ['release'] if release else None})
    loaded = cold(tmp_path, mid)
    roll = next(r for r in reversed(loaded.engine.rolls) if r.actor_id == A and r.reason == 'QI_HAZARD_DEX_SAVE')
    amount = held.data['bonus']
    assert roll.modifier == base + (amount * 2 if release else amount if held.data['kind'] == 'save' else 0)
    assert bool(F._held(loaded.engine.state.actors[A], F.WHEEL)) == (not release)


def test_lantern_release_does_not_grant_advantage_with_an_ally_beside_target(tmp_path):
    combat, table, mid = fixture(tmp_path, F.LANTERN_ID, ally_ask=True)
    turn(table, mid, PLAYER)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Lone Lantern Auspice', ALLY), answers), {})
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 5})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    finish_turn(table, mid)
    turn(table, mid, ALLY)
    cid = action(table, mid, 'Bi Shou (Dagger) attack', FOE)
    resolve(lambda answers: act(table, mid, cid, answers), {'choice:needle.lantern_release': ['release']})
    loaded = cold(tmp_path, mid)
    assert F._held(loaded.engine.state.actors[ALLY], F.LANTERN_RELEASED)
    assert loaded.engine._distance_actor_to_actor(loaded.engine.state.actors[PLAYER], loaded.engine.state.actors[FOE]) <= 5
    roll = next(r for r in reversed(loaded.engine.rolls) if r.actor_id == ALLY and r.reason.startswith('ATTACK:'))
    assert roll.mode == 'NORMAL'


@pytest.mark.parametrize('unperceived', [False, True])
def test_lantern_ai_release_uses_perceived_allies_not_hidden_positions(tmp_path, monkeypatch, unperceived):
    from combat import stealth
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fixture(tmp_path, F.LANTERN_ID)
    turn(table, mid, PLAYER)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Lone Lantern Auspice', ALLY), answers), {})
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 5})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    finish_turn(table, mid)
    turn(table, mid, ALLY)
    # Perception fixture only: the nearby caster is either perceived or
    # unperceived. The real AI choice, Reaction, geometry and roll still run.
    original = stealth.sees
    def sees(engine, viewer, target):
        if unperceived and viewer.entity_id == ALLY and target.entity_id == PLAYER:
            return False
        return original(engine, viewer, target)
    monkeypatch.setattr(stealth, 'sees', sees)
    cid = action(table, mid, 'Bi Shou (Dagger) attack', FOE)
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    resolve(lambda answers: table.auto_step(mid, 0, answers), {})
    loaded = cold(tmp_path, mid)
    bearer = loaded.engine.state.actors[ALLY]
    assert bool(F._held(bearer, F.LANTERN_RELEASED)) == unperceived
    assert bearer.reaction_available == (not unperceived)
    roll = next(r for r in reversed(loaded.engine.rolls) if r.actor_id == ALLY and r.reason.startswith('ATTACK:'))
    # The actual printed condition still sees the ally's presence. The AI
    # cannot know that unseen presence before choosing its Release.
    assert roll.mode == 'NORMAL'
