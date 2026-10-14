"""CombatService preview, session execute_intent and cold-reload lane regressions.

Fixture actions seal combat effects on genuine compiled actors; production code,
controllers and rollers are never replaced. All new asset effects are exercised
with both manual choices and automatic recipients.
"""
import copy

import pytest

from combat.gate5_service import CombatService, _ReactionRequired
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.ext import spirit_assets
from tests.test_riders_c8 import ROOT, ME, ALLY, FOE, bundle, AC_ALL, HB_ALL, MK_ALL, MIND_SPIKE


def setup_action(b, name, effects, *, target='HOSTILE_ENTITY', area=None):
    a = copy.deepcopy(next(iter(b['action_catalog'])))
    a.update(source_definition_id='action:test.a2misc.' + name.lower().replace(' ', '_'), display_name=name,
             economy='NONE', target_kind=target, range_ft=90, costs=[], resolution_kind='TYPED')
    a['parameters'] = {'typed': {'source': a['source_definition_id'], 'numbers': {'cl': 5, 'pb': 3, 'save_dc': 15, 'attack_bonus': 100, 'key_mod': 3},
                        'effects': effects, 'riders': [], 'duration': {'kind': 'instant'}, 'area': area}, 'expected_damage': 0}
    b['action_catalog'].append(a); b['actor_template']['action_ids'].append(a['source_definition_id'])
    return a


