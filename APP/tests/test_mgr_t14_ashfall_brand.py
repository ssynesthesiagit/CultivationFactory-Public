"""Assigned base rows through compiled sheets, table intents and cold reload.

No live model requests. The repeat-hit case only relaxes action economy in its
fixture; the attack, pressure choices and turn clock are the native providers.
"""
import json
from functools import lru_cache

import pytest

from combat.ext import ash_core, placed
from combat.typed_executor import stored_healing_reductions
from tests.auto_worker1_support import (
    LEFT, RIGHT, act, action_sender, cell_send, fight, reload, settle, turn,
)
from tests.test_auto62_destruction import cell_sender
from tests.h1_support import ROOT
from sphere_component_authority import (
    attach_sphere_automatic_component_receipt, build_sphere_automatic_component_authority,
)

ASHFALL = "ASH_BASE_ASHFALL"
BRAND = "ASH_BASE_CINDER_BRAND"
SPHERE = "tianxia.sphere.ash"
POOL = "resource:core.qi"


@lru_cache(maxsize=1)
def grants():
    """The native acquisition producer consumes the real catalog's Ash packet."""
    catalog = json.loads((ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    sphere = next(row for row in catalog["spheres"] if row["canonical_sphere_id"] == SPHERE)
    packet = build_sphere_automatic_component_authority(SPHERE, sphere["resolved_automatic_base_abilities"])
    record = {"record_id": SPHERE, "record_hash": sphere["record_commitment_sha256"],
              "automatic_component_authority": packet}
    event = {"event_id": "event.test.ash.acquisition", "advancement": {"target_cl": 1},
             "legal_channel": "ai-bootstrap-free-cl1-sphere",
             "content_binding": {"record_hash": record["record_hash"]}}
    ledger = {}
    attach_sphere_automatic_component_receipt(ledger, record, event)
    components = ledger["automatic_sphere_components"]
    assert {row["component_id"] for row in components} == {ASHFALL, BRAND}
    assert all(row["automatic_grant"] and not row["counts_as_talent_choice"] for row in components)
    return ledger


def acquired(doc, aid):
    """Project actual automatic grants through the production sheet field."""
    if aid == LEFT:
        ledger = grants()
        doc["spheres_and_talents"].update(
            sphere_record_ids=[SPHERE], learned_talent_record_ids=[],
            automatic_sphere_components=ledger["automatic_sphere_components"],
            automatic_sphere_component_receipts=ledger["automatic_sphere_component_receipts"],
            automatic_sphere_component_record_ids=[row["component_id"] for row in ledger["automatic_sphere_components"]])


def table(tmp_path, **kwargs):
    return fight(tmp_path, [], sheet_edit=acquired, left_attack_bonus=100, **kwargs)


def pressure_pick(label):
    def choose(prompt):
        options = [o["id"] for o in prompt["choice"]["options"]]
        return [label] if label in options else options[:1]
    return choose


def remnants(engine, owner=LEFT):
    return placed.of(engine, "ash_remnant", owner_id=owner)


def test_ashfall_native_grant_geometry_linger_and_reload(tmp_path):
    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}})
    before = reload(c, m).state.actors[LEFT].resources[POOL]
    settle(cell_send(t, m, "Ashfall", (8, 6)))
    e = reload(c, m)
    zone = next(z for z in e.state.zones.values() if z.active)
    assert zone.center.x == 8 and zone.center.y == 6
    assert zone.duration_rounds == 10 and zone.concentration_link
    assert zone.trigger_profile["terrain"] == ["ash terrain"]
    cells = {(p.x, p.y) for p in zone.affected_cells}
    assert (8, 9) in cells and (8, 10) not in cells
    assert e.state.actors[LEFT].resources[POOL] == before
    _, prompts = settle(action_sender(c, t, m, "Lingering Ashfall (2 CP)"))
    assert not prompts
    e = reload(c, m)
    kept = e.state.zones[zone.zone_id]
    assert kept.active and not kept.concentration_link and kept.center == zone.center
    assert e.state.actors[LEFT].concentration is None
    assert e.state.actors[LEFT].resources[POOL] == before - 2
    turn(t, m, RIGHT)
    assert all("Ashfall" not in g["label"] for g in t.state(m)["menu"]["actions"])
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e.state.zones[zone.zone_id].center == zone.center


