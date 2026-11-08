"""Public synthetic table regressions for explicit augment-version clicks."""
import json
import subprocess

import pytest

from combat import loadout, status_text
from combat.tabletop import TabletopError
from tests.lighting_darkness_support import synthetic_darkness_rules
from tests.lighting_support import ambient_light, fight, map_document, OWNER
from tests.worker2_support import reload


GREATER = "TAL_DARK_GREATER_DARKNESS"
PERSISTENT = "TAL_DARK_PERSISTENT_DARKNESS"


@pytest.fixture
def versions(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    with synthetic_darkness_rules(tmp_path, monkeypatch):
        # Extend the scoped printed-rules fixture shared by compiler and UI.
        # Public exports redact headings used by the legacy augment classifier.
        rules = {
            **status_text.printed_rules(),
            GREATER: "### Greater Darkness - Augment\nAugment - 1 CP: Increase the radius to 30 feet.",
            PERSISTENT: "### Persistent Darkness\nAugment - 2 CP: Darkness persists without Concentration.",
        }
        status_text.RULES_TEXT_PATH.write_text(json.dumps(rules))
        combat, table, mid = fight(tmp_path, map_document(10, 8, ambient=ambient_light("day")),
                                   talents=[GREATER, PERSISTENT], seed="VARIANT-PICK")
        engine = combat._load_session(mid).engine
        base, family = next((base, row) for base, row in loadout.families(engine)[OWNER]
                            if engine.action_catalog[base].display_name == "Darkness")
        yield combat, table, mid, base, family


def click(table, mid, source, request):
    menu = table.state(mid, lazy=True)["menu"]
    return table.select_ability_version(mid, dict(actor_id=OWNER, decision_id=menu["decision_id"],
        state_version=menu["state_version"], source_definition_id=source, sources=[], request_id=request))


def test_version_click_replaces_chosen_set_aims_own_targets_and_casts_own_cost(versions, tmp_path, monkeypatch):
    combat, table, mid, base, family = versions
    a = family["combos"][GREATER]
    b = family["combos"]["|".join(sorted([GREATER, PERSISTENT]))]
    click(table, mid, a, "choose-a")
    engine = reload(tmp_path, mid)
    assert loadout.chosen(engine.state.actors[OWNER], base) == [GREATER]
    assert b in loadout.hidden(engine, engine.state.actors[OWNER])

    # Selection must enumerate targets for this source alone; the returned
    # live menu may discover other sources, but never expand their targets.
    from combat.gate4_engine import Gate4ControllerEngine
    original = Gate4ControllerEngine.action_candidates_for_sources
    scoped = []
    def record(self, sources):
        scoped.append(set(sources))
        return original(self, sources)
    monkeypatch.setattr(Gate4ControllerEngine, "action_candidates_for_sources", record)
    before = dict(engine.state.actors[OWNER].resources)
    reply = click(table, mid, b, "choose-b")
    assert scoped == [{b}]
    assert {g["source_definition_id"] for g in reply["menu"]["actions"]} == {b}
    assert reply["state"]["menu"]["augment_versions"][b]["selected"]
    expanded = next(g for g in reply["state"]["menu"]["actions"] if g["source_definition_id"] == b)
    assert not expanded["lazy"] and expanded["expanded_from_lazy"], "Unchanged polls must retain the open targets"
    assert reply["state"]["menu"]["end_turn"], "Other legal options must remain reachable"
    options = [o for g in reply["menu"]["actions"] for o in g["options"]]
    assert options and all(o.get("area") for o in options)
    # No CP or action is spent until the player actually picks a target.
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert set(loadout.chosen(actor, base)) == {GREATER, PERSISTENT}
    assert actor.resources == before and actor.action_available
    assert b not in loadout.hidden(engine, actor) and a in loadout.hidden(engine, actor)
    assert "chosen set" not in reply["state"]["unavailable_reasons"].get("act:" + b, "")
    expected = engine.action_candidates_for_sources({b})
    assert {o["candidate_id"] for o in options} == {c.candidate_id for c in expected}
    option = options[0]
    menu = reply["menu"]
    result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "COMMITTED", result
    cold = reload(tmp_path, mid)
    costs = engine.action_catalog[b].costs
    assert sum(amount for _, amount in costs) == 3
    assert all(cold.state.actors[OWNER].resources[rid] == before[rid] - amount for rid, amount in costs)
    assert not cold.state.actors[OWNER].action_available
    zones = [z for z in cold.state.zones.values() if z.source_definition_id == b]
    assert zones and all(not z.concentration_link for z in zones)


def test_invalid_unaffordable_stale_and_ai_version_clicks_do_not_save(versions, tmp_path, monkeypatch):
    combat, table, mid, base, family = versions
    # Spend nothing: a forged/unowned version must never become a chosen set.
    path = combat._load_session(mid).store.journal_path
    before = path.read_bytes()
    with pytest.raises(TabletopError, match="does not own"):
        click(table, mid, base + "+aug.not-owned", "unowned")
    assert path.read_bytes() == before

    # Use the real projection with insufficient CP, without changing saved data.
    original = combat._clone_engine
    def poor(root, engine):
        probe = original(root, engine)
        probe.state.actors[OWNER].resources = {key: 0 for key in probe.state.actors[OWNER].resources}
        return probe
    monkeypatch.setattr(combat, "_clone_engine", poor)
    with pytest.raises(TabletopError, match="Requires") as error:
        click(table, mid, family["combos"][PERSISTENT], "too-poor")
    assert "chosen set" not in str(error.value)
    assert path.read_bytes() == before
    monkeypatch.setattr(combat, "_clone_engine", original)

    menu = table.state(mid, lazy=True)["menu"]
    payload = dict(actor_id=OWNER, decision_id=menu["decision_id"], state_version=menu["state_version"],
        source_definition_id=base, sources=[], request_id="stale")
    with pytest.raises(TabletopError, match="fight changed"):
        table.select_ability_version(mid, {**payload, "state_version": menu["state_version"] + 1})
    assert path.read_bytes() == before
    # AI selection guards run before any settings journal entry.
    session = combat._load_session(mid)
    monkeypatch.setitem(session.engine.typed_control_modes, OWNER, "LOCAL_AUTO")
    monkeypatch.setattr(combat, "_load_session", lambda _: session)
    with pytest.raises(TabletopError, match="player-controlled"):
        table.select_ability_version(mid, payload)
    assert path.read_bytes() == before


def test_version_click_client_entrypoints():
    result = subprocess.run(["node", "--test", "tests/variant_pick.test.mjs"],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