class Fight:
    def __init__(self, tmp_path, features, *, ally_at=(4, 6), control='MANUAL', setup=None, battlefield=None,
                 foe_features=()):
        mine = bundle([*features, MIND_SPIKE])
        other = bundle([MIND_SPIKE], actor_id=ALLY, cl=5)
        enemy = bundle([MIND_SPIKE, *foe_features], actor_id=FOE, cl=18 if foe_features else 5,
                       pb=6 if foe_features else 3)
        for b in (mine, other, enemy):
            b['actor_template']['maximum_hp'] = 1000
        if setup:
            setup(mine, other, enemy)
        self.root = tmp_path
        self.service = CombatService(ROOT, tmp_path)
        self.session = self.service.persistence.create_match(match_seed='A2GMISSUB1', maximum_rounds=20,
            typed_bundles=(mine, other, enemy), roster_setup={'primary_actor_ids': [ME, ALLY, FOE],
            'team_by_actor': {ME: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
            'starting_positions': {ME: {'x': 3, 'y': 6}, ALLY: {'x': ally_at[0], 'y': ally_at[1]}, FOE: {'x': 11, 'y': 6}}},
            battlefield=battlefield)
        self.metadata = {'participant_control_modes': {ME: control, ALLY: 'MANUAL', FOE: 'MANUAL'}}
        self.advance(ME)

    @property
    def e(self):
        return self.session.engine

    def candidates(self, name, target=None, remote=None, at=None):
        return [c for c in self.e.legal_candidates()
                if ((a := self.e.action_catalog.get(c.source_definition_id)) is not None and a.display_name == name or a is None and c.display_name == name)
                and (target is None or target in c.target_ids)
                and (remote is None or bool(c.metadata.get('effect_origin')) == remote)
                and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]

    def act(self, name, target=None, *, remote=None, choose=None, at=None):
        candidates = self.candidates(name, target, remote, at)
        assert candidates, (name, [(c.display_name, c.target_ids) for c in self.e.legal_candidates()])
        c = candidates[0]
        intent = ActionIntent(intent_id=f'a2misc:{c.state_version}:{name}', decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
            target_ids=c.target_ids, destination=c.destination)
        answers = []
        prompts = []
        for _ in range(30):
            try:
                preview = self.service._run_preview(self.session, self.metadata, intent, tuple(answers))
                break
            except _ReactionRequired as paused:
                rc = paused.context; prompts.append(rc)
                spec = rc.extension_choice
                pick = choose(rc) if choose else (spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ())
                answers.append(ReactionDecision(checkpoint=rc.checkpoint, reactor_id=rc.reactor_id,
                    reaction_source_id=rc.reaction_source_id, selection='USE' if pick else 'DECLINE', option_ids=pick))
        else:
            pytest.fail('Unsettled choices')
        before = len(self.e.events)
        self.session.mechanical.execute_intent(ActionIntent.model_validate(preview['intent']))
        events = self.e.events[before:]
        assert [e.model_dump(mode='json') for e in events] == preview['events']
        return events, prompts

    def advance(self, aid):
        for _ in range(15):
            if self.e.state.current_actor_id == aid:
                return
            self.act('End turn')
        pytest.fail('No turn')

    def reload(self):
        before = self.e.state.model_dump(mode='json')
        self.session = CombatService(ROOT, self.root).persistence.load_match(self.session.match_id)
        assert self.session.verify()['status'] == 'PASS'
        assert self.session.mechanical.replay()['status'] == 'PASS'
        assert self.e.state.model_dump(mode='json') == before


def place(*cells):
    pending = iter(cells)
    def choose(rc):
        if rc.reaction_source_id == 'choice:needle.spirit_asset.space':
            cell = next(pending)
            assert cell in rc.extension_choice.option_ids
            return (cell,)
        spec = rc.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    return choose


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_legion_manifest_interpose_share_and_dormancy(tmp_path, control):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Test area', [{'type': 'damage', 'flat': 20, 'damage_types': ['psychic'], 'applies_to': 'enemies_in_area'}],
                     target='CELL', area={'shape': 'sphere', 'size_ft': 60})
        setup_action(enemy, 'Test destroy', [{'type': 'damage', 'flat': 200, 'damage_types': ['psychic'], 'applies_to': 'enemies_in_area'}],
                     target='CELL', area={'shape': 'sphere', 'size_ft': 60})
    f = Fight(tmp_path, AC_ALL, control=control, setup=setup)
    before = f.e.state.actors[ME].resources['resource:core.resonance']
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    assert len(shades) == 3 and len({o.current_hp for o in shades}) == 1
    assert all(o.ac == 17 and o.current_hp == 60 for o in shades)
    assert not any(o.object_id in f.e.state.initiative_order for o in shades)
    assert f.e.state.actors[ME].resources['resource:core.resonance'] == before - 6
    f.reload()
    if control == 'MANUAL':
        f.act('Legion: Interpose (Bonus Action)', ALLY, remote=True)
        assert f.e.state.actors[ALLY].temporary_hp == 12
        assert not f.candidates('Legion: Advise (Favor)', ALLY, True)
        f.reload()
    f.act('End turn'); f.advance(FOE)
    # Select the area candidate whose blast includes the shades.
    events, _ = f.act('Test area', at=(6, 6))
    assert sum(e.event_type == 'OBJECT_UPDATED' and bool(e.payload.get('damage')) for e in events) == 1
    all_shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion', live=False)
    assert {o.current_hp for o in all_shades} == {50}
    f.reload()
    f.act('Test destroy', at=(6, 6))
    assert all(o.destroyed for o in spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion', live=False))
    f.reload()
    f.act('End turn'); f.advance(ME)
    assert not f.candidates('Ancestral Legion')


@pytest.mark.parametrize('available', [0, 2])
def test_legion_requires_all_three_legal_placements_before_action(tmp_path, available):
    # Restrict the map to fewer than the three legal 30-foot placements.
    legal = [(5, 6), (5, 7), (5, 5)][:available]
    blockers = [{'id': i, 'kind': 'crate', 'x': x, 'y': y, 'hp': 1}
                for i, (x, y) in enumerate(( (x, y) for y in range(12) for x in range(16)
                    if abs(x - 3) <= 6 and abs(y - 6) <= 6
                    and (x, y) not in {(3, 6), (4, 6), (11, 6), *legal} ))]
    battlefield = {'width_squares': 16, 'height_squares': 12, 'square_size_ft': 5,
                   'starting_positions': {}, 'terrain_regions': [], 'map_objects': blockers}
    f = Fight(tmp_path, AC_ALL, battlefield=battlefield)
    before_resonance = f.e.state.actors[ME].resources['resource:core.resonance']
    assert not f.candidates('Ancestral Legion')
    f.reload()
    assert not f.candidates('Ancestral Legion')
    assert f.e.state.actors[ME].resources['resource:core.resonance'] == before_resonance


@pytest.mark.parametrize('creature_success', [False, True])
def test_save_area_rolls_damage_for_assets_independent_of_creature_outcome(tmp_path, creature_success):
    def setup(mine, ally, enemy):
        damage = {'type': 'damage', 'flat': 20, 'damage_types': ['psychic'], 'applies_to': 'target',
                  'damage_bonus_group': 'area-packet'}
        save = {'type': 'save', 'ability': 'dex', 'dc': 15,
                'on_fail': [damage], 'on_success': []}
        setup_action(enemy, 'Save area', [save], target='CELL', area={'shape': 'sphere', 'size_ft': 60})
        if creature_success:
            mine['actor_template']['saving_throws']['DEX'] = 100
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Save area', at=(6, 6))
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    assert shades and all(o.current_hp == 50 for o in shades)
    f.reload()


def test_save_area_damages_asset_when_it_is_the_only_subject(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Asset-only save area', [{'type': 'save', 'ability': 'dex', 'dc': 15,
            'on_fail': [{'type': 'damage', 'flat': 20, 'damage_types': ['psychic'], 'applies_to': 'target',
                        'damage_bonus_group': 'asset-only'}], 'on_success': []}], target='CELL',
            area={'shape': 'sphere', 'size_ft': 5})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:8,9,0', 'cell:8,10,0', 'cell:7,9,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Asset-only save area', at=(8, 9))
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    assert shades and all(o.current_hp == 50 for o in shades)
    f.reload()


