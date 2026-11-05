"""Sure Grip's assigned climb/fall/catch rows through real table commits."""
import pytest
from combat import ext, falling
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield, battlefield_as_map
from tests.auto8f1_table_support import fixture, OWNER, FOE, SECOND, ARENA, candidate_id, move_candidate_id, reload_identical
from tests.test_a2_athletics_second_pass import add_action

GRIP = 'TAL_ATHLETICS_SURE_GRIP'


@ext.effect('test_t16_launch')
def launch(ctx, eff):
    subject = ctx.engine.state.actors[eff['subject']]
    falling.displace(ctx.engine, subject, 1, ctx.source, intent=ctx.intent)


def game(tmp_path, monkeypatch, *, dc=0, owned=True, flying=False, plain_wall=False):
    document = normalize_map({'display_name': 'Explicit catch difficulty yard', 'width_squares': 18,
        'height_squares': 12, 'walls': [{'shape': 'rect', 'points': [[6, 3], [11, 9]], 'filled': False}],
        'roofs': {'height_ft': 15, 'climb_check': 'slippery', **({'enabled': False} if plain_wall else {}), **({'catch_dc': dc} if dc is not None else {})},
        **({'catch_dc': dc} if dc is not None else {})})
    arena = to_battlefield(document)
    original = CombatService.factory_arenas
    def arenas(self, **kwargs):
        return {**original(self, **kwargs), ARENA: arena}
    monkeypatch.setattr(CombatService, 'factory_arenas', arenas)
    def prepare(bs):
        for b in bs:
            if b['actor_id'] == FOE:
                add_action(b, 'Trigger other creature fall', [{'type': 'test_t16_launch', 'subject': OWNER}])
            if b['actor_id'] == OWNER:
                b.setdefault('skills', {})['Athletics'] = 100
                if flying:
                    b['actor_template']['fly_speed_ft'] = 30
                for name, subject in [('Self fall', OWNER), ('Creature fall', FOE), ('Far creature fall', SECOND)]:
                    add_action(b, name, [{'type': 'test_t16_launch', 'subject': subject}])
                add_action(b, 'Wait without spending an Action', [])
    return fixture(tmp_path, [GRIP] if owned else [], seed='T16-GRIP-'+tmp_path.name,
        bundle_transform=prepare, places={OWNER: {'x': 5, 'y': 6}, FOE: {'x': 4, 'y': 6}, SECOND: {'x': 2, 'y': 6}})


def commit(g, name, chooser=None):
    g['commit'](candidate_id(g['menu'](), name), chooser)
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_native_climb_check_advantage_already_automated_on_current_main(tmp_path, monkeypatch):
    g = game(tmp_path, monkeypatch)
    move = next(row for row in g['menu']()['moves'] if row['destination'] == {'x': 5, 'y': 6, 'z': 1})
    g['commit'](move['candidate_id'])
    checks = [e for e in g['stored_engine']().events if e.event_type == 'CHECK_ROLLED']
    assert checks[-1].payload['actor']['mode'] == 'ADVANTAGE'
    reload_identical(g['combat'], g['match_id'], g['userdata'])


@pytest.mark.parametrize('name,target', [('Self fall', OWNER), ('Creature fall', FOE)])
def test_reaction_catches_one_selected_creature_and_prevent_fall_advantage_reloads(tmp_path, monkeypatch, name, target):
    g = game(tmp_path, monkeypatch)
    prompts = []
    def choose(p, c):
        prompts.append(c)
        return [next(o['id'] for o in c['options'] if o['id'].startswith(target+'|'))]
    commit(g, name, choose)
    engine = g['stored_engine']()
    actor = engine.state.actors[target]
    assert actor.position.z == 1
    assert any(c.condition_id == 'condition:typed.sure_grip_caught' for c in actor.conditions.values())
    assert not engine.state.actors[OWNER].reaction_available
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.source_definition_id == GRIP]
    assert len(checks) == 1 and checks[0].payload['actor']['mode'] == 'ADVANTAGE'
    assert prompts and all('Athletics DC 0' in o['label'] for o in prompts[0]['options'])
    commit(g, 'Wait without spending an Action')
    assert g['stored_engine']().state.actors[target].position.z == 1


