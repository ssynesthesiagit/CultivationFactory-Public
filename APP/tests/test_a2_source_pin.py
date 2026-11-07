"""Heaven-Sealing Source Pin (A2 source lane): a creature that teleports out of the area makes its Constitution save first.

Printed (rules_text.json): "A creature of your choice that starts in the area or enters it ... must make a Constitution
saving throw against your Source Save DC before teleporting out of the area. On a failed save, that teleport fails and the
use of the teleport effect is spent. On a successful save, the creature teleports normally."

Each case runs through the table: the owner places the Pin on a real map square, the foe spends a real Empty Step (a
Void teleport, 20 feet, 1 CP) out of it, the table commits, and the fight is cold-reloaded from disk before any assertion.
The Source Save DC is set by the owner's sheet (``dc``): 1 always passes the save and 40 always fails it, so the outcome does
not depend on the dice.
"""
import pytest

from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, ALLY, fixture, candidate, settle, turn, reload

PIN = 'tianxia.talent.source.heaven_sealing_source_pin'
EMPTY_STEP = 'TAL_VOID_EMPTY_STEP'
CENTRE = (6, 6)     # the Pin's 10-foot area is centred here; the foe starts on the centre
OUT = (5, 3)        # three squares from the centre: outside the 10-foot radius, and a square Empty Step reaches
ALLY_START = (7, 6)
TELEPORT_TO_OUT = {'choice:needle.teleport_destination': 'cell:5,3'}  # Empty Step's destination prompt, answered with OUT


def _pin_fixture(tmp_path, dc, *, foe_kit_teleport=True, modes=None, owner_teleport=False,
                 bundle_transform=None, altitude=0, foe_at=CENTRE, owner_at=None):
    foe = sheet([EMPTY_STEP] if foe_kit_teleport else [], cl=15)
    combat, table, mid = fixture(tmp_path, [PIN, *([EMPTY_STEP] if owner_teleport else [])], dc=dc, foe_sheet=foe,
                                 modes=modes, positions={OWNER: {'x': owner_at[0] if owner_at else 5 if owner_teleport else 3,
                                                                'y': owner_at[1] if owner_at else 6}, ALLY: {'x': ALLY_START[0], 'y': ALLY_START[1]},
                                                         FOE: {'x': foe_at[0], 'y': foe_at[1], 'z': altitude}},
                                 ally_talents=(), bundle_transform=bundle_transform)
    settle(table, mid, candidate(combat, mid, 'Heaven-Sealing Source Pin', at=CENTRE).candidate_id)
    return combat, table, mid


def _foe_position(engine):
    return (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y)


def _pin_zones(engine):
    return [z for z in engine.state.zones.values() if z.active and z.owner_id == OWNER
            and engine.action_catalog[z.source_definition_id].parameters['typed']['source'] == PIN]


@pytest.mark.parametrize('dc, passes', [(40, False), (1, True)], ids=['failed-save', 'passed-save'])
def test_foe_teleporting_out_of_the_pin_makes_its_constitution_save_first(tmp_path, dc, passes):
    combat, table, mid = _pin_fixture(tmp_path, dc)
    before = reload(tmp_path, mid)
    assert _pin_zones(before), 'the Pin is a live zone on the map before the teleport'
    turn(table, mid, FOE)
    action = candidate(combat, mid, 'Empty Step', target=FOE, at=OUT)
    before = reload(tmp_path, mid)
    definition = before.action_catalog[action.source_definition_id]
    settle(table, mid, action.candidate_id, TELEPORT_TO_OUT)
    after = reload(tmp_path, mid)
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
    assert len(saves) == 1, 'exactly one Constitution save, made before the teleport resolves'
    save = saves[0]
    assert save.source_definition_id == _pin_zones(before)[0].source_definition_id
    assert save.payload['dc'] == dc and save.payload['success'] is passes
    assert save.payload['reason'].endswith(':CON')
    for resource, amount in definition.costs:
        assert after.state.actors[FOE].resources[resource] == before.state.actors[FOE].resources[resource] - amount
    slot = {'ACTION': 'action_available', 'BONUS_ACTION': 'bonus_action_available'}[definition.economy]
    assert not getattr(after.state.actors[FOE], slot)
    movement = [e for e in after.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE]
    if passes:
        assert save.sequence < movement[-1].sequence
    else:
        assert not movement
    assert _foe_position(after) == (OUT if passes else CENTRE)


