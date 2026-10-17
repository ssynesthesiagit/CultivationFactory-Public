"""Recipe release uses the real Field Formula compiler, payment and table."""
import copy
import json
import pytest
from combat import ext
from combat.factory_compiler import compile_character, TYPED_AUTHORITY
from combat.recipe_options import RecipeOption, contributions
from tests import test_lock8_alchemy_table as T
from tests.test_lock8_alchemy_port import H, ME, STOCK, DREG, BITTER, INTENSIFY
from tests.test_lock_choices import install
from tests.r10_fixup_support import cast_sender, commit
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act

SEAL = T.SEAL
BASE = 'ALCHEMY_BASE_FIELD_FORMULA'
NAME = 'Field Formula: Meridian-Sealing Pill'
CP = T.CP


def actions(talents, **kwargs):
    bundle = compile_character(H._sheet('tianxia.sphere.alchemy', talents, H.AXE_KIT, dc=50, cl=10), actor_id=ME, **kwargs)
    return bundle


def test_release_preserves_administration_and_other_formula_bytes(monkeypatch):
    before = actions([SEAL, BITTER, INTENSIFY])
    monkeypatch.setitem(ext._HOOKS, 'compile_recipe_options', [])
    old = actions([SEAL, BITTER, INTENSIFY])
    # Only the new recipe family can differ, including optional combinations.
    new_rows = {a['source_definition_id']: a for a in before['action_catalog']}
    for action in old['action_catalog']:
        assert new_rows[action['source_definition_id']] == action
    releases = [a for a in before['action_catalog'] if a['display_name'].startswith(NAME)]
    assert len(releases) == 12  # plain, Bitter, five intensifications, five combinations
    assert all(a['parameters']['typed']['recipe_id'] == SEAL for a in releases)
    assert all(a['target_kind'] == 'ANY_CREATURE' and a['parameters']['typed']['area'] is None for a in releases)
    assert len({a['source_definition_id'] for a in releases}) == len(releases)


def test_unowned_recipe_is_inert_and_invalid_contributions_fail(monkeypatch):
    before = actions([])
    monkeypatch.setitem(ext._HOOKS, 'compile_recipe_options', [])
    assert actions([]) == before
    bad = RecipeOption(BASE, SEAL, [{'type': 'save'}], 'ANY_CREATURE')
    install(monkeypatch, 'compile_recipe_options', lambda owned, mechanics: [bad])
    with pytest.raises(ValueError, match='owned'):
        actions([])
    install(monkeypatch, 'compile_recipe_options', lambda owned, mechanics: [bad, bad])
    with pytest.raises(ValueError, match='Duplicate'):
        actions([SEAL])


def test_recipe_order_is_stable_and_not_subject_to_base_menu_cap(monkeypatch):
    rows = [RecipeOption(BASE, f'recipe:{i}', [{'type': 'temp_hp', 'flat': 1}], 'ALLY_OR_SELF') for i in range(9)]
    install(monkeypatch, 'compile_recipe_options', lambda owned, mechanics: list(reversed(rows)))
    owned = [BASE, *(r.recipe_id for r in rows)]
    assert contributions(owned, {}) == rows
    authority = json.loads(TYPED_AUTHORITY.read_bytes())
    for index, row in enumerate(rows):
        authority['mechanics'][row.recipe_id] = {
            **copy.deepcopy(authority['mechanics'][SEAL]),
            'name': f'Practice recipe {index}', 'economy': 'passive', 'effects': []}
    first = actions(owned, typed_authority=authority)
    releases = [a for a in first['action_catalog'] if a['parameters'].get('typed', {}).get('recipe_id')]
    assert [a['parameters']['typed']['recipe_id'] for a in releases] == [r.recipe_id for r in rows]
    install(monkeypatch, 'compile_recipe_options', lambda owned, mechanics: rows)
    assert actions(owned, typed_authority=authority) == first


def test_recipe_payment_pair_applies_full_substitution_modifier(monkeypatch):
    authority = json.loads(TYPED_AUTHORITY.read_bytes())
    modifier = authority['mechanics'][BITTER]['modifier']
    modifier.update(damage_die_steps={'6': 10}, add_range_ft=15, area_size_ft=15,
                    duration={'kind': 'rounds', 'rounds': 2}, economy='bonus_action')
    install(monkeypatch, 'compile_recipe_options', lambda owned, mechanics: [
        RecipeOption(BASE, SEAL, [{'type': 'damage', 'dice': {'count': 1, 'sides': 6},
            'damage_types': ['force'], 'applies_to': 'target'}], 'ANY_CREATURE')])
    before = copy.deepcopy(authority)
    bundle = actions([SEAL, BITTER, INTENSIFY], typed_authority=authority)
    name = NAME + ' + Formula Intensification: Longer Range + Bitter Dregs'
    action = next(a for a in bundle['action_catalog'] if a['display_name'] == name)
    typed = action['parameters']['typed']
    assert action['range_ft'] == typed['range_ft'] == 105
    assert action['economy'] == 'BONUS_ACTION'
    assert dict(action['costs']) == {'resource:core.stamina': 3, DREG: 1}
    assert typed['area'] == {'shape': 'sphere', 'size_ft': 15}
    assert typed['duration'] == {'kind': 'rounds', 'rounds': 2}
    damage = next(row for row in typed['effects'] if row['type'] == 'damage')
    assert damage['dice'] == {'count': 1, 'sides': 10}
    assert [row['id'] for row in typed['selected_modifiers']] == [INTENSIFY, BITTER]
    assert authority == before