def test_area_asset_uses_only_failed_save_branch_and_reloads(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Alternative save area', [{'type': 'save', 'ability': 'dex', 'dc': 15,
            'on_fail': [{'type': 'damage', 'flat': 13, 'damage_types': ['thunder'], 'applies_to': 'target'}],
            'on_success': [{'type': 'damage', 'flat': 27, 'damage_types': ['thunder'], 'applies_to': 'target'}]}],
            target='CELL', area={'shape': 'sphere', 'size_ft': 5})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:8,9,0', 'cell:8,10,0', 'cell:7,9,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Alternative save area', at=(8, 9))
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    assert shades and all(o.current_hp == 47 for o in shades)
    f.reload()


def test_area_asset_preserves_row_recipient_and_summon_predicates(tmp_path):
    def setup(mine, ally, enemy):
        save = {'type': 'save', 'ability': 'dex', 'dc': 15, 'on_success': [], 'on_fail': [
            {'type': 'damage', 'dice': {'count': 2, 'sides': 10}, 'damage_types': ['force'], 'applies_to': 'target'},
            {'type': 'if_summoned', 'effects': [{'type': 'damage', 'dice': {'count': 8, 'sides': 10},
                'damage_types': ['fire'], 'applies_to': 'target'}]}]}
        self_cost = {'type': 'damage', 'dice': {'count': 6, 'sides': 6}, 'damage_types': ['force'], 'applies_to': 'self'}
        setup_action(enemy, 'Scoped area', [save, self_cost], target='CELL', area={'shape': 'sphere', 'size_ft': 60})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('End turn'); f.advance(FOE)
    events, _ = f.act('Scoped area', at=(6, 6))
    rows = [e for e in events if e.event_type == 'DAMAGE_ROLLED'
            and e.source_definition_id == 'action:test.a2misc.scoped_area']
    assert len(rows) == 2  # one failed-save packet and the caster's self cost; no conditional asset roll
    hp = [o.current_hp for o in spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')]
    assert hp and len(set(hp)) == 1 and 40 <= hp[0] < 60
    f.reload()


@pytest.mark.parametrize(('save_scope', 'damaged_owner'), [
    ('enemies_in_area', ME),
    ('allies_in_area', FOE),
])
def test_mixed_area_asset_damage_inherits_enclosing_save_recipient_scope(tmp_path, save_scope, damaged_owner):
    def setup(mine, ally, enemy):
        save = {'type': 'save', 'ability': 'dex', 'dc': 15, 'applies_to': save_scope,
                'on_fail': [{'type': 'damage', 'dice': {'count': 2, 'sides': 10},
                             'damage_types': ['psychic'], 'applies_to': 'target'}],
                'on_success': []}
        # The benefit makes this a mixed area whose geometric roster is everyone.
        benefit = {'type': 'temp_hp', 'flat': 5, 'applies_to': 'allies_in_area'}
        harmful_recipients = 'hostile' if save_scope == 'enemies_in_area' else 'allies'
        setup_action(enemy, 'Mixed scoped area', [benefit, save], target='CELL',
                     area={'shape': 'sphere', 'size_ft': 60, 'recipients': 'all',
                           'harmful_recipients': harmful_recipients})

    f = Fight(tmp_path, AC_ALL, setup=setup, foe_features=AC_ALL)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Ancestral Legion', choose=place('cell:6,7,0', 'cell:6,8,0', 'cell:7,7,0'))

    events, _ = f.act('Mixed scoped area', at=(6, 6))
    assert any(e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage')
               and e.source_definition_id == 'action:test.a2misc.mixed_scoped_area' for e in events)
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    friendly_shades = spirit_assets.assets(f.e, f.e.state.actors[FOE], 'Ancestral Legion')
    if damaged_owner == ME:
        assert shades and all(o.current_hp < 60 for o in shades)
        assert friendly_shades and all(o.current_hp == 60 for o in friendly_shades)
    else:
        assert shades and all(o.current_hp == 60 for o in shades)
        assert friendly_shades and all(o.current_hp < 60 for o in friendly_shades)
    f.reload()
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    friendly_shades = spirit_assets.assets(f.e, f.e.state.actors[FOE], 'Ancestral Legion')
    if damaged_owner == ME:
        assert shades and all(o.current_hp < 60 for o in shades)
        assert friendly_shades and all(o.current_hp == 60 for o in friendly_shades)
    else:
        assert shades and all(o.current_hp == 60 for o in shades)
        assert friendly_shades and all(o.current_hp < 60 for o in friendly_shades)


def test_area_asset_skips_a_pool_already_hit_by_object_area(tmp_path):
    def setup(mine, ally, enemy):
        mine['actor_template']['saving_throws']['DEX'] = 100
        ally['actor_template']['saving_throws']['DEX'] = 100
        enemy['actor_template']['saving_throws']['DEX'] = 100
        setup_action(enemy, 'Object-aware area', [{'type': 'save', 'ability': 'dex', 'dc': 15,
            'on_fail': [{'type': 'damage', 'dice': {'count': 2, 'sides': 10}, 'damage_types': ['force'], 'applies_to': 'target'}],
            'on_success': []}], target='CELL', area={'shape': 'sphere', 'size_ft': 60})
        enemy.setdefault('typed_passives', []).append({
            'block': 'object_damage', 'feature_id': 'action:test.a2misc.object_aware_area', 'on': 'technique',
            'dice': {'count': 2, 'sides': 10}})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    assert any(r.get('feature_id') == 'action:test.a2misc.object_aware_area'
               for r in f.e.typed_passive_rows.get(FOE, []))
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('End turn'); f.advance(FOE)
    events, _ = f.act('Object-aware area', at=(6, 6))
    damaged = [e for e in events if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage')]
    assert len(damaged) == 1
    # This feature's printed object die uses the ordinary raw object-roll path;
    # the typed asset reader must not create a second evented damage roll.
    assert not any(e.event_type == 'DAMAGE_ROLLED'
                   and e.source_definition_id == 'action:test.a2misc.object_aware_area' for e in events)
    hp = [o.current_hp for o in spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')]
    assert hp and len(set(hp)) == 1 and hp[0] < 60
    f.reload()


def test_area_asset_honors_menu_damage_eligibility(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Menu area', [
            {'type': 'menu', 'id': 'test:area', 'count': 1, 'options': ['Quiet', 'Blast'], 'default': ['Quiet']},
            {'type': 'damage', 'flat': 19, 'damage_types': ['psychic'], 'applies_to': 'target',
             'menu': 'test:area', 'option': 'Blast'}], target='CELL', area={'shape': 'sphere', 'size_ft': 5})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:8,9,0', 'cell:8,10,0', 'cell:7,9,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Menu area', at=(8, 9))
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    assert shades and all(o.current_hp == 60 for o in shades)
    f.reload()


def test_area_without_admitted_assets_does_not_roll_asset_packets(tmp_path):
    def setup(mine, ally, enemy):
        mine['actor_template']['saving_throws']['DEX'] = 100
        ally['actor_template']['saving_throws']['DEX'] = 100
        setup_action(enemy, 'Unneeded area packet', [{'type': 'save', 'ability': 'dex', 'dc': 15,
            'on_fail': [{'type': 'damage', 'dice': {'count': 8, 'sides': 10},
                        'damage_types': ['psychic'], 'applies_to': 'target'}], 'on_success': []}], target='CELL',
            area={'shape': 'sphere', 'size_ft': 60})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('End turn'); f.advance(FOE)
    before = len(f.e.events)
    f.act('Unneeded area packet', at=(6, 6))
    emitted = f.e.events[before:]
    assert not any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == 'action:test.a2misc.unneeded_area_packet'
                   for e in emitted)
    f.reload()


def test_area_asset_does_not_receive_hit_only_packet(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Hit branch area', [{'type': 'attack', 'attack_kind': 'cultivation_ranged', 'attack_bonus': -100,
            'on_hit': [{'type': 'damage', 'flat': 22, 'damage_types': ['psychic'], 'applies_to': 'target'}],
                'on_miss': []}], target='CELL', area={'shape': 'sphere', 'size_ft': 60})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Hit branch area', at=(6, 6))
    shades = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')
    assert shades and all(o.current_hp == 60 for o in shades)
    f.reload()


