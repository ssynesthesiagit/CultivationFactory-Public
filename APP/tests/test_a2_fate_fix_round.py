"""Fate review regressions through table intents, saved receipts and cold replay.

Sealed setup actions fix a Wheel face (not a random casting outcome). Synthetic
contests invoke shipped producers without resetting economy or editing live state.
"""
import pytest
from combat.ext import fate_riders as F
from combat.gate4_adapters import ManualControllerAdapter
from tests import worker2_support as S
from tests.cw2_service_support import add_action, seal
from tests.h1_support import sheet
from tests.test_carry import KIT
from tests.test_r9i_choices import action, resolve, finish_turn
from tests.test_r9i_karma_persistence import act


def wheel_setup(bundle, face, bonus=2):
    kind = 'attack' if face <= 2 else 'save' if face <= 4 else 'check'
    add_action(bundle, 'Set Wheel face', [{'type': 'condition', 'condition': 'turning_wheel',
        'applies_to': 'self', 'condition_data': {'kind': kind, 'bonus': bonus, 'face': face}}],
        target='SELF', typed={'duration': {'kind': 'until_removed'}})


def steer(combat, mid, actor, cid):
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')


@pytest.mark.parametrize('side', ['actor', 'defender'])
@pytest.mark.parametrize('face', [2, 4, 6])
@pytest.mark.parametrize('release', [False, True])
def test_wheel_initial_typed_contest_both_sides_manual_bearer_on_ai_turn(tmp_path, side, face, release):
    def prepare(bundles):
        wheel_setup(bundles[0], face)
    combat, table, mid = S.fixture(tmp_path, [F.WHEEL_ID, 'TAL_ATHLETICS_SUDDEN_FLANK'],
        foe_sheet=sheet(['TAL_ATHLETICS_SUDDEN_FLANK'], cl=15),
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 8, 'y': 6}, bundle_transform=prepare)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Set Wheel face'), answers), {})
    before = S.reload(tmp_path, mid)
    assert F._held(before.state.actors[S.OWNER], F.WHEEL)
    from combat.ability_checks import skill_bonus
    base = skill_bonus(before, before.state.actors[S.OWNER], 'Acrobatics', 2)
    actor, target = (S.OWNER, S.FOE) if side == 'actor' else (S.FOE, S.OWNER)
    S.turn(table, mid, actor)
    cid = action(table, mid, 'Tumble (Action)', target)
    if side == 'defender':
        steer(combat, mid, actor, cid)
    prompts = []
    def send(answers):
        result = table.auto_step(mid, 0, answers) if side == 'defender' else act(table, mid, cid, answers)
        if result['status'] == 'REACTION_REQUIRED' and result['reaction']['context']['reaction_source_id'] == 'choice:needle.wheel_release':
            prompts.append(result['reaction'])
        return result
    resolve(send, {'choice:needle.wheel_release': ['release'] if release else None})
    assert prompts, 'initial opposed draw must offer Release before any die'
    assert all(p['context']['reactor_id'] == S.OWNER and 'before' in p['moment'] and 'Reaction' in p['moment'] and 'd20 ' not in p['moment'] for p in prompts)
    loaded = S.reload(tmp_path, mid)
    event = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
    roll = event.payload['actor' if side == 'actor' else 'target']
    assert roll['actor_id'] == S.OWNER
    assert roll['modifier'] == base + (4 if release else 2 if face == 6 else 0)
    bearer = loaded.state.actors[S.OWNER]
    assert bool(F._held(bearer, F.WHEEL)) == (not release)
    assert bearer.reaction_available == (not release)


