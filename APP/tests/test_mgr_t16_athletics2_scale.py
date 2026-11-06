"""Scale Foe Bonus Actions, player choices, carrying and Close Quarters cover."""
import pytest
from combat.gate2_runtime_models import CandidateKind
from tests.worker2_support import fixture, OWNER, ALLY, FOE, settle, turn, reload, candidate, sealed_native_attack
from tests.auto8f1_table_support import candidate_id, AXE_KIT, POLEARM_KIT
from combat.creature_attachment import carrier

SCALE = 'TAL_ATHLETICS_SCALE_FOE'
QUARTERS = 'TAL_ATHLETICS_CLOSE_QUARTERS_TRAINING'


def game(tmp_path, *, trained=False, size='Large', hit=False, owner_kit=None, host_fly=0, dislodge_success=False,
         friendly=False, outside_x=8, host_z=0, host_hover=False, battlefield_transform=None, owner_position=None,
         owner_fly=0):
    def prepare(bs):
        for b in bs:
            b['skills'] = {'Athletics': 100, 'Acrobatics': 100} if b['actor_id'] == OWNER else {'Athletics': -100, 'Acrobatics': -100}
            if b['actor_id'] == FOE:
                b['actor_template']['fly_speed_ft'] = host_fly
                b['actor_template']['hover'] = host_hover
                b['actor_template']['size_category'] = size
                b['actor_template']['armor_class'] = 1
                if dislodge_success:
                    b['skills']['Athletics'] = 200
                from tests.athletics_table_support import add_action
                add_action(b, 'Host teleport', [{'type': 'teleport', 'distance_ft': 15, 'applies_to': 'self'}])
                b['action_catalog'][-1]['target_kind'] = 'CELL'
                b['action_catalog'][-1]['range_ft'] = 15
                sealed_native_attack(b, 'Host attack', attack_bonus=20)
            elif b['actor_id'] == OWNER:
                b['actor_template']['armor_class'] = 1 if hit else 20
                b['actor_template'].update(fly_speed_ft=owner_fly, hover=bool(owner_fly))
            else:
                sealed_native_attack(b, 'Outside attack', attack_bonus=10)
    combat, table, mid = fixture(tmp_path, [SCALE] + ([QUARTERS] if trained else []), bundle_transform=prepare,
        owner_kit=owner_kit,
        positions={OWNER: owner_position or {'x': 3, 'y': 6}, FOE: {'x': 4, 'y': 6, 'z': host_z},
                   ALLY: {'x': outside_x, 'y': 6}},
        team_overrides={ALLY: 'team:opponents', **({FOE: 'team:factory'} if friendly else {})},
        battlefield_transform=battlefield_transform,
        seed='MGR-T16-SCALE-'+tmp_path.name, named=True)
    return combat, table, mid


def climb(table, mid, skill='athletics'):
    return settle(table, mid, candidate_id(table.state(mid)['menu'], 'climb onto a bigger creature'),
                  picks={'choice:needle.scale_check': skill})