def test_the_built_in_ai_never_spends_cp_on_lingering_ashfall(tmp_path):
    """Lingering Ashfall is the owner's own choice ("You may apply this augment after creating Ashfall on your
    turn"), so the built-in AI's menu leaves it out and the player's menu keeps it; the 2 CP are never spent
    without the owner asking. A model/AI pilot seat still sees it (include_item_actions keeps player_only rows)."""
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary

    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}})
    settle(cell_send(t, m, "Ashfall", (8, 6)))
    engine = reload(c, m)
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    player_menu = {v.display_name for v in
                   build_decision_context(engine, policy, include_item_actions=True).legal_candidates}
    ai_menu = {v.display_name for v in build_decision_context(engine, policy, for_ai=True).legal_candidates}
    assert any(name.startswith("Lingering Ashfall") for name in player_menu), player_menu
    assert not [name for name in ai_menu if name.startswith("Lingering Ashfall")], ai_menu


@pytest.mark.parametrize("ai", [False, True])
def test_pressure_choice_is_after_hit_owned_and_expires(tmp_path, ai):
    c, t, m = table(tmp_path)
    before = reload(c, m).state.actors[LEFT].resources[POOL]
    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Create Remnant", ai=ai),
                        pressure_pick("Reduce Healing"))
    e = reload(c, m)
    assert any(v.event_type == "ATTACK_ROLLED" for v in e.events)
    assert any("ashen_brand" in row.condition_id for row in e.state.actors[RIGHT].conditions.values())
    assert e.state.actors[LEFT].resources[POOL] == before
    if ai:
        assert not prompts
        assert len(remnants(e)) == 1
        c.set_controller_mode(m, actor_id=LEFT, controller_mode="MANUAL")
    else:
        choice = next(p for p in prompts if p["context"]["reaction_source_id"].endswith(ash_core.PRESSURE))
        assert choice["context"]["reactor_id"] == LEFT
        assert {o["id"] for o in choice["choice"]["options"]} == {
            "Reduce Healing", "Create Remnant", "Move Remnant"}
        assert not remnants(e)
        assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16
        turn(t, m, RIGHT)
        e = reload(c, m)
        assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16
        turn(t, m, LEFT)
        e = reload(c, m)
        assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 20
        assert not any("ashen_brand" in row.condition_id for row in e.state.actors[RIGHT].conditions.values())


def test_remnant_move_offers_short_and_bent_destinations_and_cold_reload(tmp_path):
    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}})
    settle(action_sender(c, t, m, "Cinder Brand: Create Remnant"), pressure_pick("Create Remnant"))
    engine = reload(c, m)
    zone = remnants(engine)[0]
    center = zone.center
    # "move one Remnant within 30 feet up to 10 feet" offers every in-map square in reach, not only the
    # eight maximum-distance directions: short steps and diagonal ("bent") steps are all legal moves.
    steps = {(center.x + dx, center.y + dy): f"{zone.zone_id}|cell:{center.x + dx},{center.y + dy}"
             for dx in range(-2, 3) for dy in range(-2, 3) if (dx or dy)
             and engine.grid.in_bounds((center.x + dx, center.y + dy))
             and (center.x + dx, center.y + dy) not in engine.grid.blocked}
    short, bent = (center.x + 1, center.y), (center.x + 1, center.y + 1)
    assert short in steps and bent in steps
    turn(t, m, RIGHT)
    turn(t, m, LEFT)  # the move is another Action

    def choose(prompt):
        ids = [o["id"] for o in prompt["choice"]["options"]]
        if steps.get(short) in ids:
            offered = [option for option in ids if option.startswith(zone.zone_id + "|")]
            assert len(offered) == len(steps)
            assert steps[bent] in ids  # a bent short step has its own coordinate id
            return [steps[short]]
        return ["Move Remnant"] if "Move Remnant" in ids else ids[:1]

    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Move Remnant"), choose)
    assert any(steps[short] in [o["id"] for o in p["choice"]["options"]] for p in prompts)
    moved = next(z for z in placed.of(reload(c, m), "ash_remnant") if z.zone_id == zone.zone_id)
    assert (moved.center.x, moved.center.y) == short
    assert moved.created_round == zone.created_round
    assert moved.duration_rounds == zone.duration_rounds == 10
    assert not moved.concentration_link


