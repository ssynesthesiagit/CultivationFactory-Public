"""INS7D: real table/session actions, persisted ownership and cold replay.

Synthetic packets isolate a named guard opening and deterministic missed
Opportunity Attack; a real compiled Hewing Strike covers modifier attribution.
No browser or model transport is used.
"""
import pytest

from combat.ext import sand_born_footwork as sand, shieldhook_adept as shield
from combat.ext.guard_broken import CONDITION
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, action_sender, fight, reload, resolve, turn


def fresh(combat, mid):
    e = reload(combat, mid)
    s = combat._load_session(mid)
    assert s.verify()["status"] == "PASS"
    assert s.mechanical.replay()["status"] == "PASS"
    return e


def shield_match(tmp_path, *, owns=True, success=False, ai=False, real=False, relation_case=False):
    def edit(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [shield.FEATURE] if owns else []
        if aid == RIGHT:
            doc["proficiencies"] = {"armor": ["Shield"]}
    def bundle_edit(bundle):
        if bundle["actor_id"] == LEFT:
            old = "action:test.worker1." + LEFT
            new = "passive:" + shield.BEARD
            for a in bundle["action_catalog"]:
                if a["source_definition_id"] == old:
                    a["source_definition_id"] = new
            bundle["actor_template"]["action_ids"] = [new if a == old else a for a in bundle["actor_template"]["action_ids"]]
    save = {"type": "save", "ability": "str", "dc": -100 if success else 100,
        "on_fail": [{"type": "break_guard", "shield": True, "next": False}],
        "on_success": [{"type": "break_guard", "shield": True, "next": True, "axe": True}]}
    attack = {"type": "attack", "attack_kind": "cultivation_melee", "on_hit": [], "on_miss": []}
    axe_kit = {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}
    shield_kit = {"items": [{"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}
    c, t, mid = fight(tmp_path, ["TAL_AXES_SHIELD_CATCHING_BEARD", "TAL_AXES_HEWING_STRIKE"] if real else [],
        sheet_edit=edit, bundle_edit=bundle_edit, ally=[], prepare=[save], prepare_source="passive:" + shield.BEARD,
        left_save_dc=-100 if success else 100, reaction_ask=not ai,
        cause=[attack], cause_target="ANY_CREATURE", left_kit=axe_kit if real else None,
        right_kit=shield_kit, left_score=50 if real else 14,
        extra_actions=[("Plain attack", {"target_kind": "ANY_CREATURE", "effects": [attack]})],
        ally_team="team:shieldhook-cross" if relation_case else "team:factory",
        extra_witness=relation_case, witness_team="team:factory",
        witness_position={"x": 2, "y": 5} if relation_case else None)
    return c, t, mid


def guard(e):
    return next(c for c in e.state.actors[RIGHT].conditions.values() if c.condition_id == CONDITION)


@pytest.mark.parametrize("success", [False, True])
@pytest.mark.parametrize("pick", [LEFT, ALLY])
def test_guard_choice_persists_exact_recipient_scope_and_deadline(tmp_path, success, pick):
    c, t, mid = shield_match(tmp_path, success=success)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {shield.CHOICE: [pick]})
    e = fresh(c, mid)
    g = guard(e)
    assert g.source_actor_id == LEFT
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == shield.CHOICE)
    assert {o["id"] for o in q["choice"]["options"]} == {LEFT, ALLY}
    assert "Shield-Catching Beard" in str(q) and "Visitor" in str(q)
    if pick == ALLY:
        assert g.data["beneficiary_id"] == ALLY and g.data["next"] and not g.data["axe"]
        assert g.expires_on == (f"END_OF_SOURCE_TURN_AT:{e.state.actors[LEFT].turns_started}" if success else "START_OF_SOURCE_NEXT_TURN")
    else:
        assert "beneficiary_id" not in g.data and g.data["next"] == success


@pytest.mark.parametrize("success", [False, True])
def test_ally_opening_expires_at_casters_boundary(tmp_path, success):
    c, t, mid = shield_match(tmp_path, success=success)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {shield.CHOICE: [ALLY]})
    turn(t, mid, RIGHT)
    e = fresh(c, mid)
    assert any(x.condition_id == CONDITION for x in e.state.actors[RIGHT].conditions.values()) != success
    turn(t, mid, LEFT)
    assert not any(x.condition_id == CONDITION for x in fresh(c, mid).state.actors[RIGHT].conditions.values())


def test_unrelated_attack_does_not_consume_ally_opening(tmp_path):
    c, t, mid = shield_match(tmp_path)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {shield.CHOICE: [ALLY]})
    resolve(lambda a: act(t, mid, "Plain attack", a, target_id=RIGHT))
    before = fresh(c, mid)
    assert guard(before).data["beneficiary_id"] == ALLY
    from combat.armour import shield_bonus_earning
    assert shield_bonus_earning(before, before.state.actors[RIGHT]) == 2
    base_ac = before.state.actors[RIGHT].armor_class
    # The ally's unarmed attack consumes it; no axe/weapon restriction survives.
    turn(t, mid, ALLY)
    e = fresh(c, mid)
    label = next(a.display_name for a in e.action_catalog.values() if a.owner_id == ALLY
                 and a.resolution_kind == "TYPED" and a.parameters.get("typed", {}).get("weapon")
                 and a.display_name == "Unarmed Strike")
    resolve(lambda a: act(t, mid, label, a, target_id=RIGHT))
    after = fresh(c, mid)
    assert not any(x.condition_id == CONDITION for x in after.state.actors[RIGHT].conditions.values())
    roll = next(ev for ev in reversed(after.events) if ev.event_type == "ATTACK_ROLLED" and ev.actor_id == ALLY)
    assert roll.payload["target_ac"] == base_ac - 2