@pytest.mark.parametrize('suffix,cost,stock,dreg', [('', 1, 1, 0), (' + Bitter Dregs', 1, 0, 1),
    (' + Formula Intensification: Longer Range', 3, 1, 0),
    (' + Formula Intensification: Longer Range + Bitter Dregs', 3, 0, 1)])
@pytest.mark.parametrize('dc,saved', [(50, False), (-40, True)])
def test_release_table_cost_denial_expiry_and_optional_choices(monkeypatch, tmp_path, suffix, cost, stock, dreg, dc, saved):
    original = T.sheet
    monkeypatch.setattr(T, 'sheet', lambda talents, **kw:
        original([*talents, BITTER, INTENSIFY] if SEAL in talents else talents, **kw))
    combat, table, mid = T.fight(monkeypatch, tmp_path, SEAL, dc=dc, foe_hp=60)
    e = combat._load_session(mid).engine
    before = copy.deepcopy(e.state.actors[T.OWNER])
    release = next(a for a in e.action_catalog.values() if a.owner_id == T.OWNER and a.display_name == NAME + suffix)
    assert release.range_ft == (90 if 'Longer Range' in suffix else 60)
    assert dict(release.costs) == {CP: cost, DREG if dreg else STOCK: 1}
    assert any(c.source_definition_id == release.source_definition_id and c.target_ids == (T.FOE,)
               for c in e.legal_candidates())
    assert any(c.source_definition_id == release.source_definition_id and c.target_ids == (T.OWNER,)
               for c in e.legal_candidates())
    commit(cast_sender(combat, table, mid, NAME + suffix, target=T.FOE))
    e = T.reload_checked(tmp_path, mid)
    actor = e.state.actors[T.OWNER]
    assert actor.resources[CP] == before.resources[CP] - cost
    assert actor.resources[STOCK] == before.resources[STOCK] - stock
    assert actor.resources[DREG] == before.resources[DREG] - dreg
    assert actor.current_hp == before.current_hp - (4 if saved and dreg else 0)
    assert e.state.actors[T.FOE].current_hp == 60  # the formula is nondamaging
    def regain(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == T.OWNER:
            target = engine.state.actors[T.FOE]
            engine._spend_resource(target, CP, 2, 'test:open-pool')
            engine._gain_resource(target, CP, 2, 'test:formula-denial')
    install(monkeypatch, 'event', regain)
    prior = e.state.actors[T.FOE].resources[CP]
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    e = T.reload_checked(tmp_path, mid)
    assert e.state.actors[T.FOE].resources[CP] == prior - 2
    turn(table, mid, T.FOE)
    e = T.reload_checked(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.no_cp_regain' for c in e.state.actors[T.FOE].conditions.values()) is not saved
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    e = T.reload_checked(tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.no_cp_regain' for c in e.state.actors[T.FOE].conditions.values())


def test_release_push_choice_rolls_back_pays_once_and_reloads(monkeypatch, tmp_path):
    original = T.sheet
    monkeypatch.setattr(T, 'sheet', lambda talents, **kw:
        original([*talents, BITTER, INTENSIFY] if SEAL in talents else talents, **kw))
    combat, table, mid = T.fight(monkeypatch, tmp_path, SEAL, foe_hp=60)
    name = NAME + ' + Formula Intensification: Push Creature + Bitter Dregs'
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    paused = cast_sender(combat, table, mid, name, target=T.FOE)()
    assert paused['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat = T.CombatService(T.ROOT, tmp_path)
    table = T.TabletopService(combat, tmp_path)
    commit(cast_sender(combat, table, mid, name, target=T.FOE), lambda prompt: (T.FOE, True))
    e = T.reload_checked(tmp_path, mid)
    assert e.state.actors[T.FOE].position.x == 6
    actor = e.state.actors[T.OWNER]
    assert actor.resources[CP] == before['actors'][T.OWNER]['resources'][CP] - 3
    assert actor.resources[DREG] == before['actors'][T.OWNER]['resources'][DREG] - 1