def test_second_hit_same_turn_keeps_damage_and_brand_but_not_pressure(tmp_path):
    def repeat_economy(bundle):
        for action in bundle["action_catalog"]:
            if BRAND in action["source_definition_id"]:
                action["economy"] = "NONE"
                action["parameters"]["free_primary"] = True

    c, t, m = table(tmp_path, bundle_edit=repeat_economy)
    settle(action_sender(c, t, m, "Cinder Brand: Create Remnant"), pressure_pick("Create Remnant"))
    e = reload(c, m)
    assert len(remnants(e)) == 1
    before = e.state.actors[RIGHT].current_hp
    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Reduce Healing"), pressure_pick("Reduce Healing"))
    e = reload(c, m)
    assert e.state.actors[RIGHT].current_hp < before
    assert not any(p["context"]["reaction_source_id"].endswith(ash_core.PRESSURE) for p in prompts)
    assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 20
    assert len(remnants(e)) == 1
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    _, prompts = settle(action_sender(c, t, m, "Cinder Brand: Reduce Healing"), pressure_pick("Reduce Healing"))
    assert any(p["context"]["reaction_source_id"].endswith(ash_core.PRESSURE) for p in prompts)
    e = reload(c, m)
    assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16


def test_reduce_healing_uses_the_typed_formula_when_the_printed_prose_is_rewritten(tmp_path, monkeypatch):
    """The public test export rewrites free prose in the authority (tools/public_test_prose.py).
    The pressure row's typed ``formula`` still says "pb", so Reduce Healing must keep working
    instead of silently applying nothing when its sentence cannot be read."""
    from combat import factory_compiler as compiler

    authority = json.loads(compiler.TYPED_AUTHORITY.read_text(encoding="utf-8"))
    record = authority["mechanics"][BRAND]
    scrambled = 0
    for option in record["options"]:
        for effect in option["effects"]:
            for row in effect.get("on_hit") or []:
                if row.get("type") == "healing_reduction":
                    assert row["formula"] == "pb"
                    row["evidence"] = "qwy zzx vbn mmm plk"
                    scrambled += 1
    assert scrambled
    rewritten = tmp_path / "authority.json"
    rewritten.write_text(json.dumps(authority), encoding="utf-8")
    monkeypatch.setattr(compiler, "TYPED_AUTHORITY", rewritten)
    c, t, m = table(tmp_path)
    settle(action_sender(c, t, m, "Cinder Brand: Create Remnant"), pressure_pick("Reduce Healing"))
    e = reload(c, m)
    assert stored_healing_reductions(e, e.state.actors[RIGHT], 20) == 16


@pytest.mark.parametrize("cl,dice", [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_cinder_native_damage_brackets_and_key_modifier(tmp_path, cl, dice):
    c, t, m = table(tmp_path, cl=cl)
    settle(action_sender(c, t, m, "Cinder Brand: Reduce Healing"), pressure_pick("Reduce Healing"))
    e = reload(c, m)
    rolls = [v.payload for v in e.events if v.event_type == "DAMAGE_ROLLED" and v.actor_id == LEFT]
    assert len(rolls) == 1
    # Critical hits double dice only; the real Path key modifier remains +2.
    assert rolls[0]["expression"] in (f"{dice}d8+2", f"{dice * 2}d8+2")


def test_native_range_and_wrong_owner_controls(tmp_path):
    c, t, m = table(tmp_path, positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 16, "y": 6}})
    e = reload(c, m)
    candidates = e.legal_candidates()
    assert not any(v.display_name.startswith("Cinder Brand:") and RIGHT in v.target_ids for v in candidates)
    casts = [v for v in candidates if v.display_name.startswith("Ashfall at ")]
    assert casts and all(e.grid.distance_ft(e.state.actors[LEFT].position, v.destination) <= 60 for v in casts)
    turn(t, m, RIGHT)
    assert not any("Cinder Brand" in g["label"] or "Ashfall" in g["label"] for g in t.state(m)["menu"]["actions"])