@pytest.mark.parametrize('dc,decline,owned', [(1000, False, True), (0, True, True), (0, False, False), (None, False, True)])
def test_failure_decline_nonowner_and_unadjudicated_dc_do_not_stop_falling(tmp_path, monkeypatch, dc, decline, owned):
    g = game(tmp_path, monkeypatch, dc=dc, owned=owned)
    commit(g, 'Self fall', (lambda p,c: []) if decline else None)
    assert g['reload_owner']().position.z == 0
    assert g['reload_owner']().reaction_available is (decline or not owned or dc is None)


def test_catch_creature_support_ends_when_anchor_moves_out_of_reach(tmp_path, monkeypatch):
    g = game(tmp_path, monkeypatch)
    commit(g, 'Creature fall')
    g['commit'](move_candidate_id(g['menu'](), 7, 1))
    engine = g['stored_engine']()
    assert engine.state.actors[FOE].position.z == 0
    assert not any(c.condition_id == 'condition:typed.sure_grip_caught' for c in engine.state.actors[FOE].conditions.values())
    reload_identical(g['combat'], g['match_id'], g['userdata'])


def test_catch_does_not_offer_outside_natural_reach(tmp_path, monkeypatch):
    g = game(tmp_path, monkeypatch)
    called = []
    commit(g, 'Far creature fall', lambda p,c: called.append(c) or [])
    assert not called and g['reload_owner']().reaction_available
    assert g['stored_engine']().state.actors[SECOND].position.z == 0


def test_scene_and_surface_catch_dc_roundtrip_without_invented_default():
    document = normalize_map({'width_squares': 12, 'height_squares': 12,
        'walls': [{'shape': 'rect', 'points': [[4, 3], [8, 8]], 'filled': False}],
        'catch_dc': 12, 'roofs': {'height_ft': 15, 'catch_dc': 14}})
    arena = to_battlefield(document)
    assert arena['catch_dc'] == 12 and arena['roof_surfaces'][0]['catch_dc'] == 14
    assert battlefield_as_map(arena)['catch_dc'] == 12
    assert battlefield_as_map(arena)['roofs']['catch_dc'] == 14


def test_ai_catcher_decides_without_manual_prompt(tmp_path, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.worker2_support import settle
    g = game(tmp_path, monkeypatch)
    combat = g['combat']
    cid = candidate_id(g['menu'](), 'Self fall')
    combat.set_controller_mode(g['match_id'], actor_id=OWNER, controller_mode='LOCAL_AUTO')
    real = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: real.choose_reaction(context).decision)
    assert not settle(g['table'], g['match_id'], cid, choices={}, auto=True)
    assert g['reload_owner']().position.z == 1
    reload_identical(combat, g['match_id'], g['userdata'])


def test_flying_catcher_is_a_native_stable_anchor(tmp_path, monkeypatch):
    g = game(tmp_path, monkeypatch, flying=True)
    commit(g, 'Self fall')  # A flyer stays aloft without needing a catch.
    assert g['reload_owner']().position.z == 1 and g['reload_owner']().reaction_available
    commit(g, 'Creature fall')
    assert g['stored_engine']().state.actors[FOE].position.z == 1
    assert not g['reload_owner']().reaction_available


def test_manual_catcher_is_asked_on_an_ai_actors_turn(tmp_path, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.worker2_support import settle, prompt_turn
    g = game(tmp_path, monkeypatch)
    combat = g['combat']
    prompt_turn(g['table'], g['match_id'], FOE)
    cid = candidate_id(g['menu'](), 'Trigger other creature fall')
    combat.set_controller_mode(g['match_id'], actor_id=FOE, controller_mode='LOCAL_AUTO')
    real = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: real.choose_reaction(context).decision)
    prompts = settle(g['table'], g['match_id'], cid,
        choices={'choice:needle.athletics.sure_grip_catch': 'first'}, auto=True)
    assert prompts and prompts[0]['context']['reactor_id'] == OWNER
    assert g['reload_owner']().position.z == 1
    reload_identical(combat, g['match_id'], g['userdata'])


def test_self_catch_uses_declared_solid_support_without_roof_metadata(tmp_path, monkeypatch):
    g = game(tmp_path, monkeypatch, plain_wall=True)
    commit(g, 'Self fall')
    actor = g['reload_owner']()
    assert actor.position.z == 1
    assert any(c.data.get('surface_id', '').startswith('solid:') for c in actor.conditions.values())
