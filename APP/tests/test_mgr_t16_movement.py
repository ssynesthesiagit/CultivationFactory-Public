"""Selected Smoke, Air and Red Thread outcomes through table transactions."""
import pytest
from combat import ext, senses
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.ext import smoke_mirror as M, air_lifts as A
from combat.ext.air_delivery import DELIVERY, routes
from combat.ext.hit_dice import PREFIX
from combat.ext.fate_riders import RED_THREAD
from tests import worker2_support as S
from tests.cw2_service_support import add_action, seal
from tests.mgr_t16_support import automatic

VEIL = 'SMOKE_BASE_SMOKE_VEIL'
SOOT = 'TAL_SMOKE_SOOT_MARKED_WITNESS'


@pytest.fixture(autouse=True)
def setups(monkeypatch):
    def scene(ctx, row):
        foe = ctx.engine.state.actors[S.FOE]
        if row.get('invisible'):
            ctx.engine._apply_condition(foe, 'condition:typed.invisible', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED')
        if row.get('hidden'):
            ctx.engine._apply_condition(foe, 'condition:typed.hidden', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'stealth_total': 100, 'support_causes': row['hidden']})
        if row.get('object'):
            obj = RuntimeObjectState(object_id='object:test.wind_script', object_kind='talisman',
                position=Position(x=5, y=6), unattended=True, flammable=False,
                component={'size': 'Tiny', 'prepared_by': S.OWNER, 'name': 'Prepared paper talisman', 'activated': 0})
            ctx.engine._update_object(obj, ctx.source, ctx.actor.entity_id)
        if row.get('fly'):
            ctx.engine._apply_condition(foe, 'condition:test.flight', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'fly_speed_ft': 40, 'flight_hover': 1})
            from combat.falling import displace
            displace(ctx.engine, foe, 1, ctx.source, intent=ctx.intent)
        if row.get('airless'):
            ctx.engine._apply_condition(ctx.actor, 'condition:test.airless', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'airless': 1, 'created_air': int(bool(row.get('created_air')))})
        if row.get('end'):
            ctx.engine._end_concentration(ctx.actor, 'PLAYER_ENDS_CONCENTRATION')
        if row.get('currents'):
            from combat import zones
            from combat.typed_executor import Context
            action = next(a for a in ctx.engine.action_catalog.values() if a.owner_id == S.OWNER
                          and (a.parameters.get('typed') or {}).get('source') == 'AIR_BASE_GATHER_CURRENT')
            for _ in range(row['currents']):
                sub = Context(ctx.engine, ctx.actor, action, ctx.intent, action.parameters['typed'], [], None, {})
                # Preserve compiled Air provenance; appearance alone never
                # classifies an area as a Current.
                zones.create(sub, action.parameters['typed']['zone_spec'])
    monkeypatch.setitem(ext._EFFECTS, 'test_mgr_t16_movement_scene', scene)


def fixture(tmp_path, talents, *, hit_dice=False, **scene):
    def transform(bundles):
        add_action(bundles[0], 'Scene event', [{'type': 'test_mgr_t16_movement_scene', **scene}], target='SELF')
        add_action(bundles[0], 'End current', [{'type': 'test_mgr_t16_movement_scene', 'end': True}], target='SELF')
        if hit_dice:
            bundles[1]['actor_template']['resources'].append({'resource_id': PREFIX + '8', 'initial': 2, 'maximum': 2})
            seal(bundles[1])
    return S.fixture(tmp_path, talents, cl=17, dc=100, bundle_transform=transform)


def use(c, t, mid, name, *, target=None, at=None, **kw):
    return S.settle(t, mid, S.candidate(c, mid, name, target=target, at=at).candidate_id, **kw)


def test_mirror_trace_after_invisibility_does_not_spend_ordinary_allowance(tmp_path):
    c, t, mid = fixture(tmp_path, [M.MIRROR, VEIL], invisible=True)
    use(c, t, mid, 'Smoke Veil', at=(6, 6))
    prompts = use(c, t, mid, 'Scene event', picks={'choice:needle.smoke_mirror': 'trace'})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.smoke_mirror' for p in prompts)
    e = S.reload(tmp_path, mid)
    from combat.typed_executor import bears_mark
    assert bears_mark(e.state.actors[S.FOE], S.OWNER, 'Smoke Trace')
    assert any(c.condition_id == M.MIRROR_TRACE for c in e.state.actors[S.FOE].conditions.values())