@pytest.mark.parametrize('producer', ['typed', 'brute', 'steal'])
@pytest.mark.parametrize('skill', ['Athletics', 'Acrobatics'])
def test_lantern_defending_skill_consumed_once_with_reload_and_help_marker(tmp_path, producer, skill):
    def prepare(bundles):
        effects = {'typed': {'type': 'contest_against',
                    'actor_check': {'kind': 'check', 'ability': 'STR', 'skill': 'Athletics'},
                    'target_check': {'kind': 'check', 'ability': 'STR' if skill == 'Athletics' else 'DEX', 'skill': skill}},
                   'brute': {'type': 'brutal_shove', 'mode': 'prone_only', 'no_damage': True, 'no_manhandle': True},
                   'steal': {'type': 'scoundrel_check'}}
        add_action(bundles[2], 'Defending check', [effects[producer]], target='HOSTILE_ENTITY')
        seal(bundles[2])
    owner_doc = sheet([F.LANTERN_ID], cl=15)
    # The real proficient self-Help action must be offered before an opponent
    # approaches. Favor the chosen defender skill for Steal Equipment's resolver.
    skill_rows = [{'skill': skill, 'bonus': 30, 'proficiency_multiplier': 1}]
    # worker2 fixture accepts a sealed owner bundle as well as a foe sheet.
    from combat.factory_compiler import compile_character
    owner_doc['ability_scores_and_statistics']['skills'] = skill_rows
    owner_doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    owner_bundle = compile_character(owner_doc, actor_id=S.OWNER, reaction_plan={'ask': True})
    combat, table, mid = S.fixture(tmp_path, [F.LANTERN_ID], owner_bundle=owner_bundle,
        foe_kit={'starting_kit': KIT}, foe_position={'x': 6, 'y': 6}, ally_position={'x': 8, 'y': 6}, bundle_transform=prepare)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Lone Lantern Auspice', S.OWNER), answers), {})
    finish_turn(table, mid)
    S.turn(table, mid, S.OWNER)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Help yourself'), answers), {'choice:needle.lantern_help': [skill]})
    S.reload(tmp_path, mid)
    finish_turn(table, mid)
    S.turn(table, mid, S.FOE)
    move = next(m for m in table.state(mid)['menu']['moves'] if m['destination'] == {'x': 4, 'y': 6})
    resolve(lambda answers: act(table, mid, move['candidate_id'], answers), {})
    for index in range(2):
        cid = action(table, mid, 'Defending check', S.OWNER)
        resolve(lambda answers: act(table, mid, cid, answers), {'choice:needle.brute_contest_skill': [skill]})
        loaded = S.reload(tmp_path, mid)
        event = next(e for e in reversed(loaded.events) if e.event_type == 'CHECK_ROLLED')
        assert event.payload['target']['mode'] == ('ADVANTAGE' if index == 0 else 'NORMAL')
        held = F._held(loaded.state.actors[S.OWNER], F.LANTERN_HELP)[0]
        assert held.data['used'] is True and held.data['rule'] == {}
        label = f"Lone Lantern Help: {skill} check benefit used; no other creature's Help until the start of your next turn."
        assert held.data['label'] == label
        from combat.gate5_service import CombatService
        from tests.h1_support import ROOT
        cold = CombatService(ROOT, tmp_path)
        projected = cold.presentation(mid)
        owner = next(row for row in projected['actors'] if row['entity_id'] == S.OWNER)
        pill = next(row for row in owner['conditions'] if row['condition_id'] == F.LANTERN_HELP)
        assert pill['display_name'] == label
        applied = [row for boundary in cold.history(mid)['boundaries'] for row in boundary['feed']
                   if row['event_type'] == 'CONDITION_APPLIED'
                   and row['raw']['payload'].get('condition_id') == F.LANTERN_HELP
                   and row['raw']['payload'].get('gate3_condition_after', {}).get('data', {}).get('used')]
        assert applied and all(label in row['summary'] and 'Advantage' not in row['summary'] for row in applied)

        from combat.ext.help_policy import allowed
        assert not allowed(loaded, loaded.state.actors[S.ALLY], loaded.state.actors[S.OWNER])


@pytest.mark.parametrize('delivery', ['native', 'typed', 'typed_fixed', 'flat'])
def test_wheel_damage_amount_service_rolled_once_and_fixed_unchanged(tmp_path, monkeypatch, delivery):
    def prepare(bundles):
        wheel_setup(bundles[0], 2)
        if delivery == 'native':
            S.sealed_native_attack(bundles[0], 'Measured damage', damage_type='FORCE', modifier=3)
        elif delivery == 'flat':
            add_action(bundles[0], 'Measured damage', [{'type': 'damage', 'flat': 7, 'damage_types': ['force'], 'applies_to': 'target'}], target='HOSTILE_ENTITY')
        else:
            weapon = {'damage': {'count': 1, 'sides': 6, 'modifier': 3}, 'damage_type': 'FORCE'}
            if delivery == 'typed_fixed':
                weapon['fixed_damage'] = 7
            add_action(bundles[0], 'Measured damage', [{'type': 'attack', 'attack_kind': 'weapon'}], target='HOSTILE_ENTITY',
                typed={'numbers': {'attack_bonus': 20}, 'weapon': weapon})
    combat, table, mid = S.fixture(tmp_path, [F.WHEEL_ID], bundle_transform=prepare, foe_position={'x': 4, 'y': 6}, ally_position={'x': 8, 'y': 6})
    resolve(lambda answers: act(table, mid, action(table, mid, 'Set Wheel face'), answers), {})
    from tests.sol109_support import accurate_attacks
    accurate_attacks(monkeypatch, S.OWNER)
    before = S.reload(tmp_path, mid)
    start, hp = len(before.events), before.state.actors[S.FOE].current_hp
    resolve(lambda answers: act(table, mid, action(table, mid, 'Measured damage', S.FOE), answers), {})
    loaded = S.reload(tmp_path, mid)
    events = loaded.events[start:]
    packets = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and S.FOE in e.target_ids]
    assert len(packets) == 1
    if delivery == 'flat':
        expected = 7
    else:
        rolled = next(e.payload for e in events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == S.OWNER)
        assert rolled['modifier'] == (3 if delivery == 'typed_fixed' else 5)
        assert len(rolled['dice']) == (0 if delivery == 'typed_fixed' else 1)
        expected = 10 if delivery == 'typed_fixed' else sum(rolled['dice']) + 5
        assert rolled['total'] == expected
    assert packets[0].payload['hp_damage'] == expected
    assert loaded.state.actors[S.FOE].current_hp == hp - expected
    assert F._held(loaded.state.actors[S.OWNER], F.WHEEL)