def test_shield_nonowner_keeps_ordinary_guard_without_prompt(tmp_path):
    c, t, mid = shield_match(tmp_path, owns=False)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert not prompts and "beneficiary_id" not in guard(fresh(c, mid)).data


def test_shield_ai_keeps_ordinary_benefit_without_player_prompt(tmp_path):
    c, t, mid = shield_match(tmp_path, ai=True)
    _, prompts = resolve(action_sender(c, t, mid, "Prepare", ai=True, target_id=RIGHT))
    assert not prompts and "beneficiary_id" not in guard(fresh(c, mid)).data


def test_shieldhook_uses_relations_for_cross_team_allies_and_same_team_enemies(tmp_path):
    c, t, mid = shield_match(tmp_path, relation_case=True)
    witness = "actor:factory.auto111-witness"
    c.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
        "other": ALLY, "relation": "ALLY"},
        expected_state_version=c._load_session(mid).engine.state.state_version)
    c.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
        "other": witness, "relation": "ENEMY"},
        expected_state_version=c._load_session(mid).engine.state.state_version)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {shield.CHOICE: [ALLY]})
    e = fresh(c, mid)
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == shield.CHOICE)
    assert {o["id"] for o in q["choice"]["options"]} == {LEFT, ALLY}
    assert guard(e).data["beneficiary_id"] == ALLY


def test_real_compiled_beard_uses_the_same_beneficiary_choice(tmp_path):
    c, t, mid = shield_match(tmp_path, real=True)
    e = fresh(c, mid)
    names = [a.display_name for a in e.action_catalog.values() if a.owner_id == LEFT
             and "Shield-Catching Beard" in a.display_name]
    assert names
    resolve(lambda a: act(t, mid, names[0], a, target_id=RIGHT), {shield.CHOICE: [ALLY]})
    assert guard(fresh(c, mid)).data["beneficiary_id"] == ALLY


SQUARE = {"name": "Sand test", "cells": [], "size_ft": 5, "centered_on_self": True,
          "terrain": ["deep sand terrain"], "visual": {"material": "sand"},
          "difficult": "all", "duration": {"kind": "one_minute"}}


def sand_match(tmp_path, *, owns=True, oa=True, ai=False, terrain="deep sand terrain", large=False):
    def edit(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [sand.FEATURE] if owns else []
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 100
    def bundle(bundle):
        if bundle["actor_id"] == RIGHT:
            for a in bundle["action_catalog"]:
                if a["display_name"] == "Cause":
                    a["parameters"]["typed"]["numbers"]["attack_bonus"] = -100
                    if oa:
                        a["parameters"]["typed"]["opportunity_of"] = "action:test.opportunity_profile"
    attack = {"type": "attack", "attack_kind": "cultivation_melee", "on_hit": [], "on_miss": []}
    zone = {k: v for k, v in SQUARE.items() if k != "cells"}
    zone["terrain"] = [terrain]
    if terrain not in ("shallow sand terrain", "deep sand terrain"):
        zone["visual"] = {}
    return fight(tmp_path, sheet_edit=edit, bundle_edit=bundle, cause=[attack], cause_target="ANY_CREATURE",
        prepare=[{"type": "zone"}], prepare_zone_spec=zone, prepare_target="SELF", reaction_ask=not ai,
        extra_actions=([("Grow", {"effects": [{"type": "size_change", "size": "Large", "duration": {"kind": "one_minute"}}]})] if large else []) + [("Hide check", {"target_kind": "HOSTILE_ENTITY", "effects": [{"type": "contest_against",
            "actor_check": {"ability": "DEX", "skill": "Stealth", "hazards": ["hide"]},
            "target_check": {"kind": "dc", "basis": "save_dc"}}]})])


@pytest.mark.parametrize("owns", [False, True])
@pytest.mark.parametrize("oa", [False, True])
def test_missed_opportunity_creates_one_square_only_for_owner(tmp_path, owns, oa):
    c, t, mid = sand_match(tmp_path, owns=owns, oa=oa)
    turn(t, mid, RIGHT)
    _, prompts = resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT))
    e = fresh(c, mid)
    created = [z for z in e.state.zones.values() if z.source_definition_id == sand.FEATURE]
    assert len(created) == int(owns and oa)
    if created:
        z = created[0]
        assert z.owner_id == LEFT and len(z.affected_cells) == 1
        assert e.grid.distance_ft(e.state.actors[LEFT].position, z.affected_cells[0]) == 5
        q = next(p for p in prompts if p["context"]["reaction_source_id"] == sand.CHOICE)
        assert len(q["choice"]["options"]) == 8
        assert "Opportunity Attack" in str(q) and "Keeper" in str(q)
        turn(t, mid, LEFT)
        turn(t, mid, RIGHT)
        _, prompts2 = resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT))
        assert not any(p["context"]["reaction_source_id"] == sand.CHOICE for p in prompts2)
        assert len([z for z in fresh(c, mid).state.zones.values() if z.source_definition_id == sand.FEATURE]) == 1


