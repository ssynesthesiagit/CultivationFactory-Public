"""DS11 regressions exercise real table commits, reload and replay."""
import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from tests import test_tabletop_hunt6 as H
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.test_friendly_fire_area_table import _commit_area_action

CALAMITY = 'tianxia.talent.destruction.returning_calamity'


@pytest.mark.parametrize('ally_position,inside', [
    ({'x': 4, 'y': 4, 'z': 1}, True),
    ({'x': 4, 'y': 4, 'z': 4}, False),
    # Within the horizontal radius and vertical height, but outside the sphere.
    ({'x': 6, 'y': 4, 'z': 3}, False),
])
def test_elevated_zone_preview_matches_committed_volume(tmp_path, ally_position, inside):
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.spatial_areas import zone_contains
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet

    source = 'TAL_DARK_HUNGRY_DARKNESS'
    bundles = []
    for who, name in [(H.LEFT, 'Left'), (H.ALLY, 'Ally'), (H.RIGHT, 'Right')]:
        document = sheet([source] if who == H.LEFT else [], cl=15, dc=99)
        document['identity']['display_name'] = name
        bundle = compile_character(document, actor_id=who)
        # Ordinary hovering ally; altitude is part of the persisted initial state.
        if who == H.ALLY:
            bundle['actor_template'].update(fly_speed_ft=30, hover=True)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(H.ROOT, tmp_path)
    session = combat.persistence.create_match(
        match_seed='SOL104R-VOLUME', typed_bundles=tuple(bundles),
        battlefield={'battlefield_id': 'test:volume', 'width_squares': 12,
                     'height_squares': 8, 'square_size_ft': 5, 'terrain_regions': [],
                     'starting_positions': {}},
        roster_setup={'primary_actor_ids': [H.LEFT, H.ALLY, H.RIGHT],
                      'team_by_actor': {H.LEFT: 'a', H.ALLY: 'a', H.RIGHT: 'b'},
                      'starting_positions': {H.LEFT: {'x': 0, 'y': 4},
                                             H.ALLY: ally_position,
                                             H.RIGHT: {'x': 4, 'y': 4}}})
    mid = session.match_id
    for who in (H.LEFT, H.ALLY, H.RIGHT):
        combat.set_controller_mode(mid, actor_id=who, controller_mode='MANUAL')
    table = TabletopService(combat, tmp_path)
    while table.state(mid)['menu']['actor_id'] != H.LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    # Automatic shaping previews Hungry Darkness, while manual placement stays
    # available once the player returns to manual control and selects that shape.
    combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith('Darkness') and c.destination
                     and (c.destination.x, c.destination.y, c.destination.z) == (4, 4, 0))
    assert candidate.metadata.get('allies_in_area', 0) == int(inside)
    assert candidate.metadata.get('unavoidable_allies_in_area', 0) == int(inside)
    assert (candidate.metadata.get('ally_expected_damage', 0) > 0) is inside
    context = build_decision_context(engine, PolicyLibrary(H.ROOT).fallback(), for_ai=True)
    assert any(c.candidate_id == candidate.candidate_id for c in context.legal_candidates) is (not inside)
    assert engine.state.model_dump(mode='json') == before
    combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='MANUAL')
    shape_menu = table.state(mid)['menu']
    shape = next(g['options'][0]['candidate_id'] for g in shape_menu['actions']
                 if g['label'] == 'Shape Darkness: Hungry Darkness')
    assert table.act(mid, shape, shape_menu['decision_id'], shape_menu['state_version'],
                     table.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    result, option = _commit_area_action(table, mid, 'Darkness', {'x': 4, 'y': 4})
    assert result['status'] == 'COMMITTED', result
    assert ('Hits allies too: Ally' in option['label']) is inside
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    zone = next(z for z in loaded.engine.state.zones.values() if 'darkness' in z.source_definition_id.lower())
    assert zone_contains(loaded.engine, loaded.engine.state.actors[H.ALLY], zone) is inside
    seq = loaded.engine.state.event_sequence
    for _ in range(6):
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
        if loaded.engine.state.current_actor_id == H.ALLY:
            break
    else:
        pytest.fail('The elevated ally did not start its next turn')
    damage = [e for e in loaded.engine.events if e.sequence > seq
              and e.event_type == 'DAMAGE_COMMITTED' and H.ALLY in e.target_ids
              and 'darkness' in e.source_definition_id.lower()]
    assert bool(damage) is inside
    assert loaded.engine.state.actors[H.ALLY].position.model_dump() == ally_position
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('source,label', [
    ('TAL_MAGMA_BLACKGLASS_RIVER', 'Blackglass River'),
    ('TAL_DEATH_WITHERING_FIELD', 'Withering Field'),
    ('TAL_DARK_HUNGRY_DARKNESS', 'Darkness'),
])
def test_zone_candidates_expose_delayed_ally_harm(tmp_path, source, label):
    # A placed river starts at the aim and runs away from its caster. Put the
    # ally ahead of (4,4), within its 15-foot width, rather than behind it.
    starts = {'team1': [[3, 4], [5, 5]], 'team2': [[4, 4]]} if label == 'Blackglass River' else None
    combat, table, mid = H.table_fight(tmp_path, [source], ally_talents=[], starts=starts)
    if label == 'Darkness':
        combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates()
                  if c.display_name.startswith(label)]
    assert candidates, label
    risky = next(c for c in candidates if c.destination and c.destination.x == 4 and c.destination.y == 4)
    assert risky.metadata.get('allies_in_area', 0) > 0
    assert risky.metadata.get('ally_expected_damage', 0) > 0
    # AI sees the same recipient data; manual placements stay legal.
    context = build_decision_context(engine, PolicyLibrary(H.ROOT).fallback(), for_ai=True)
    assert all(c.candidate_id != risky.candidate_id for c in context.legal_candidates)
    if label != 'Darkness':
        seq = engine.state.event_sequence
        result, _ = _commit_area_action(table, mid, label, {'x': 4, 'y': 4})
        assert result['status'] == 'COMMITTED'
        # Player placement is still legal and its delayed damage really reaches
        # the ally after a committed turn boundary, rather than a preview only.
        for _ in range(6):
            loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
            if any(e.sequence > seq and e.event_type == 'DAMAGE_COMMITTED'
                   and H.ALLY in e.target_ids and source in e.source_definition_id for e in loaded.engine.events):
                break
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
        else:
            pytest.fail('The manual zone did not damage the ally on its next turn')
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('attacker,ask,use', [
    (H.ALLY, False, False), (H.RIGHT, False, True),
    (H.ALLY, True, True), (H.ALLY, True, False),
])
def test_retaliation_spares_allies_automatically_but_keeps_player_choice(monkeypatch, tmp_path, attacker, ask, use, ai_turn):
    combat, table, mid = H.table_fight(tmp_path, [CALAMITY], ask=ask, ally_talents=[])
    if not ask:
        combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
    if ai_turn:
        # Ask-me remains owned by the manual reactor even on someone else's
        # automatic turn; automatic reactors still make their own decision.
        combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='MANUAL')
        while table.state(mid)['menu']['actor_id'] != H.RIGHT:
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
        if not ask:
            combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
        combat.set_controller_mode(mid, actor_id=H.RIGHT, controller_mode='LOCAL_AUTO')
    def wound(engine, event_type, kwargs):
        if event_type == 'HOLD_POSITION_COMMITTED':
            engine._commit_damage(engine.state.actors[H.LEFT], 1, 'FORCE',
                                  'test:trigger', attacker, engine._active_intent, reaction_depth=0)
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS['event'], wound])
    before = combat._load_session(mid).engine.state.event_sequence
    state = table.state(mid)
    cid = next(c.candidate_id for c in combat._legal_candidates(combat._load_session(mid))
               if c.source_definition_id == H.HOLD)
    automatic_action = not ask or ai_turn
    if automatic_action:
        from combat.gate4_adapters import ManualControllerAdapter
        real = combat.controller
        class HoldController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = HoldController()
        send = lambda answers=(): table.auto_step(mid, 0, list(answers))
    else:
        send = lambda answers=(): table.act(mid, cid, state['menu']['decision_id'], state['menu']['state_version'], 0, list(answers))
    result = send()
    if ask:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['reaction'] == 'Returning Calamity'
        assert 'Ally' in str(prompt)
        result = send([{**prompt['context'], 'selection': 'USE' if use else 'DECLINE'}])
    assert result['status'] == 'COMMITTED', result
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    fired = [e for e in loaded.engine.events if e.sequence > before
             and e.source_definition_id == CALAMITY and e.event_type == 'DAMAGE_COMMITTED']
    assert bool(fired) is use
    if fired:
        assert fired[0].target_ids == (attacker,)
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_ai_does_not_project_before_combat_but_player_can_select_it(tmp_path):
    from combat import prefight
    from combat.ext.astral_projection import SOURCE, projected_instances
    combat, table, mid = H.table_fight(tmp_path, [SOURCE], primary='Resonance', ally_talents=[])
    session = CombatService(H.ROOT, tmp_path)._load_session(mid)
    bundle = next(b for b in session.engine.typed_bundle_documents if b['actor_id'] == H.LEFT)
    option = next(o for o in bundle['prefight']['options'] if 'astral_projection' in o['action_id'])
    assert option['ai_eligible'] is False
    assert option['action_id'] not in bundle['prefight']['picks']
    assert prefight.validate([option['action_id']], bundle['prefight']['options'], prefight.starting_pools(bundle))
    assert not projected_instances(session.engine, session.engine.state.actors[H.LEFT])
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    assert CombatService(H.ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('effect', [
    {'type': 'drop_item'}, {'type': 'take_weapon'}, {'type': 'pickup_item'},
    {'type': 'recover_weapon'}, {'type': 'equipment_grip'},
    {'type': 'condition', 'condition': 'disarmed'},
    {'type': 'condition', 'condition': 'condition:core.unconscious'},
    {'type': 'condition', 'condition': 'incapacitated'},
])
def test_equipment_and_disabling_self_buffs_need_player_selection(effect):
    from combat import prefight
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    action = ActionDefinition(source_definition_id='test:unknown_form', display_name='Deliberate form', owner_id=H.LEFT,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'duration': {'kind': 'minutes', 'amount': 10}, 'effects': [effect]}})
    options = prefight.options([action], H.LEFT)
    assert len(options) == 1 and options[0]['ai_eligible'] is False
    assert prefight.choose(options, {}) == []
    assert prefight.validate(['test:unknown_form'], options, {}) == ['test:unknown_form']


