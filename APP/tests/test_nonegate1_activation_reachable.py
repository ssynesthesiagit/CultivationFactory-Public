"""Printed free activations keep a route without turning automatic riders into actions.

The cue guard is scoped to NONE/no_action/free_action typed rows. Trigger-bound
choices and prerequisites absent on a minimal table have individually reviewed
exemptions; hashes force re-review when their printed clauses change. This is a
primary-menu guard, not a claim that every triggered clause is fully automated.
"""
import hashlib
import json
import re
from pathlib import Path

from combat.gate2_runtime_models import ActionDefinition
from combat.primary_intents import allows_primary
from tests.h1_support import mechanics
from tests.nonegate1_activation_exemptions import EXEMPTIONS
from tests import hunt28_support as harness
from tests.hunt31_support import OWNER, fixture, reload
from tests.test_a2_hunger import BASE, SAT, CP, play

ROOT = Path(__file__).resolve().parents[1]
CUE = re.compile(
    r"\byou may\b|\bfree action\b|\bchoose\b|\bactivat(?:e|ion)\b|"
    r"\bwithout (?:spending |using )?an? action\b", re.I)
RIVALRY = "tianxia.talent.beauty.radiant_rivalry"
PRIMARY_MENUS = {RIVALRY: "Radiant Rivalry"}


def test_every_cued_none_row_has_a_menu_or_documented_exemption(tmp_path):
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    exemptions = EXEMPTIONS
    checked = set()
    for source, row in mechanics().items():
        if str((row.get("activation") or {}).get("economy")).lower() not in {
                "none", "no_action", "free_action"}:
            continue
        text = texts.get(source) or texts.get(source.split("#")[0], "")
        if not CUE.search(text):
            continue
        checked.add(source)
        if source in exemptions:
            exemption = exemptions[source]
            assert exemption["reason"].strip(), source
            assert exemption["printed_sha256"] == hashlib.sha256(text.encode()).hexdigest(), (
                source, "Printed rules changed; review the primary-menu exemption.")
            continue
        assert source in PRIMARY_MENUS, (source, "Printed activation has no primary-menu coverage or exemption.")
        combat, table, mid = harness.fixture(tmp_path / source, [source])
        assert PRIMARY_MENUS[source] in {g["label"] for g in table.state(mid)["menu"]["actions"]}
        action = next(a for a in combat._load_session(mid).engine.action_catalog.values()
                      if a.owner_id == OWNER and a.display_name == PRIMARY_MENUS[source])
        assert allows_primary(action)
    assert checked == set(exemptions) | set(PRIMARY_MENUS)


def test_hunger_paid_options_reach_owner_menu_and_pay_once(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [BASE], resources={SAT: 8})
    state = table.state(mid)
    expected = {"Digestive Mantle: " + benefit for benefit in (
        "Beast Strength", "Predator Step", "Iron Stomach", "Thick Hide",
        "Venom Belly", "Furnace Belly", "Elemental Gut", "Deep Nourishment", "Demon-Beast Course")}
    assert expected <= {g["label"] for g in state["menu"]["actions"]}
    engine = reload(combat, mid)
    before = engine.state.actors[OWNER].resources[CP]
    for action in engine.action_catalog.values():
        if action.owner_id == OWNER and action.display_name in expected:
            assert action.economy == "BONUS_ACTION" and allows_primary(action)
    actor = play(combat, table, mid, "Digestive Mantle: Thick Hide").state.actors[OWNER]
    assert actor.resources[CP] == before - 1 and actor.resources[SAT] == 7
    assert not actor.bonus_action_available


def test_hunger_scenario_packets_explicitly_declare_free_permission(monkeypatch, tmp_path):
    # This fixture executes Prepare before returning. It used to fail there,
    # before a real Mantle could be selected, then on its unsealed damage probes.
    from tests.test_a2_hunger_second_pass import table_fixture, KING
    combat, table, mid = table_fixture(monkeypatch, tmp_path, [BASE, KING])
    engine = reload(combat, mid)
    probes = [a for a in engine.action_catalog.values()
              if a.source_definition_id.startswith(("action:test.h31.prepare.", "action:test.hunger_second."))]
    assert probes and all(a.parameters.get("free_primary") is True for a in probes)
    assert "Digestive Mantle: Thick Hide" in {g["label"] for g in table.state(mid)["menu"]["actions"]}


def test_match_start_door_declarations_keep_free_menu_route_across_reload(tmp_path):
    from tests.test_door_interaction import setup, cold, choices, execute
    from combat.tabletop_service import TabletopService
    service, session = setup(tmp_path)
    menu = TabletopService(service, tmp_path).state(session.match_id)["menu"]
    assert any(g["source_definition_id"] == "system:door.open.free" for g in menu["actions"])
    action = session.engine.action_catalog["system:door.open.free"]
    assert action.parameters.get("free_primary") is True and allows_primary(action)
    execute(session, next(c for c in choices(session, "open") if c.source_definition_id.endswith(".free")))
    session = cold(tmp_path, session)
    assert session.engine.state.actors[session.engine.state.current_actor_id].action_available
    assert {c.source_definition_id for c in choices(session, "close")} == {"system:door.close.utilize"}


def test_none_is_still_not_permission_for_unowned_automatic_effect_packets():
    action = ActionDefinition(source_definition_id="action:test.trigger_packet",
        display_name="Triggered damage packet", owner_id="actor:test",
        economy="NONE", resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "damage", "flat": 5}]}})
    assert not allows_primary(action)