def test_lingering_ashfall_expires_at_original_one_minute_boundary(tmp_path):
    c, t, m = table(tmp_path, maximum_rounds=12)
    settle(cell_send(t, m, "Ashfall", (8, 6)))
    settle(lambda answers: act(t, m, "Lingering Ashfall (2 CP)", answers))
    e = reload(c, m)
    zone = next(z for z in e.state.zones.values() if z.active)
    for _ in range(10):
        turn(t, m, RIGHT)
        turn(t, m, LEFT)
    e = reload(c, m)
    assert not e.state.zones[zone.zone_id].active
    assert any(v.event_type == "ZONE_REMOVED" and v.payload.get("reason") == "DURATION_ENDED" for v in e.events)


def _warding_ash(extra=None):
    """A synthetic ordinary Temporary HP source, so the pressure choice has a pool to suppress."""
    effect = {"type": "temp_hp", "applies_to": "target", "flat": 40}
    effect.update(extra or {})
    return [("Warding Ash", {"effects": [effect], "target_kind": "HOSTILE_ENTITY"})]


def test_suppressed_temporary_hp_restores_and_survives_a_table_reload(tmp_path):
    """Cinder Brand's suppression stops an ordinary pool protecting the target (it returns at the
    start of the caster's next turn), and both the suppression and its amount survive a cold load."""
    c, t, m = table(tmp_path, extra_actions=_warding_ash())
    settle(action_sender(c, t, m, "Warding Ash"))
    assert reload(c, m).state.actors[RIGHT].temporary_hp == 40
    settle(action_sender(c, t, m, "Cinder Brand: Suppress Temporary HP"),
           pressure_pick("Suppress Temporary HP"))
    e = reload(c, m)
    foe = e.state.actors[RIGHT]
    (suppressed,) = [row for row in foe.conditions.values() if row.condition_id == ash_core.SUPPRESSED]
    amount = suppressed.data["amount"]
    assert 0 < amount < 40  # the hit's own damage came off the pool first
    assert foe.temporary_hp == 0
    assert suppressed.data["grant_source"] == "action:test.worker1.extra.Warding_Ash"
    assert suppressed.data["grant_expires"] is None  # an instant grant lasts until depleted

    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e.state.actors[RIGHT].temporary_hp == amount
    assert not any(row.condition_id == ash_core.SUPPRESSED for row in e.state.actors[RIGHT].conditions.values())


def test_suppressed_temporary_hp_does_not_return_after_its_source_printed_end(tmp_path):
    """A pool whose source ends while it is suppressed stays gone: the restore waits on the grant's
    own printed end, not just the start of the caster's next turn."""
    c, t, m = table(tmp_path, extra_actions=_warding_ash({"expires_on": "START_OF_TARGET_NEXT_TURN"}))
    settle(action_sender(c, t, m, "Warding Ash"))
    assert reload(c, m).state.actors[RIGHT].temporary_hp == 40
    settle(action_sender(c, t, m, "Cinder Brand: Suppress Temporary HP"),
           pressure_pick("Suppress Temporary HP"))
    e = reload(c, m)
    (suppressed,) = [row for row in e.state.actors[RIGHT].conditions.values()
                     if row.condition_id == ash_core.SUPPRESSED]
    assert suppressed.data["grant_expires"].startswith(f"START_OF_TURN_AT:{RIGHT}:")
    assert e.state.actors[RIGHT].temporary_hp == 0

    turn(t, m, RIGHT)  # the source's printed end arrives first
    turn(t, m, LEFT)   # then the suppression's own end
    e = reload(c, m)
    assert e.state.actors[RIGHT].temporary_hp == 0
    assert not any(row.condition_id == ash_core.SUPPRESSED for row in e.state.actors[RIGHT].conditions.values())
    assert not any(v.event_type == "TEMP_HP_GRANTED" and v.payload.get("restored_by") for v in e.events)