def test_other_form_can_use_the_same_prefight_seam(monkeypatch):
    from combat import prefight
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    action = ActionDefinition(source_definition_id='test:another_form', display_name='Scouting form', owner_id=H.LEFT,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'duration': {'kind': 'minutes', 'amount': 10}, 'effects': []}})
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'prefight_ai_allowed', [*ext._HOOKS['prefight_ai_allowed'],
        lambda candidate: False if candidate.source_definition_id == 'test:another_form' else None])
    assert prefight.choose(prefight.options([action], H.LEFT), {}) == []


def test_real_ai_table_places_damaging_zone_away_from_allies(tmp_path):
    source = 'TAL_DEATH_WITHERING_FIELD'
    combat, table, mid = H.table_fight(tmp_path, [source], ally_talents=[])
    combat.set_controller_mode(mid, actor_id=H.LEFT, controller_mode='LOCAL_AUTO')
    # A supported policy override favors the real zone; safety comes from
    # eligibility, without changing or bypassing the actual scorer.
    engine = combat._load_session(mid).engine
    action = next(a for a in engine.action_catalog.values() if a.owner_id == H.LEFT
                  and a.display_name == 'Withering Field')
    normal = combat.controller
    class FavorZone:
        def choose_primary_action(self, context):
            policy = context.policy.model_copy(update={'action_priorities': {action.source_definition_id: 10000}})
            return normal.choose_primary_action(context.model_copy(update={'policy': policy}))
        def __getattr__(self, name):
            return getattr(normal, name)
    combat.controller = FavorZone()
    assert table.auto_step(mid, 0)['status'] == 'COMMITTED'
    loaded = CombatService(H.ROOT, tmp_path)._load_session(mid)
    zone = next(z for z in loaded.engine.state.zones.values() if source in z.source_definition_id)
    assert loaded.engine._footprint_intersects(loaded.engine.state.actors[H.RIGHT], zone.affected_cells)
    assert all(not loaded.engine._footprint_intersects(a, zone.affected_cells)
               for a in loaded.engine.state.actors.values() if a.team_id == loaded.engine.state.actors[H.LEFT].team_id)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