def test_typed_contest_prepares_once_then_defers_rewrites_and_raw_replacement(tmp_path, monkeypatch):
    from combat import ext
    observations = []
    ext.effects()
    def reroll(engine, roll, intent):
        if roll.reason.startswith('CHECK:') and 'tumble' in roll.reason:
            context = engine.d20_context(roll)
            observations.append((roll.actor_id, context['dc']))
            return {'source_id': 'test:contest-reroll', 'operation': 'reroll'}
        return None
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*ext._HOOKS.get('d20_result', []), reroll])
    def prepare(bundles):
        wheel_setup(bundles[0], 6)
    combat, table, mid = S.fixture(tmp_path, [F.WHEEL_ID, 'TAL_ATHLETICS_SUDDEN_FLANK'],
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 8, 'y': 6}, bundle_transform=prepare)
    resolve(lambda answers: act(table, mid, action(table, mid, 'Set Wheel face'), answers), {})
    seen = resolve(lambda answers: act(table, mid, action(table, mid, 'Tumble (Action)', S.FOE), answers), {})
    assert seen.count('choice:needle.wheel_release') == 1
    loaded = S.reload(tmp_path, mid)
    rewrites = [e for e in loaded.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == 'test:contest-reroll']
    assert [e.actor_id for e in rewrites] == [S.FOE, S.OWNER]
    theirs, mine = [e.payload for e in rewrites]
    # Both initial draws preceded the first rewrite. Replacement keeps the
    # already prepared modifier and never contributes Wheel a second time.
    assert mine['original']['counter_end'] <= theirs['result']['counter_end']
    assert mine['original']['modifier'] == mine['result']['modifier'] == 4
    assert observations[-2:] == [(S.FOE, mine['original']['total']), (S.OWNER, theirs['result']['total'] + 1)]
    assert F._held(loaded.state.actors[S.OWNER], F.WHEEL)


@pytest.mark.parametrize('delivery', ['native', 'typed'])
@pytest.mark.parametrize('attacks', [1, 2])
@pytest.mark.parametrize('bonus', [1, 2, 3])
def test_wheel_release_removes_damage_bonus_each_strike_commit_reload(tmp_path, monkeypatch, delivery, attacks, bonus):
    def prepare(bundles):
        wheel_setup(bundles[0], 2, bonus)
        if delivery == 'native':
            S.sealed_native_attack(bundles[0], 'Release damage', damage_type='FORCE', modifier=3, attacks=attacks)
        else:
            add_action(bundles[0], 'Release damage', [{'type': 'attack', 'attack_kind': 'weapon', 'count': attacks}],
                target='HOSTILE_ENTITY', typed={'numbers': {'attack_bonus': 20},
                    'weapon': {'damage': {'count': 1, 'sides': 6, 'modifier': 3}, 'damage_type': 'FORCE'}})
    combat, table, mid = S.fixture(tmp_path, [F.WHEEL_ID], bundle_transform=prepare,
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 8, 'y': 6})
    resolve(lambda answers: act(table, mid, action(table, mid, 'Set Wheel face'), answers), {})
    from tests.sol109_support import accurate_attacks
    accurate_attacks(monkeypatch, S.OWNER)
    before = S.reload(tmp_path, mid)
    start, hp = len(before.events), before.state.actors[S.FOE].current_hp
    prompts = resolve(lambda answers: act(table, mid, action(table, mid, 'Release damage', S.FOE), answers),
        {'choice:needle.wheel_release': ['release']})
    assert prompts.count('choice:needle.wheel_release') == 1
    loaded = S.reload(tmp_path, mid)
    events = loaded.events[start:]
    released = [e for e in events if e.event_type == 'REACTION_RESOLVED' and e.payload.get('reaction_name') == 'Turning Wheel Release']
    assert len(released) == 1 and released[0].payload['bonus'] == 2 * bonus
    attack_rolls = [e.payload for e in events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == S.OWNER]
    assert len(attack_rolls) == attacks
    assert [row['modifier'] for row in attack_rolls] == [20 + 2 * bonus] + [20] * (attacks - 1)
    rolls = [e.payload for e in events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == S.OWNER]
    assert len(rolls) == attacks
    assert all(row['modifier'] == 3 and row['total'] == sum(row['dice']) + 3 for row in rolls)
    packets = [e.payload for e in events if e.event_type == 'DAMAGE_COMMITTED' and S.FOE in e.target_ids]
    assert [row['hp_damage'] for row in packets] == [row['total'] for row in rolls]
    assert loaded.state.actors[S.FOE].current_hp == hp - sum(row['total'] for row in rolls)
    assert not F._held(loaded.state.actors[S.OWNER], F.WHEEL)
    assert loaded.state.actors[S.OWNER].reaction_available is False
