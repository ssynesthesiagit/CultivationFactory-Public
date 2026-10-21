"""Compiler and final-roll contracts exposed by the F7 integrated review."""
from pathlib import Path

import pytest

from combat import ext, typed_executor as te, typed_reactions
from combat.ext import athletics_grip_lungs
from combat import roof_movement as climbing
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, duel, ME, FOE, script, sheet
from tests.test_lock_choices import install

# Dynamic runtime inputs must accompany this file in a public test export.
ATHLETICS_BLOCK = Path('combat/rules/feature_blocks.d/athletics-second-pass.json')

DARK = "TAL_DARK_TENEBROUS_LEGERDEMAIN"
# Inline kit data (a public item id): importing tests/test_riders_c4.py would
# pull repository history into the public export, which cannot publish it.
AXE = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu",
                                   "name": "Fu (Short Axe)", "quantity": 1}]}}


def _act(table, mid, text, answers=(), destination=None):
    if destination is not None:
        from tests.r1i_service_support import place
        return place(table, mid, text, destination, answers)
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if text in g["label"])
    option = next((o for o in group["options"] if FOE in o.get("target_ids", [])), group["options"][0])
    return table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers))


def _reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


def _dark_table(tmp_path):
    bundles = []
    for aid in (ME, FOE):
        document = sheet([DARK] if aid == ME else [], kit=AXE)
        document["identity"]["display_name"] = "Left" if aid == ME else "Right"
        document["ability_scores_and_statistics"]["skills"] = [
            {"skill": "Sleight of Hand", "bonus": 100 if aid == ME else 0},
            {"skill": "Athletics", "bonus": 0}, {"skill": "Acrobatics", "bonus": 1}]
        b = compile_character(document, actor_id=aid, reaction_plan={"ask": True})
        b["actor_template"]["initiative_bonus"] = 100 if aid == ME else -100
        b.pop("bundle_sha256", None)
        b["bundle_sha256"] = canonical_sha256(b)
        bundles.append(b)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="A11-DARK", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    table = TabletopService(service, tmp_path)
    assert _act(table, session.match_id, "Shape Darkness: Tenebrous Legerdemain")["status"] == "COMMITTED"
    assert _act(table, session.match_id, "Darkness", destination={"x": 4, "y": 6})["status"] == "COMMITTED"
    return service, table, session.match_id


@pytest.mark.parametrize('owned', [True, False])
def test_canonical_grip_row_drives_climbing_and_holds_together(owned):
    engine = duel(['TAL_ATHLETICS_SURE_GRIP'] if owned else [])
    actor = engine.state.actors[ME]
    rows = [r for r in engine.typed_passive_rows[ME]
            if r.get('feature_id') == 'TAL_ATHLETICS_SURE_GRIP']
    assert len(rows) == int(owned)
    assert bool(athletics_grip_lungs.maintain_grip(engine, actor)) is owned
    assert ('ADVANTAGE' in climbing.profile(engine, actor).check_modes) is owned


@pytest.mark.parametrize('outcome', ['success', 'failure'])
def test_declared_save_reaches_all_notifications_and_is_consumed_once(monkeypatch, outcome):
    engine = duel([])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {}, [target], target)
    seen = []
    markers = []
    monkeypatch.setattr(typed_reactions, 'after_d20',
                        lambda *a, **kw: seen.append(('d20', not kw['success'])))
    monkeypatch.setattr(typed_reactions, 'on_creature_event',
                        lambda e, s, name: seen.append(('event', name == 'creature_save_failed')))
    def after_save(c, s, a, n, failed):
        seen.append(('save', failed))
        markers.append(c.engine._typed_roll_outcome.get(s.entity_id))
    install(monkeypatch, 'after_save', after_save)
    engine._typed_roll_outcome = {FOE: outcome}
    expected = outcome == 'failure'
    assert te.settle_typed_save(ctx, target, 'CHA', None, not expected, set(), set(), 0) is expected
    assert seen == [('d20', expected), ('event', expected), ('save', expected)]
    assert markers == [outcome]  # Later reactions must see that the outcome was already declared.
    assert FOE not in engine._typed_roll_outcome
    seen.clear()
    assert te.settle_typed_save(ctx, target, 'CHA', None, not expected, set(), set(), 0) is not expected


@pytest.mark.parametrize('hazards, expected', [(['poisoned'], True), ([], False)])
def test_opposed_check_transports_its_own_pressure_to_native_roll_hooks(monkeypatch, hazards, expected):
    engine = duel([])
    actor, target = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    ctx = te.Context(engine, actor, action, None, {}, [target], target)
    seen = []
    def observe(e, roll, intent):
        context = e.d20_context(roll)
        if context and context.get('kind') == 'check':
            seen.append('poisoned' in context['named'])
    install(monkeypatch, 'd20_bonus', observe)
    script(engine, [10])
    te.resolve_opposed_check(ctx, target,
        {'kind': 'check', 'ability': 'STR', 'hazards': hazards}, {'kind': 'dc', 'dc': 12})
    assert seen and all(value is expected for value in seen)


def test_darkness_placement_does_not_reselect_shape_darkness(tmp_path):
    _, _, mid = _dark_table(tmp_path)
    engine = _reload(tmp_path, mid)
    assert any(a.parameters.get('dark_legerdemain') for a in engine.action_catalog.values())
    zones = [zone for zone in engine.state.zones.values()
             if zone.trigger_profile.get('name') == 'Darkness']
    assert len(zones) == 1
    center = zones[0].center
    assert (center.x, center.y, center.z) == (4, 6, 0)
    assert zones[0].trigger_profile['talents'] == ['Tenebrous Legerdemain']


def test_darkness_setup_uses_the_table_square_choice_before_commit(tmp_path, monkeypatch):
    from combat.placement_menu import CHOICE

    act = TabletopService.act
    results = []
    def observe(self, *args, **kwargs):
        result = act(self, *args, **kwargs)
        results.append(result)
        return result
    monkeypatch.setattr(TabletopService, 'act', observe)
    _dark_table(tmp_path)
    assert [r['status'] for r in results] == ['COMMITTED', 'REACTION_REQUIRED', 'COMMITTED']
    prompt = results[1]['reaction']
    assert prompt['context']['reaction_source_id'] == CHOICE
    assert 'cell:4,6,0' in {o['id'] for o in prompt['choice']['options']}