def test_declining_sand_keeps_scene_allowance(tmp_path):
    c, t, mid = sand_match(tmp_path)
    turn(t, mid, RIGHT)
    resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT), {sand.CHOICE: []})
    assert not fresh(c, mid).state.actors[LEFT].turn_flags.get(sand.USED)
    resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT))
    assert fresh(c, mid).state.actors[LEFT].turn_flags[sand.USED] == 1


@pytest.mark.parametrize("ai", [False, True])
def test_large_sand_owner_offers_full_external_footprint_perimeter(tmp_path, monkeypatch, ai):
    from combat.ext import needle
    c, t, mid = sand_match(tmp_path, large=True, ai=ai)
    resolve(lambda a: act(t, mid, "Grow", a))
    before = fresh(c, mid)
    footprint = set(before._actor_cells(before.state.actors[LEFT]))
    assert len(footprint) == 4
    expected = {(x + dx, y + dy) for x, y in footprint
                for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy} - footprint
    observed = []
    original = sand.ask
    def capture(*args, **kwargs):
        observed.append(set(args[5]))
        return original(*args, **kwargs)
    monkeypatch.setattr(sand, "ask", capture)
    turn(t, mid, RIGHT)
    if ai:
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    destination = f"cell:{max(x for x, y in footprint) + 1},{max(y for x, y in footprint)}"
    resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT), {sand.CHOICE: [destination]})
    assert observed and all(pool == {f"cell:{x},{y}" for x, y in expected} for pool in observed)
    engine = fresh(c, mid)
    zone = next(z for z in engine.state.zones.values() if z.source_definition_id == sand.FEATURE)
    assert {(p.x, p.y) for p in zone.affected_cells} <= expected
    if not ai:
        assert needle.cell_id(zone.affected_cells[0]) == destination


def test_sand_ai_off_turn_selects_from_same_legal_cells_without_prompt(tmp_path):
    c, t, mid = sand_match(tmp_path, ai=True)
    turn(t, mid, RIGHT)
    c.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    _, prompts = resolve(lambda a: act(t, mid, "Cause", a, target_id=LEFT))
    e = fresh(c, mid)
    assert not prompts
    assert e.state.actors[LEFT].turn_flags[sand.USED] == 1
    assert len([z for z in e.state.zones.values() if z.source_definition_id == sand.FEATURE]) == 1


@pytest.mark.parametrize("owns", [False, True])
def test_own_sand_exemption_is_scoped_to_creating_owner(tmp_path, owns):
    from combat import zones
    c, t, mid = sand_match(tmp_path, owns=owns)
    resolve(lambda a: act(t, mid, "Prepare", a))
    e = fresh(c, mid)
    z = next(z for z in zones.typed_zones(e) if z.owner_id == LEFT)
    assert ((3, 6) not in zones.difficult_cells(e, e.state.actors[LEFT])) == owns
    assert (3, 6) in zones.difficult_cells(e, e.state.actors[RIGHT])


@pytest.mark.parametrize("terrain,expected", [("deep sand terrain", "ADVANTAGE"), ("ruin", "ADVANTAGE"),
    ("dusty", "ADVANTAGE"), ("desert", "ADVANTAGE"), ("dry-earth", "ADVANTAGE"), ("grass", "NORMAL")])
def test_environmental_hiding_mode_after_table_commit_and_reload(tmp_path, terrain, expected):
    from combat.ability_checks import hide_check_mode
    c, t, mid = sand_match(tmp_path, terrain=terrain)
    resolve(lambda a: act(t, mid, "Prepare", a))
    e = fresh(c, mid)
    assert hide_check_mode(e, e.state.actors[LEFT]) == expected
    assert hide_check_mode(e, e.state.actors[RIGHT]) == "NORMAL"
    resolve(lambda a: act(t, mid, "Hide check", a, target_id=RIGHT))
    e = fresh(c, mid)
    check = next(ev for ev in reversed(e.events) if ev.event_type == "CHECK_ROLLED" and ev.actor_id == LEFT)
    assert check.payload["actor"]["mode"] == expected