@pytest.mark.parametrize('mode', ['fly', 'walk', 'climb', 'swim'])
def test_messenger_remote_support_once_per_turn_reload(tmp_path, mode):
    # A support fixture uses the real healing effect. Remote-origin eligibility
    # recognizes its Spirit Awakening source, not its test label.
    def setup(mine, ally, enemy):
        a = setup_action(mine, 'Test support', [{'type': 'temp_hp', 'flat': 7, 'applies_to': 'target'}], target='ALLY_OR_SELF')
        a['range_ft'] = 5
        a['parameters']['typed']['source'] = 'tianxia.path.spirit_awakening.feature.test_support'
    f = Fight(tmp_path, MK_ALL, ally_at=(10, 6), setup=setup)
    f.act('Record willing messenger contact', choose=lambda c: ('record',) if c.reaction_source_id.endswith('miko.messenger_contact') else ())
    f.act(f'Manifest Messenger: {mode.title()}', choose=place('cell:9,6,0'))
    messenger = spirit_assets.assets(f.e, f.e.state.actors[ME], 'Kami Messenger')[0]
    assert messenger.current_hp == 24 and messenger.ac == 17
    assert messenger.component['travel_mode'] == mode
    f.reload()
    assert not f.candidates('Test support', ALLY, False)
    assert not f.candidates('Test support', FOE, True)
    f.act('Test support', ALLY, remote=True)
    assert f.e.state.actors[ALLY].temporary_hp == 7
    assert f.e.state.actors[FOE].temporary_hp == 0
    assert not f.candidates('Test support', ALLY, True)
    f.reload()
    f.act('End turn', choose=place('cell:9,7,0'))
    assert spirit_assets.assets(f.e, f.e.state.actors[ME], 'Kami Messenger')[0].position.y == 7
    f.reload()


