"""Actual abilities through table commits, history formatting and fresh reload."""
import pytest
from tests.hunt15_support import ALLY, LEFT, RIGHT, act, action_sender, fight, reload, turn


@pytest.mark.parametrize("ai", [False, True])
def test_locking_gate_success_is_a_plain_notice(tmp_path, ai):
    combat, table, mid = fight(tmp_path, ["FORMATIONS_BASE_SET_ARRAY"])
    turn(table, mid, LEFT)
    # Array placement is a player's spatial choice. Its successful notice must
    # remain correct after an ordinary AI action on the following turn as well.
    result = act(table, mid, "Combat Array: Locking Gate")
    assert result["status"] == "COMMITTED"
    if ai:
        assert act(table, mid, "end")["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.zones and engine.state.objects
    lines = [r for r in table.events(mid, 0)["events"] if "Array set at" in r["summary"]]
    assert lines and all("Not automated" not in r["summary"] and "skipped" not in r["summary"] for r in lines)


@pytest.mark.parametrize("ai", [False, True])
def test_indomitable_save_reroll_has_both_rolls_in_history(tmp_path, ai):
    combat, table, mid = fight(tmp_path, ["tianxia.path.body_refining.feature.indomitable_body"],
        primary="Stamina", effects=[{"type": "save", "ability": "dex", "applies_to": "target", "dc": 100,
        "on_fail": [{"type": "damage", "damage_type": "PSYCHIC", "flat": 1, "applies_to": "target"}]}], target="HOSTILE_ENTITY")
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Test setup", ai=ai)
    answers = []
    for _ in range(10):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        p = result["reaction"]
        answers.append({**p["context"], "selection": "USE" if p["reaction"] == "Indomitable Body" else "DECLINE"})
    assert result["status"] == "COMMITTED"
    engine = reload(combat, mid)
    event = next(e for e in engine.events if e.event_type == "D20_REWRITTEN")
    row = next(r for r in table.events(mid, 0)["events"] if r["event_sequence"] == event.sequence)
    assert row["detailed_breakdown_recorded"]
    assert "Indomitable Body" in row["summary"]
    for roll in (event.payload["original"], event.payload["result"]):
        assert str(roll["natural_result"]) in row["summary"] and str(roll["total"]) in row["summary"]


@pytest.mark.parametrize("ai", [False, True])
def test_soul_gaze_names_the_creature(tmp_path, ai):
    # Exercise the shipped reveal effect against a creature; the generic compiler
    # currently classifies Soul Gaze as ALLY_OR_SELF (a separate targeting issue).
    combat, table, mid = fight(tmp_path, ["tianxia.path.spirit_awakening.feature.soul_gaze"], primary="Resonance",
                              effects=[{"type": "soul_gaze_reveal", "applies_to": "target"}], target="HOSTILE_ENTITY")
    turn(table, mid, LEFT)
    assert action_sender(combat, table, mid, "Test setup", ai=ai, target_id=RIGHT)([])["status"] == "COMMITTED"
    reload(combat, mid)
    row = next(r for r in table.events(mid, 0)["events"] if "Soul Gaze on" in r["summary"])
    assert "Visiting Fighter" in row["summary"] and RIGHT not in row["summary"]


@pytest.mark.parametrize("ai", [False, True])
def test_real_soul_gaze_can_diagnose_an_enemy(tmp_path, ai):
    """Printed 'one creature you can see' includes enemies, without a stand-in action.

    Promoted from FIX15's strict expected failure by the creature-target seam.
    """
    combat, table, mid = fight(tmp_path,
        ["tianxia.path.spirit_awakening.feature.soul_gaze"], primary="Resonance")
    turn(table, mid, LEFT)
    options = [o for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Soul Gaze" for o in g["options"]]
    assert any(RIGHT in o.get("target_ids", []) for o in options), \
        "Soul Gaze must offer the visible enemy as well as friendly creatures"
    before = reload(combat, mid).state.actors[LEFT].resources["resource:core.resonance"]
    assert action_sender(combat, table, mid, "Soul Gaze", ai=ai,
                         target_id=RIGHT)([])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources["resource:core.resonance"] == before - 1
    row = next(r for r in table.events(mid, 0)["events"] if "Soul Gaze on" in r["summary"])
    assert "Visiting Fighter" in row["summary"] and RIGHT not in row["summary"]


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("target_id,name", [
    (LEFT, "River Keeper"),
    (ALLY, "Guarding Friend"),
])
def test_real_soul_gaze_preserves_visible_friendly_targets(tmp_path, ai, target_id, name):
    """The future unrestricted-target seam must retain allies and self."""
    combat, table, mid = fight(tmp_path,
        ["tianxia.path.spirit_awakening.feature.soul_gaze"], primary="Resonance", ally=[])
    turn(table, mid, LEFT)
    before = reload(combat, mid).state.actors[LEFT].resources["resource:core.resonance"]
    assert action_sender(combat, table, mid, "Soul Gaze", ai=ai,
                         target_id=target_id)([])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources["resource:core.resonance"] == before - 1
    rows = [r for r in table.events(mid, 0)["events"] if "Soul Gaze on" in r["summary"]]
    assert rows, "Soul Gaze must diagnose the selected creature, including self"
    row = rows[0]
    assert f"Soul Gaze on {name}:" in row["summary"] and target_id not in row["summary"]


@pytest.mark.parametrize("ai", [False, True])
def test_real_soul_gaze_rejects_an_unseen_unmarked_ally(tmp_path, ai):
    """Clear map geometry alone does not satisfy 'one creature you can see'."""
    from combat import senses
    from combat.typed_executor import bears_mark

    combat, table, mid = fight(tmp_path,
        ["tianxia.path.spirit_awakening.feature.soul_gaze"], primary="Resonance", ally=[],
        effects=[{"type": "condition", "condition": "invisible", "applies_to": "self",
                  "expires_on": "UNTIL_REMOVED"}])
    turn(table, mid, ALLY)
    assert action_sender(combat, table, mid, "Test setup", ai=ai)([])["status"] == "COMMITTED"
    if ai:
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    observer, target = engine.state.actors[LEFT], engine.state.actors[ALLY]
    assert any(c.condition_id == "condition:typed.invisible" for c in target.conditions.values())
    assert not senses.sees_hidden(engine, observer, target)
    assert not bears_mark(target, LEFT, "Resonance")
    options = [o for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Soul Gaze" for o in g["options"]]
    assert not any(ALLY in o.get("target_ids", []) for o in options), \
        "Soul Gaze must not offer an unseen ally without the caster's Resonance Mark"
    assert any(LEFT in o.get("target_ids", []) for o in options)


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("marker", [LEFT, RIGHT])
def test_real_soul_gaze_only_preserves_the_casters_mark_exception(tmp_path, ai, marker):
    """Committed own marks allow Invisible allies; someone else's marks do not."""
    from combat.typed_executor import bears_mark

    combat, table, mid = fight(tmp_path,
        ["tianxia.path.spirit_awakening.feature.soul_gaze"], primary="Resonance", ally=[],
        target="ALLY_OR_SELF" if marker == LEFT else "HOSTILE_ENTITY",
        effects=[{"type": "condition", "condition": "invisible", "applies_to": "target",
                  "expires_on": "UNTIL_REMOVED"},
                 {"type": "mark", "mark": "Resonance", "applies_to": "target",
                  "duration": {"kind": "until_removed"}}])
    turn(table, mid, marker)
    assert action_sender(combat, table, mid, "Test setup", ai=ai,
                         target_id=ALLY)([])["status"] == "COMMITTED"
    if ai:
        combat.set_controller_mode(mid, actor_id=marker, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert bears_mark(engine.state.actors[ALLY], marker, "Resonance")
    assert any(c.condition_id == "condition:typed.invisible"
               for c in engine.state.actors[ALLY].conditions.values())
    options = [o for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Soul Gaze" for o in g["options"]]
    assert any(ALLY in o.get("target_ids", []) for o in options) == (marker == LEFT)
    # An unrelated action can still select the Invisible ally.
    if marker == LEFT:
        assert any(ALLY in o.get("target_ids", []) for g in table.state(mid)["menu"]["actions"]
                   if g["label"] == "Test setup" for o in g["options"])
        before = engine.state.actors[LEFT].resources["resource:core.resonance"]
        assert action_sender(combat, table, mid, "Soul Gaze", ai=ai,
                             target_id=ALLY)([])["status"] == "COMMITTED"
        engine = reload(combat, mid)
        assert engine.state.actors[LEFT].resources["resource:core.resonance"] == before - 1
        assert any("Soul Gaze on Guarding Friend:" in r["summary"]
                   for r in table.events(mid, 0)["events"])


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("revealing_sense", [False, True])
@pytest.mark.parametrize("condition,holder", [("invisible", ALLY), ("blinded", LEFT)])
def test_real_soul_gaze_uses_shared_senses(tmp_path, ai, revealing_sense, condition, holder):
    from combat import senses

    owned = ["tianxia.path.spirit_awakening.feature.soul_gaze"]
    if revealing_sense:
        owned.append("tianxia.path.spirit_awakening.feature.spiritual_sense")
    combat, table, mid = fight(tmp_path, owned, primary="Resonance", ally=[],
        effects=[{"type": "condition", "condition": condition, "applies_to": "self",
                  "expires_on": "UNTIL_REMOVED"}])
    turn(table, mid, holder)
    assert action_sender(combat, table, mid, "Test setup", ai=ai)([])["status"] == "COMMITTED"
    if ai:
        combat.set_controller_mode(mid, actor_id=holder, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    observer, target = engine.state.actors[LEFT], engine.state.actors[ALLY]
    assert any(c.condition_id == f"condition:typed.{condition}"
               for c in engine.state.actors[holder].conditions.values())
    assert senses.perceives_without_sight(engine, observer, target) == revealing_sense
    options = [o for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Soul Gaze" for o in g["options"]]
    assert any(ALLY in o.get("target_ids", []) for o in options) == revealing_sense
    if revealing_sense:
        before = observer.resources["resource:core.resonance"]
        assert action_sender(combat, table, mid, "Soul Gaze", ai=ai,
                             target_id=ALLY)([])["status"] == "COMMITTED"
        assert reload(combat, mid).state.actors[LEFT].resources["resource:core.resonance"] == before - 1
        assert any("Soul Gaze on Guarding Friend:" in r["summary"]
                   for r in table.events(mid, 0)["events"])


@pytest.mark.parametrize("ai", [False, True])
def test_flowing_response_setting_status_describes_the_move_after_reload(tmp_path, ai):
    combat, table, mid = fight(tmp_path, ["TAL_FLOWING_RIVER_FLOWING_RESPONSE"])
    turn(table, mid, LEFT)
    assert act(table, mid, "Flowing Response: step away")["status"] == "COMMITTED"
    if ai:
        # Settings belong to the player. Check the persisted pill while the
        # opponent's ordinary AI decision goes through the table boundary.
        assert act(table, mid, "end")["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        result = table.auto_step(mid, table.state(mid)["last_sequence"])
        answers = []
        for _ in range(10):
            if result["status"] != "REACTION_REQUIRED":
                break
            answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
            result = table.auto_step(mid, table.state(mid)["last_sequence"], answers)
        assert result["status"] == "COMMITTED"
    reload(combat, mid)
    row = next(c for a in table.state(mid)["presentation"]["actors"] for c in a["conditions"]
               if c["condition_id"] == "condition:typed.flowing_response_step")
    assert row["rule_text"] and "5 feet" in row["rule_text"]
    assert "Opportunity Attacks" in row["rule_text"]
    assert row["source_ability"] == "Flowing Response"