@pytest.mark.parametrize('hold', [False, True])
def test_owner_can_choose_whether_its_own_pin_holds_it(tmp_path, hold):
    combat, table, mid = _pin_fixture(tmp_path, 40, owner_teleport=True)
    prompts = settle(table, mid, candidate(combat, mid, 'Empty Step', target=OWNER, at=OUT).candidate_id,
                     {**TELEPORT_TO_OUT, 'choice:needle.source_pin': 'hold' if hold else None})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.source_pin' for p in prompts)
    assert bool([e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]) is hold
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == ((5, 6) if hold else OUT)


def test_no_pin_no_save(tmp_path):
    combat, table, mid = fixture(tmp_path, [], foe_sheet=sheet([EMPTY_STEP], cl=15), foe_position={'x': CENTRE[0], 'y': CENTRE[1]})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Empty Step', target=FOE, at=OUT).candidate_id, TELEPORT_TO_OUT)
    after = reload(tmp_path, mid)
    assert not [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE]
    assert _foe_position(after) == OUT


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('hold', [False, True])
def test_manual_owner_chooses_enemy_on_player_and_ai_turns(tmp_path, ai_turn, hold):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.test_r9i_karma_persistence import act

    combat, table, mid = _pin_fixture(tmp_path, 40)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Empty Step', target=FOE, at=OUT).candidate_id
    if ai_turn:
        real = combat.controller

        class BoundPrimary:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = BoundPrimary()
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    answers, pin_prompts = [], []
    for _ in range(8):
        result = table.auto_step(mid, 0, answers) if ai_turn else act(table, mid, cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        context = p['context']
        if context['reaction_source_id'] == 'choice:needle.source_pin':
            pin_prompts.append(p)
            assert context['reactor_id'] == OWNER
            assert 'Heaven-Sealing Source Pin' in p['moment'] and 'Empty Step' in p['moment']
            assert 'fails' in p['moment'] and 'spent' in p['moment']
            assert reload(tmp_path, mid).state.model_dump(mode='json') == before
            answers.append({**context, 'selection': 'USE' if hold else 'DECLINE',
                            **({'option_ids': ['hold']} if hold else {})})
        else:
            assert context['reaction_source_id'] == 'choice:needle.teleport_destination'
            answers.append({**context, 'selection': 'USE', 'option_ids': ['cell:5,3']})
    else:
        pytest.fail('teleport did not commit')
    after = reload(tmp_path, mid)
    assert len(pin_prompts) == 1
    assert len(_saves(after)) == int(hold)
    assert _foe_position(after) == (CENTRE if hold else OUT)


def _saves(engine):
    return [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE
            and engine.action_catalog[e.source_definition_id].parameters.get('typed', {}).get('source') == PIN]


def _landing_driver(monkeypatch, *, flying=False):
    """Sealed scenario actions exercise generic landing gates through table/session commits.

    Only the test effect supplies a requested 3D landing: the production player picker
    currently offers 2D cells. No engine function is replaced; teleport_subject is the real
    interpreter seam used by self and granted teleports, including its save/choice hooks.
    """
    from combat import ext
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import Position
    from combat.typed_executor import teleport_subject

    def land(ctx, row):
        teleport_subject(ctx, ctx.target, Position(**row['landing']))

    monkeypatch.setitem(ext.effects(), 'test_pin_landing', land)

    def transform(bundles):
        for bundle in bundles:
            if flying:
                bundle['actor_template'].update(fly_speed_ft=30, hover=True)
            for name, landing in [('Test granted departure', {'x': 5, 'y': 3}),
                                  ('Test granted return', {'x': 6, 'y': 6}),
                                  ('Test edge departure', {'x': 0, 'y': 3}),
                                  ('Test edge overlap', {'x': 3, 'y': 5}),
                                  ('Test vertical departure', {'x': 6, 'y': 6, 'z': 1})]:
                source = f"action:test.pin.{bundle['actor_id']}.{name.replace(' ', '_')}"
                bundle['action_catalog'].append({
                    'source_definition_id': source, 'display_name': name, 'owner_id': bundle['actor_id'],
                    'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
                    'range_ft': 60, 'costs': [['resource:core.qi', 1]],
                    'parameters': {'typed': {'source': 'test:pin.landing', 'effects': [
                        {'type': 'test_pin_landing', 'applies_to': 'target', 'landing': landing}]}}})
                bundle['actor_template']['action_ids'].append(source)
            source = f"action:test.pin.{bundle['actor_id']}.concentration"
            bundle['action_catalog'].append({
                'source_definition_id': source, 'display_name': 'Test incapacitation',
                'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
                'target_kind': 'SELF', 'range_ft': 0, 'costs': [],
                'parameters': {'typed': {'source': 'test:pin.incapacitation',
                    'effects': [{'type': 'condition', 'condition': 'incapacitated', 'applies_to': 'self',
                                 'duration': {'kind': 'minutes', 'amount': 1}}]}}})
            bundle['actor_template']['action_ids'].append(source)
            source = f"action:test.pin.{bundle['actor_id']}.blind"
            bundle['action_catalog'].append({
                'source_definition_id': source, 'display_name': 'Test blindness',
                'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
                'target_kind': 'SELF', 'range_ft': 0, 'costs': [],
                'parameters': {'typed': {'source': 'test:pin.blindness', 'effects': [
                    {'type': 'condition', 'condition': 'blinded', 'applies_to': 'self',
                     'duration': {'kind': 'minutes', 'amount': 1}}]}}})
            bundle['actor_template']['action_ids'].append(source)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    return transform


def _granted(combat, table, mid, name, *, hold=True, subject=FOE):
    prompts = settle(table, mid, candidate(combat, mid, name, target=subject).candidate_id,
                     {'choice:needle.source_pin': 'hold' if hold else None})
    return [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.source_pin']


@pytest.mark.parametrize('departure,dc,hold', [
    (True, 40, True), (True, 1, True), (True, 40, False),
    (False, 40, True), (False, 1, True),
], ids=['edge-failed-save', 'edge-passed-save', 'edge-owner-declines',
        'destination-still-overlaps-fail-dc', 'destination-still-overlaps-pass-dc'])
def test_large_creature_pin_membership_uses_occupied_surface_cells(tmp_path, monkeypatch, departure, dc, hold):
    from combat.canonical import canonical_sha256

    driver = _landing_driver(monkeypatch)

    def large_foe(bundles):
        driver(bundles)
        for bundle in bundles:
            if bundle['actor_id'] == FOE:
                source = 'action:test.pin.grow'
                bundle['action_catalog'].append({
                    'source_definition_id': source, 'display_name': 'Test Large footprint',
                    'owner_id': FOE, 'economy': 'NONE', 'resolution_kind': 'TYPED',
                    'target_kind': 'SELF', 'range_ft': 0, 'costs': [],
                    'parameters': {'typed': {'source': 'test:pin.grow', 'effects': [
                        {'type': 'size_change', 'size': 'Large',
                         'duration': {'kind': 'minutes', 'amount': 1}}]}}})
                bundle['actor_template']['action_ids'].append(source)
                bundle.pop('bundle_sha256')
                bundle['bundle_sha256'] = canonical_sha256(bundle)

    edge = (3, 5)  # anchor outside; its occupied (4, 6) square touches the Pin
    start, destination = (edge, (0, 3)) if departure else ((5, 5), edge)
    combat, table, mid = _pin_fixture(tmp_path, dc, foe_at=start, owner_at=(1, 6), bundle_transform=large_foe)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test Large footprint', target=FOE).candidate_id)
    before = reload(tmp_path, mid)
    actor = before.state.actors[FOE]
    assert _foe_position(before) == start
    assert before._footprint(actor).width_cells == before._footprint(actor).height_cells == 2
    cells = {(c.x, c.y) for c in _pin_zones(before)[0].affected_cells}
    assert edge not in cells
    assert (start in cells) is not departure
    assert cells.intersection(before._actor_cells(actor))
    from combat.gate2_runtime_models import Position
    assert bool(cells.intersection(before._actor_cells(actor, Position(x=destination[0], y=destination[1])))) is not departure
    name = 'Test edge departure' if departure else 'Test edge overlap'
    prompts = _granted(combat, table, mid, name, hold=hold)
    after = reload(tmp_path, mid)
    saves = _saves(after)
    assert len(prompts) == int(departure), 'only complete departure asks the Pin owner'
    assert len(saves) == int(departure and hold)
    if saves:
        assert saves[0].payload['dc'] == dc
        assert saves[0].payload['reason'].endswith(':CON')
        assert saves[0].payload['success'] is (dc == 1)
    assert after.state.actors[FOE].resources['resource:core.qi'] == actor.resources['resource:core.qi'] - 1
    assert _foe_position(after) == (start if departure and hold and dc == 40 else destination)
    assert after._footprint(after.state.actors[FOE]).width_cells == 2


@pytest.mark.parametrize('subject', [FOE, ALLY])
@pytest.mark.parametrize('owner_ai', [False, True])
def test_owner_choice_includes_allies_and_ai_uses_enemy_preference(tmp_path, monkeypatch, subject, owner_ai):
    combat, table, mid = _pin_fixture(tmp_path, 40, bundle_transform=_landing_driver(monkeypatch))
    if owner_ai:
        turn(table, mid, ALLY)  # manual primary; the Pin's AI owner chooses the recipient automatically
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = _granted(combat, table, mid, 'Test granted departure', subject=subject)
    after = reload(tmp_path, mid)
    held = not owner_ai or subject == FOE
    assert len(prompts) == (0 if owner_ai else 1)
    assert len([e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == subject]) == int(held)
    start = CENTRE if subject == FOE else ALLY_START
    actor = after.state.actors[subject]
    assert (actor.position.x, actor.position.y) == (start if held else OUT)


def test_ai_owner_does_not_choose_enemy_it_cannot_perceive(tmp_path, monkeypatch):
    from combat import senses
    combat, table, mid = _pin_fixture(tmp_path, 40, bundle_transform=_landing_driver(monkeypatch))
    settle(table, mid, candidate(combat, mid, 'Test blindness', target=OWNER).candidate_id)
    before = reload(tmp_path, mid)
    assert not senses.perceives(before, before.state.actors[OWNER], before.state.actors[FOE])
    turn(table, mid, ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    assert not _granted(combat, table, mid, 'Test granted departure')
    after = reload(tmp_path, mid)
    assert not _saves(after) and _foe_position(after) == OUT


@pytest.mark.parametrize('airborne', [False, True])
def test_surface_contact_and_vertical_departure_through_committed_landing(tmp_path, monkeypatch, airborne):
    combat, table, mid = _pin_fixture(tmp_path, 40, altitude=1 if airborne else 0,
                                    bundle_transform=_landing_driver(monkeypatch, flying=True))
    turn(table, mid, FOE)
    _granted(combat, table, mid, 'Test granted departure' if airborne else 'Test vertical departure')
    after = reload(tmp_path, mid)
    assert len(_saves(after)) == (0 if airborne else 1)
    assert _foe_position(after) == (OUT if airborne else CENTRE)
    assert after.state.actors[FOE].position.z == 0


def test_save_limit_is_current_fight_turn_and_survives_reload(tmp_path, monkeypatch):
    combat, table, mid = _pin_fixture(tmp_path, 40, bundle_transform=_landing_driver(monkeypatch))
    turn(table, mid, FOE)
    _granted(combat, table, mid, 'Test granted departure')
    first = reload(tmp_path, mid)
    assert len(_saves(first)) == 1 and _foe_position(first) == CENTRE
    flag = next(v for k, v in first.state.actors[FOE].turn_flags.items() if k.startswith('source_pin_saved|'))
    assert isinstance(flag, str), 'the committed use marker must be JSON-safe'
    # A new service/session reads the committed flag before a second accepted use.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert not _granted(combat, table, mid, 'Test granted departure')
    second = reload(tmp_path, mid)
    assert len(_saves(second)) == 1 and _foe_position(second) == OUT
    _granted(combat, table, mid, 'Test granted return')
    reload(tmp_path, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] != FOE
    _granted(combat, table, mid, 'Test granted departure')
    after = reload(tmp_path, mid)
    assert len(_saves(after)) == 2 and _foe_position(after) == CENTRE


@pytest.mark.parametrize('end', ['expiry', 'concentration'])
def test_pin_stops_gating_when_its_zone_ends(tmp_path, monkeypatch, end):
    combat, table, mid = _pin_fixture(tmp_path, 40, bundle_transform=_landing_driver(monkeypatch))
    before = reload(tmp_path, mid)
    zone_id = _pin_zones(before)[0].zone_id
    if end == 'concentration':
        settle(table, mid, candidate(combat, mid, 'Test incapacitation', target=OWNER).candidate_id)
    else:
        for _ in range(36):
            if not _pin_zones(reload(tmp_path, mid)):
                break
            settle(table, mid, table.state(mid)['menu']['end_turn'])
        assert reload(tmp_path, mid).state.round_number >= before.state.round_number + 10
    after = reload(tmp_path, mid)
    assert not _pin_zones(after)
    if end == 'concentration':
        assert after.state.actors[OWNER].concentration is None
        assert any(e.event_type == 'CONCENTRATION_ENDED' and e.actor_id == OWNER for e in after.events)
    assert any(e.event_type == 'ZONE_REMOVED' and e.payload['zone_id'] == zone_id for e in after.events)
    turn(table, mid, FOE)
    assert not _granted(combat, table, mid, 'Test granted departure')
    final = reload(tmp_path, mid)
    assert not _saves(final) and _foe_position(final) == OUT