@pytest.mark.parametrize('skill', ['athletics', 'acrobatics'])
def test_bonus_action_climb_check_and_contained_square_choice_cold_reload(tmp_path, skill):
    combat, table, mid = game(tmp_path)
    prompts = climb(table, mid, skill)
    assert any('Scale Foe' in str(p) and 'Mara' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    actor, host = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert carrier(engine, actor) is host
    assert actor.position == host.position
    assert not actor.bonus_action_available and actor.action_available
    assert actor.movement_remaining_ft == actor.speed_ft - 5
    rolls = [e for e in engine.events if e.event_type == 'CHECK_ROLLED']
    assert rolls[-1].payload['actor']['mode'] == 'NORMAL'


def test_scale_target_must_be_currently_bigger(tmp_path):
    combat, table, mid = game(tmp_path, size='Medium')
    assert not any('climb onto a bigger creature' in o['label'] for a in table.state(mid)['menu']['actions'] for o in a['options'])


def test_scale_ai_chooses_its_own_check_and_square_automatically(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = game(tmp_path)
    cid = candidate_id(table.state(mid)['menu'], 'climb onto a bigger creature')
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    original = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: original.choose_reaction(context).decision)
    prompts = settle(table, mid, cid, auto=True)
    assert not prompts
    engine = reload(tmp_path, mid)
    assert carrier(engine, engine.state.actors[OWNER]) is engine.state.actors[FOE]


def test_host_attacks_only_clinger_with_disadvantage_then_carries_it(tmp_path):
    combat, table, mid = game(tmp_path, hit=True)
    climb(table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Host attack', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
    assert rolls[-1].payload['mode'] == 'DISADVANTAGE'
    move = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind == CandidateKind.MOVE and
                c.destination and (c.destination.x, c.destination.y, c.destination.z) == (5, 6, 0))
    settle(table, mid, move.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position == engine.state.actors[FOE].position


def test_host_dislodging_check_is_normal_and_player_resists_on_host_turn(tmp_path):
    combat, table, mid = game(tmp_path)
    climb(table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate_id(table.state(mid)['menu'], 'Dislodge a creature'),
                     picks={'choice:needle.resist_dislodge': 'acrobatics'})
    assert any('Scale Foe' in str(p) and 'dislodge' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    row = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'][-1]
    assert row.payload['actor']['mode'] == row.payload['target']['mode'] == 'NORMAL'


def test_close_quarters_cover_redirects_same_attack_roll_to_host_and_reloads(tmp_path, monkeypatch):
    # The attacking die is pinned (the sibling sf3 table test pins it the same way) so the
    # miss is about the carrier's cover, not about which die the match seed happens to draw.
    from combat.gate2_rolls import DeterministicRollAuthority
    raw = DeterministicRollAuthority.raw_d20
    def roll(self, **kwargs):
        result = raw(self, **kwargs)
        if kwargs['actor_id'] == ALLY and kwargs['reason'].startswith('ATTACK:'):
            return result.model_copy(update={'natural_result': 12, 'dice': (12,), 'total': 22})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', roll)
    combat, table, mid = game(tmp_path, trained=True)
    climb(table, mid)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Outside attack', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY]
    assert len(rolls) == 1
    row = rolls[0]
    # Rolls retain their declared target; the post-correction receipt names the
    # actual recipient and preserves that roll id through damage and reload.
    assert row.target_ids == (OWNER,)
    transfer = next(e for e in engine.events if e.payload.get('attack_redirected'))
    assert transfer.payload['original_target_id'] == OWNER
    assert transfer.target_ids == (FOE,)
    assert transfer.payload['roll_id'] == row.payload['roll_id']
    assert engine.state.actors[OWNER].current_hp == engine.state.actors[OWNER].maximum_hp
    assert engine.state.actors[FOE].current_hp < engine.state.actors[FOE].maximum_hp


@pytest.mark.parametrize('kit,unarmed,expected', [(POLEARM_KIT, False, 'DISADVANTAGE'),
    (AXE_KIT, False, 'NORMAL'), (None, True, 'NORMAL')])
def test_close_quarters_clinging_weapon_penalty_and_printed_exemptions(tmp_path, kit, unarmed, expected):
    combat, table, mid = game(tmp_path, trained=True, owner_kit=kit)
    climb(table, mid)
    engine = combat._load_session(mid).engine
    def wanted(c):
        a = engine.action_catalog.get(c.source_definition_id)
        if not a or c.target_ids != (FOE,) or a.economy.value != 'ACTION':
            return False
        typed = a.parameters.get('typed', {})
        return (any(e.get('type') == 'attack' and e.get('attack_kind') == 'unarmed' for e in typed.get('effects', ()))
                if unarmed else any(e.get('type') == 'attack' for e in typed.get('effects', ()))
                and bool(typed.get('weapon')) and typed['weapon'].get('attack_delivery') == 'melee'
                and typed['weapon'].get('implement_id') == kit['starting_kit']['items'][0]['item_id'])
    c = next(c for c in engine.legal_candidates() if wanted(c))
    settle(table, mid, c.candidate_id)
    row = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER)
    assert row.payload['mode'] == expected


def test_clinging_stays_supported_when_host_ascends(tmp_path):
    combat, table, mid = game(tmp_path, host_fly=15)
    climb(table, mid)
    turn(table, mid, FOE)
    c = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.kind == CandidateKind.MOVE
             and c.destination and (c.destination.x, c.destination.y, c.destination.z) == (4, 6, 1)
             and c.metadata.get('movement_mode') == 'fly')
    settle(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position == engine.state.actors[FOE].position
    assert engine.state.actors[OWNER].position.z == 1
    assert carrier(engine, engine.state.actors[OWNER]) is engine.state.actors[FOE]


def test_self_teleport_leaves_clinger_in_its_original_square(tmp_path):
    combat, table, mid = game(tmp_path)
    climb(table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Host teleport', at=(6, 6)).candidate_id,
           picks={'choice:needle.teleport_destination': 'cell:6,6'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.x == 6
    assert engine.state.actors[OWNER].position.x == 4
    assert carrier(engine, engine.state.actors[OWNER]) is None


def test_successful_dislodge_physically_releases_clinger_and_reloads(tmp_path):
    combat, table, mid = game(tmp_path, dislodge_success=True)
    climb(table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate_id(table.state(mid)['menu'], 'Dislodge a creature'))
    engine = reload(tmp_path, mid)
    assert carrier(engine, engine.state.actors[OWNER]) is None
    assert engine.state.actors[OWNER].position != engine.state.actors[FOE].position


def test_scale_foe_menu_label_and_needle_ids_are_the_ones_a_fight_script_selects(tmp_path):
    # A behaviour-diff fight script picks the action by its printed menu label and
    # answers the needle by option id. If either is renamed the script can no longer
    # reach the record at all (MGR-T16 F9R finding 1: three Scale Foe scripts died at
    # step 1 because the label was invented, not printed).
    combat, table, mid = game(tmp_path)
    engine = combat._load_session(mid).engine
    names = {action.display_name for action in engine.action_catalog.values()}
    assert 'Scale Foe: climb onto a bigger creature' in names
    assert 'Dislodge a creature using Scale Foe' in names
    state = table.state(mid)
    menu = state['menu']
    cid = candidate_id(menu, 'climb onto a bigger creature')
    result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, [])
    assert result['status'] == 'REACTION_REQUIRED'
    ids = {option['id'] for option in result['reaction']['choice']['options']}
    assert ids == {'athletics', 'acrobatics'}


SHAFT_WALLS = [(x, y) for x in range(3, 7) for y in range(5, 9)
               if (x, y) not in {(4, 6), (5, 6), (4, 7), (5, 7)}]


def shaft(arena):
    # Large carrier at (4,6) hovers from 5 to 15 feet up inside a shaft whose
    # sides are walled over the same band: no horizontal exit at the clinging
    # creature's height, while the open air above the carrier stays clear.
    arena['terrain_regions'].append({'region_id': 'test.shaft.walls', 'terrain_type': 'BLOCKED',
        'movement_cost': 0, 'base_altitude_ft': 5, 'height_ft': 10,
        'cells': [{'x': x, 'y': y} for x, y in SHAFT_WALLS]})


def test_successful_dislodge_leaves_through_the_clear_space_above_and_reloads(tmp_path):
    from combat import ext
    combat, table, mid = game(tmp_path, dislodge_success=True, host_fly=30, host_z=1, host_hover=True,
                              battlefield_transform=shaft, owner_fly=60, owner_position={'x': 4, 'y': 6, 'z': 3})
    climb(table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate_id(table.state(mid)['menu'], 'Dislodge a creature'))
    engine = reload(tmp_path, mid)
    moves = [e for e in engine.events if e.actor_id == OWNER and e.event_type == 'MOVEMENT_COMMITTED'
             and e.source_definition_id == SCALE]
    assert moves, 'a successful dislodge must move the clinger out of the carrier volume'
    assert moves[-1].payload['destination'] == {'x': 4, 'y': 6, 'z': 3}
    assert engine.state.actors[OWNER].position.z == 3
    assert carrier(engine, engine.state.actors[OWNER]) is None
    assert ext.run('attack_roll_modes', engine, engine.state.actors[FOE], engine.state.actors[OWNER]) == []


def test_close_quarters_does_not_apply_its_hostile_space_rules_to_a_friendly_carrier(tmp_path):
    combat, table, mid = game(tmp_path, trained=True, friendly=True, owner_kit=POLEARM_KIT, outside_x=6)
    climb(table, mid)
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.target_ids == (ALLY,) and
             c.source_definition_id.endswith('.weapon.ji'))
    settle(table, mid, c.candidate_id)
    row = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER)
    assert row.payload['mode'] == 'NORMAL'
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Outside attack', target=OWNER).candidate_id)
    row = next(e for e in reversed(reload(tmp_path, mid).events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY)
    assert row.payload['cover_bonus'] == 0