@pytest.mark.parametrize('mode,condition', [('Hold the Heart', 'despair'), ('Bear It With Me', 'emotional_wound')])
@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_borrowed_courage_emotional_effects_source_and_reload(tmp_path, mode, condition, control):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Test emotional wound', [{'type': 'condition', 'condition': condition, 'applies_to': 'target',
                     'expires_on': 'UNTIL_REMOVED', 'condition_data': {'rule': {'no_reactions': True}, 'origin_save': {'ability': 'WIS', 'dc': 15}}}])
    f = Fight(tmp_path, HB_ALL, control=control, setup=setup)
    f.act('Vow Mark', ALLY)
    from combat.typed_executor import bears_mark
    assert bears_mark(f.e.state.actors[ALLY], ME, 'Vow Mark')
    f.act('End turn'); f.advance(FOE); f.act('Test emotional wound', ALLY); f.act('End turn'); f.advance(ME)
    f.reload()
    assert not f.candidates(f'Borrowed Courage: {mode}', FOE)
    f.act(f'Borrowed Courage: {mode}', ALLY)
    f.reload()
    if mode == 'Hold the Heart':
        assert any(c.condition_id.endswith('suppressed.' + condition) for c in f.e.state.actors[ALLY].conditions.values())
    else:
        held = [c for c in f.e.state.actors[ME].conditions.values() if c.condition_id.endswith('.' + condition)]
        assert len(held) == 1 and held[0].source_actor_id == FOE
        assert held[0].data['origin_save']['dc'] == 15
        assert not any(c.condition_id.endswith('.' + condition) for c in f.e.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('selected,transferred', [('emotional_wound', True), ('despair', False)])
def test_bear_it_with_me_selects_among_instances_before_immunity(tmp_path, selected, transferred):
    def setup(mine, ally, enemy):
        mine.setdefault('typed_passives', []).append({'block': 'condition_immunity', 'conditions': ['despair']})
        setup_action(enemy, 'Test two feelings', [
            {'type': 'condition', 'condition': 'emotional_wound', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
             'condition_data': {'label': 'Emotional wound', 'rule': {'no_reactions': True}}},
            {'type': 'condition', 'condition': 'despair', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
             'condition_data': {'label': 'Despair', 'rule': {'no_reactions': True}}}])
    f = Fight(tmp_path, HB_ALL, setup=setup)
    f.act('Vow Mark', ALLY)
    f.act('End turn'); f.advance(FOE); f.act('Test two feelings', ALLY)
    ally = f.e.state.actors[ALLY]
    assert sum(c.condition_id.endswith('.emotional_wound') for c in ally.conditions.values()) == 1
    assert sum(c.condition_id.endswith('.despair') for c in ally.conditions.values()) == 1
    f.act('End turn'); f.advance(ME)

    def choose_effect(rc):
        labels = (rc.choice_trigger or {}).get('labels') or {}
        option = next(key for key, value in labels.items() if selected.replace('_', ' ') in value.lower())
        return (option,)

    f.act('Borrowed Courage: Bear It With Me', ALLY, choose=choose_effect)
    f.reload()
    ally = f.e.state.actors[ALLY]
    me = f.e.state.actors[ME]
    assert any(c.condition_id.endswith('.emotional_wound') for c in me.conditions.values()) is transferred
    if transferred:
        assert any(c.condition_id.endswith('.despair') for c in ally.conditions.values())
        assert not any(c.condition_id.endswith('.emotional_wound') for c in ally.conditions.values())
    else:
        assert any(c.condition_id.endswith('.emotional_wound') for c in ally.conditions.values())
        assert any(c.condition_id.endswith('.despair') for c in ally.conditions.values())


@pytest.mark.parametrize(('payload_scope', 'save_scope', 'default_scope', 'martial_override', 'damaged_owner'), [
    ('allies_in_area', None, 'hostile', False, FOE),
    ('enemies_in_area', None, 'allies', False, ME),
    ('allies_in_area', 'enemies_in_area', 'hostile', False, FOE),
    ('enemies_in_area', 'allies_in_area', 'allies', False, ME),
    ('allies_in_area', None, 'allies', True, ME),
    ('allies_in_area', 'allies_in_area', 'allies', True, ME),
])
def test_area_asset_explicit_payload_scope_overrides_defaults(tmp_path, payload_scope, save_scope,
                                                            default_scope, martial_override, damaged_owner):
    def setup(mine, ally, enemy):
        damage = {'type': 'damage', 'dice': {'count': 2, 'sides': 10},
                  'damage_types': ['psychic'], 'applies_to': payload_scope}
        effects = [damage] if save_scope is None else [
            {'type': 'save', 'ability': 'dex', 'dc': 15, 'applies_to': save_scope,
             'on_fail': [damage], 'on_success': [
                 {'type': 'damage', 'dice': {'count': 8, 'sides': 10},
                  'damage_types': ['psychic'], 'applies_to': payload_scope}]}]
        action = setup_action(enemy, 'Explicit asset area', [
            {'type': 'temp_hp', 'flat': 5, 'applies_to': 'allies_in_area'}, *effects],
            target='CELL', area={'shape': 'sphere', 'size_ft': 10, 'recipients': 'all',
                                 'harmful_recipients': default_scope})
        if martial_override:
            from combat.area_recipients import scoped_area
            typed = action['parameters']['typed']
            typed['sphere'] = 'Berserker'
            typed['area'] = scoped_area(typed['area'], typed['effects'], typed=typed)
            assert typed['area']['harmful_recipient_override'] == 'hostile'

    f = Fight(tmp_path, AC_ALL, setup=setup, foe_features=AC_ALL)
    f.act('Ancestral Legion', choose=place('cell:8,9,0', 'cell:8,10,0', 'cell:7,9,0'))
    f.act('End turn'); f.advance(FOE)
    f.act('Ancestral Legion', choose=place('cell:9,9,0', 'cell:9,10,0', 'cell:10,9,0'))
    f.reload()
    events, _ = f.act('Explicit asset area', at=(8, 9))
    # No creatures are inside: only the one admitted failed/direct packet rolls.
    rolls = [e for e in events if e.event_type == 'DAMAGE_ROLLED'
             and e.source_definition_id == 'action:test.a2misc.explicit_asset_area']
    assert len(rolls) == 1
    updates = [e for e in events if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage')]
    assert len(updates) == 1
    def check_hp():
        for owner in (ME, FOE):
            shades = spirit_assets.assets(f.e, f.e.state.actors[owner], 'Ancestral Legion')
            hp = {o.current_hp for o in shades}
            assert len(shades) == 3 and len(hp) == 1
            assert (next(iter(hp)) < 60) if owner == damaged_owner else hp == {60}
    check_hp()
    f.reload()
    check_hp()