def test_mirror_automatic_owner_places_observed_event_trace_without_prompt(tmp_path):
    def transform(bundles):
        add_action(bundles[0], 'Invisibility event', [{'type': 'test_mgr_t16_movement_scene', 'invisible': True}], target='SELF')
        action = next(a for a in bundles[0]['action_catalog'] if a['display_name'] == 'Invisibility event')
        action['parameters']['player_only'] = False
        seal(bundles[0])
    c, t, mid = S.fixture(tmp_path, [M.MIRROR, VEIL], cl=17, bundle_transform=transform)
    use(c, t, mid, 'Smoke Veil', at=(6, 6))
    prompts = automatic(c, t, mid, S.OWNER, 'Invisibility event')
    e = S.reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.smoke_mirror' for p in prompts)
    assert any(q.condition_id == M.MIRROR_TRACE for q in e.state.actors[S.FOE].conditions.values())


def test_mirror_direction_bound_to_exact_trace_end(tmp_path):
    c, t, mid = fixture(tmp_path, [M.MIRROR, SOOT, VEIL], hidden=['smoke'])
    use(c, t, mid, 'Smoke Veil', at=(6, 6))
    use(c, t, mid, 'Scene event', picks={'choice:needle.smoke_mirror': 'trace'})
    e = S.reload(tmp_path, mid)
    assert any(r.get('ability') == 'Smoke Mirror Trail' for r in senses.perception(e, e.state.actors[S.OWNER]).get('information', []))
    # A real spend ends that specific trace; the location exception is personal.
    use(c, t, mid, 'Soot-Marked Witness', target=S.FOE)
    e = S.reload(tmp_path, mid)
    assert not any(r.get('ability') == 'Smoke Mirror Trail' for r in senses.perception(e, e.state.actors[S.OWNER]).get('information', []))
    assert senses.pinpoints(e, e.state.actors[S.OWNER], e.state.actors[S.FOE])
    assert not senses.pinpoints(e, e.state.actors[S.ALLY], e.state.actors[S.FOE])


@pytest.mark.parametrize('causes,known', [(['smoke'], True), (['smoke', 'cover'], False), ([], False)])
def test_soot_only_listed_concealment_support_not_global_reveal(tmp_path, causes, known):
    c, t, mid = fixture(tmp_path, [SOOT, VEIL], hidden=causes or ['unknown'])
    use(c, t, mid, 'Place Smoke Trace', target=S.FOE)
    use(c, t, mid, 'Scene event')
    use(c, t, mid, 'Soot-Marked Witness', target=S.FOE)
    e = S.reload(tmp_path, mid)
    assert senses.pinpoints(e, e.state.actors[S.OWNER], e.state.actors[S.FOE]) is known
    assert any(q.condition_id == 'condition:typed.hidden' for q in e.state.actors[S.FOE].conditions.values())


