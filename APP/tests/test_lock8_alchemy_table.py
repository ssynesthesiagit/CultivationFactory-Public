"""Owned Alchemy actions at the actual portable table, including terminal saves."""
import json
import zipfile
import pytest
from tests.legacy_fight_support import legacy_zero_hp

pytestmark = pytest.mark.usefixtures("legacy_zero_hp")

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat import ext
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.r10_fixup_support import cast_sender, commit

OWNER, FOE = 'actor:factory.aaaaaaaa', 'actor:factory.ffffffff'
BITTER = 'TAL_ALCHEMY_BITTER_DREGS'
INTENSIFY = 'tianxia.talent.alchemy.formula_intensification'
SEAL = 'TAL_ALCHEMY_MERIDIAN_SEALING_PILL'
STOCK, DREG, CP = 'resource:named.reagent_stock', 'resource:named.bitter_dreg', 'resource:core.stamina'


def fight(monkeypatch, tmp_path, ability, *, dc=50, foe_hp=1, owner_hp=60, blocker=False):
    for pid in (('aaaaaaaa', 'ffffffff', 'bbbbbbbb') if blocker else ('aaaaaaaa', 'ffffffff')):
        doc = sheet([ability] if pid == 'aaaaaaaa' else ['TAL_ALCHEMY_QI_INFUSION_PILL'],
                    primary='Stamina', dc=dc)
        doc['identity']['display_name'] = 'Alchemist' if pid == 'aaaaaaaa' else 'Target'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = owner_hp if pid == 'aaaaaaaa' else foe_hp
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('aaaaaaaa', {'mode': 'ask'}, {ability})
    def prepared(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == OWNER:
            actor = engine.state.actors[OWNER]
            for resource in (STOCK, DREG):
                if resource in actor.resource_maximums:
                    engine._gain_resource(actor, resource, 2, 'test:prepared-inventory')
    # The prepared-inventory hook joins the engine's own event subscribers: replacing the list
    # would switch off every other plug-in's event reader (combat/ext/life_state._events among
    # them), so a defeated creature never finalizes and the fight never ends.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), prepared])
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Alchemy yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[4 if ability == SEAL else 6, 4], [9,6]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'],
        opponent_actor_ids=[FOE, 'actor:factory.bbbbbbbb'] if blocker else [FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL', 'actor:factory.bbbbbbbb': 'MANUAL'}, arena_id='battlefield:map.alchemy-yard',
        match_seed='LOCK8-ALCHEMY')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return combat, table, mid


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def test_owned_intensification_pauses_after_terminal_hit_then_moves_and_reloads(monkeypatch, tmp_path):
    combat, table, mid = fight(monkeypatch, tmp_path, INTENSIFY)
    name = 'Field Formula: Numbing Smoke + Formula Intensification: Move Self'
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    paused = cast_sender(combat, table, mid, name, at=(6, 4))()
    assert paused['status'] == 'REACTION_REQUIRED'
    assert 'Formula Intensification' in paused['reaction']['reaction']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    commit(cast_sender(combat, table, mid, name, at=(6, 4)), lambda prompt: ('cell:3,3', True))
    e = reload_checked(tmp_path, mid)
    actor = e.state.actors[OWNER]
    assert e.state.terminal_result is not None and e.state.actors[FOE].current_hp == 0
    assert (actor.position.x, actor.position.y) == (3, 3)
    assert actor.movement_remaining_ft == before['actors'][OWNER]['movement_remaining_ft']
    assert actor.resources[STOCK] == before['actors'][OWNER]['resources'][STOCK] - 1
    assert actor.resources[CP] == before['actors'][OWNER]['resources'][CP] - 3
    movement = next(ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == OWNER)
    assert movement.payload['cost_ft'] == 0 and movement.payload['granted_cost_ft'] == 5
    assert movement.sequence > max(ev.sequence for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED')


@pytest.mark.parametrize('owner_hp', [60, 2])
def test_owned_bitter_backlash_after_last_enemy_dies_is_committed_once(monkeypatch, tmp_path, owner_hp):
    combat, table, mid = fight(monkeypatch, tmp_path, BITTER, dc=-40, owner_hp=owner_hp)
    name = 'Field Formula: Numbing Smoke + Bitter Dregs'
    before = combat._load_session(mid).engine.state.actors[OWNER].resources.copy()
    commit(cast_sender(combat, table, mid, name, at=(6, 4)))
    e = reload_checked(tmp_path, mid)
    assert e.state.terminal_result is not None and e.state.actors[FOE].current_hp == 0
    assert e.state.actors[OWNER].current_hp == max(0, owner_hp - 4)
    assert e.state.terminal_result.winning_team_id == e.state.actors[OWNER].team_id
    assert e.state.actors[OWNER].resources[DREG] == before[DREG] - 1
    assert e.state.actors[OWNER].resources[STOCK] == before[STOCK]
    damage = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED']
    assert [ev.target_ids for ev in damage] == [(FOE,), (OWNER,)]
    assert damage[-1].payload['damage_type'] == 'POISON'


@pytest.mark.parametrize('dc,saved', [(50, False), (-40, True)])
def test_real_meridian_seal_denies_direct_gain_and_expires_at_printed_turn(monkeypatch, tmp_path, dc, saved):
    combat, table, mid = fight(monkeypatch, tmp_path, SEAL, dc=dc, foe_hp=60)
    commit(cast_sender(combat, table, mid, 'Meridian-Sealing Pill', target=FOE))
    def regain(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == OWNER:
            target = engine.state.actors[FOE]
            engine._spend_resource(target, CP, 2, 'test:open-pool')
            engine._gain_resource(target, CP, 2, 'test:direct-recovery')
    install(monkeypatch, 'event', regain)
    before = combat._load_session(mid).engine.state.actors[FOE].resources[CP]
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[FOE].resources[CP] == before - 2
    turn(table, mid, FOE)
    e = reload_checked(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.no_cp_regain' for c in e.state.actors[FOE].conditions.values()) is not saved
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    e = reload_checked(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.no_cp_regain' for c in e.state.actors[FOE].conditions.values())