@pytest.mark.parametrize('ai', [False, True])
def test_red_thread_bearer_hit_die_payment_temp_hp_and_release(tmp_path, monkeypatch, ai):
    from combat.ext import red_thread_release
    native = red_thread_release.ask

    def choose(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == 'choice:needle.red_thread_ally':
            # Keep this payment case aimed at the visible other ally now that
            # choosing the bearer is also legal; retain the full native pool.
            assert S.OWNER in options
            kwargs['preferred'] = [S.OWNER]
        return native(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)

    monkeypatch.setattr(red_thread_release, 'ask', choose)
    c, t, mid = fixture(tmp_path, [RED_THREAD], hit_dice=True)
    use(c, t, mid, 'Red Thread Auspice', target=S.ALLY)
    S.turn(t, mid, S.ALLY)
    prompts = automatic(c, t, mid, S.ALLY, 'Red Thread Auspice: Release') if ai else use(c, t, mid, 'Red Thread Auspice: Release',
        picks={'choice:needle.red_thread_ally': S.OWNER, 'choice:needle.red_thread_die': PREFIX + '8'})
    e = S.reload(tmp_path, mid)
    assert e.state.actors[S.ALLY].resources[PREFIX + '8'] == 1
    assert e.state.actors[S.OWNER].temporary_hp > 0
    assert not any(q.data.get('auspice') == 'red_thread' for q in e.state.actors[S.ALLY].conditions.values())
    assert any(p['context']['reaction_source_id'] == 'choice:needle.red_thread_die' for p in prompts) is (not ai)


@pytest.mark.parametrize('ai', [False, True])
def test_wind_script_chooses_object_and_destination_without_activation(tmp_path, ai):
    c, t, mid = fixture(tmp_path, [DELIVERY, 'AIR_BASE_GATHER_CURRENT'], object=True)
    use(c, t, mid, 'Scene event')
    prompts = automatic(c, t, mid, S.OWNER, 'Gather Current: Carry', at=(5, 6)) if ai else use(c, t, mid, 'Gather Current: Carry', at=(5, 6),
        picks={'choice:needle.wind_script_object': 'object:test.wind_script', 'choice:needle.wind_script_destination': 'cell:6,6,0'})
    e = S.reload(tmp_path, mid)
    obj = e.state.objects['object:test.wind_script']
    assert obj.position != Position(x=5, y=6) and obj.component['activated'] == 0
    assert any(p['context']['reaction_source_id'] == 'choice:needle.wind_script_destination' for p in prompts) is (not ai)


def test_updraft_start_save_lifts_suspends_and_keeps_finite_volume(tmp_path):
    c, t, mid = fixture(tmp_path, [A.UPDRAFT])
    use(c, t, mid, 'Updraft Gate', at=(6, 6))
    for _ in range(4):
        if t.state(mid)['menu']['actor_id'] == S.FOE:
            break
        S.settle(t, mid, t.state(mid)['menu']['end_turn'],
                 picks={'choice:needle.updraft_consent': 'resist'})
    e = S.reload(tmp_path, mid)
    foe = e.state.actors[S.FOE]
    assert foe.position.z == 2
    assert any(q.condition_id == A.SUSPENDED for q in foe.conditions.values())
    zone = next(z for z in e.state.zones.values() if z.active)
    from combat.spatial_areas import zone_contains
    assert not zone_contains(e, foe.model_copy(update={'position': Position(x=6, y=6, z=7)}), zone)


def test_sky_sovereign_hostile_flight_halved_after_start_save(tmp_path):
    c, t, mid = fixture(tmp_path, [A.SKY], fly=True)
    use(c, t, mid, 'Scene event')
    use(c, t, mid, 'Sky-Sovereign Incarnation')
    S.turn(t, mid, S.FOE)
    e = S.reload(tmp_path, mid)
    from combat.flight import profile
    assert profile(e, e.state.actors[S.FOE]).speed_ft == 20
    assert profile(e, e.state.actors[S.OWNER]).speed_ft == 60


@pytest.mark.parametrize('created_air', [False, True])
def test_sky_sovereign_vacuum_requires_created_air(tmp_path, created_air):
    c, t, mid = fixture(tmp_path, [A.SKY], airless=True, created_air=created_air)
    use(c, t, mid, 'Sky-Sovereign Incarnation')
    use(c, t, mid, 'Scene event')
    e = S.reload(tmp_path, mid)
    from combat.flight import profile
    from combat.ext.states import active
    assert bool(active(e, e.state.actors[S.OWNER], 'sky_sovereign_incarnation')) is created_air
    assert profile(e, e.state.actors[S.OWNER]).speed_ft == (60 if created_air else 0)


def test_updraft_concentration_end_after_reload_removes_hold_and_falls(tmp_path):
    c, t, mid = fixture(tmp_path, [A.UPDRAFT])
    use(c, t, mid, 'Updraft Gate', at=(6, 6))
    for _ in range(4):
        if t.state(mid)['menu']['actor_id'] == S.FOE:
            break
        S.settle(t, mid, t.state(mid)['menu']['end_turn'],
                 picks={'choice:needle.updraft_consent': 'resist'})
    e = S.reload(tmp_path, mid)
    assert e.state.actors[S.FOE].position.z == 2
    S.turn(t, mid, S.OWNER)
    use(c, t, mid, 'End current')
    e = S.reload(tmp_path, mid)
    assert not any(z.active for z in e.state.zones.values())
    assert e.state.actors[S.FOE].position.z == 0
    assert not any(q.condition_id == A.SUSPENDED for q in e.state.actors[S.FOE].conditions.values())


def test_sky_sovereign_exempts_six_currents_without_dropping_seventh(tmp_path):
    c, t, mid = fixture(tmp_path, [A.SKY, 'AIR_BASE_GATHER_CURRENT'], currents=7)
    use(c, t, mid, 'Sky-Sovereign Incarnation')
    use(c, t, mid, 'Scene event')
    e = S.reload(tmp_path, mid)
    from combat.ext.air_currents import currents
    assert len(currents(e, e.state.actors[S.OWNER])) == 7
    assert sum(bool(z.trigger_profile.get('sky_control_exempt')) for z in currents(e, e.state.actors[S.OWNER])) == 6
    assert A.air_control_count(e, e.state.actors[S.OWNER]) == 1
