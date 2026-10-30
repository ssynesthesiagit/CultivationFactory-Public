"""Native Pole delivery controls and legal-subject handoff regression.

Characters acquire the exact source feature in their portable sheet; all writes
use table intents. The Hidden instance in the No Blind Side regression is the
scene state "the Pole became Hidden from you", applied through the engine's own
condition event inside the committed turn (a test fixture, not a Hide action);
the attack roll, its mode receipts and every reload/replay are native.
"""
import json
import zipfile

import pytest

from combat import ext, senses, stealth
from combat import typed_executor as te
from combat.ext import compass_breaking_hand as compass
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_hidden_targeting import move_to, turn
from tests.test_lock9_passage_review import checked

FEATURE = "tianxia.tradition.spirit.compass_breaking_hand.feature.three_bearing_footwork"
MIND = "tianxia.path.spirit_awakening.feature.mind_spike"
OWNER = "actor:factory.aaaaaaaa"
ALLY = "actor:factory.bbbbbbbb"
FOE = "actor:factory.ffffffff"
POLE = "condition:typed.compass_pole"
BEARING = "condition:typed.compass_bearing"
HIDDEN = "condition:typed.hidden"
NO_OPPORTUNITY = "condition:typed.no_opportunity_attacks"


def native_table(tmp_path, *, owned=True):
    for pid in ("aaaaaaaa", "bbbbbbbb", "ffffffff"):
        ids = [MIND, *([FEATURE] if owned and pid == "aaaaaaaa" else [])]
        document = sheet(ids, cl=3, primary="Resonance", key="WIS", name=pid)
        document["identity"]["path"] = "Spirit Awakening"
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({
        "display_name": "Bearing verification hall", "width_squares": 12,
        "height_squares": 14, "walls": [],
        "starts": {"team1": [[1, 6], [2, 6]], "team2": [[6, 6]]},
    })
    mid = service.create_factory_match(
        project_ids=["aaaaaaaa", "bbbbbbbb"], opponent_actor_ids=[FOE],
        control_modes={actor: "MANUAL" for actor in (OWNER, ALLY, FOE)},
        arena_id="battlefield:map.bearing-verification-hall",
        match_seed="MGR-T14-BEARING-FOOTWORK",
    )["match_id"]
    ui = TabletopService(service, tmp_path)
    to_actor(ui, mid, OWNER)
    return service, ui, mid


@pytest.mark.parametrize("owned", [True, False])
def test_native_pole_acquisition_commit_cold_reload_and_replay(tmp_path, owned):
    service, ui, mid = native_table(tmp_path, owned=owned)
    engine = service._load_session(mid).engine
    rows = [row for row in engine.typed_passive_rows.get(OWNER, ())
            if row.get("kind") == "three_bearing_footwork"]
    assert [row["feature_id"] for row in rows] == ([FEATURE] if owned else [])
    candidates = [c for c in engine.legal_candidates() if c.display_name == "Choose Pole"]
    if not owned:
        assert not candidates
        assert not any(c.condition_id == POLE for c in checked(tmp_path, mid).state.actors[OWNER].conditions.values())
        return
    assert any(c.target_ids == (FOE,) for c in candidates)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    resonance, hp, position = actor.resources["resource:core.resonance"], target.current_hp, target.position
    target_conditions = target.conditions.copy()
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    engine = checked(tmp_path, mid)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    poles = [c for c in actor.conditions.values() if c.condition_id == POLE]
    assert len(poles) == 1 and poles[0].data["pole"] == FOE
    assert poles[0].source_actor_id == OWNER
    assert actor.resources["resource:core.resonance"] == resonance - 1
    assert not actor.bonus_action_available
    assert target.current_hp == hp and target.position == position
    assert target.conditions == target_conditions


def test_native_perceived_ally_is_a_legal_pole(tmp_path):
    """Printed Pole permits a companion; hostile benefits must be gated separately."""
    service, ui, mid = native_table(tmp_path)
    engine = service._load_session(mid).engine
    assert engine.state.actors[OWNER].team_id == engine.state.actors[ALLY].team_id
    assert any(c.display_name == "Choose Pole" and c.target_ids == (ALLY,)
               for c in engine.legal_candidates()), "Pole must allow a perceived ally, not only hostiles"
    commit(cast_sender(service, ui, mid, "Choose Pole", target=ALLY))
    actor = checked(tmp_path, mid).state.actors[OWNER]
    assert any(c.condition_id == POLE and c.data.get("pole") == ALLY for c in actor.conditions.values())
    # Choosing an ally is only a reference point; hostile-only strike/progress
    # remains inert when the owner damages that ally.
    ally = checked(tmp_path, mid).state.actors[ALLY]
    assert ally.team_id == actor.team_id
    assert actor.turn_flags.get("compass_strike_used") is not True
    assert actor.turn_flags.get("compass_pole_struck") is not True


# -------------------------------------------------------------------------------------------------- native duel fixtures
def duel(tmp_path, *, owned=True, starts=((1, 6), (2, 6)), objects=None, cl=3, owner_extra=()):
    """One owner (the feature) and one opponent; all table intents, no injected effects."""
    rows = (("aaaaaaaa", [FEATURE, MIND, *owner_extra] if owned else [MIND], starts[0]),
            ("ffffffff", [MIND], starts[1]))
    for pid, ids, spot in rows:
        document = sheet(ids, cl=cl, primary="Resonance", key="WIS", name=pid)
        document["identity"]["path"] = "Spirit Awakening"
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    document = {"display_name": "Bearing duel hall", "width_squares": 12, "height_squares": 14, "walls": [],
                "starts": {"team1": [list(starts[0])], "team2": [list(starts[1])]}}
    if objects:
        document["objects"] = objects
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save(document)
    mid = service.create_factory_match(
        project_ids=["aaaaaaaa"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"},
        arena_id="battlefield:map.bearing-duel-hall",
        match_seed="MGR-T14-BEARING-FOOTWORK",
    )["match_id"]
    ui = TabletopService(service, tmp_path)
    to_actor(ui, mid, OWNER)
    return service, ui, mid


def end_turn(ui, mid, bearing=None):
    """End the current turn, answering a turn-start Bearing question when one is asked."""
    answers = []
    for _ in range(30):
        state = ui.state(mid)
        menu = state["menu"]
        result = ui.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        ids = [option["id"] for option in (prompt.get("choice") or {}).get("options", [])]
        if bearing and set(ids) >= set(("approach", "orbit", "depart")):
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [bearing]})
        else:
            answers.append({**prompt["context"], "selection": "DECLINE"})
    raise AssertionError("the turn did not commit")


def to_actor(ui, mid, actor_id, bearing=None):
    for _ in range(30):
        if ui.state(mid)["menu"]["actor_id"] == actor_id:
            return
        end_turn(ui, mid, bearing)
    raise AssertionError(f"never reached {actor_id}")


def mark_pole(service, ui, mid, monkeypatch):
    """Choose the foe as Pole and mark it with the real Mind Spike action."""
    fixed_dice(monkeypatch, [1] * 400)
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE))
    engine = checked(service.userdata_root, mid)
    assert te.bears_mark(engine.state.actors[FOE], OWNER, "Resonance")
    return engine


# ---------------------------------------------------------------------------------------- No Blind Side (first attack only)
def _inject_hidden_on_turn_start(monkeypatch):
    def inject(engine, event_type, kwargs):
        if event_type != "TURN_STARTED" or kwargs.get("actor_id") != FOE:
            return
        foe = engine.state.actors[FOE]
        if not any(c.condition_id == HIDDEN for c in foe.conditions.values()):
            engine._apply_condition(foe, HIDDEN, "test:no-blind-side", FOE, expires_on="UNTIL_REMOVED")
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), inject])


def _keep_hidden_through_attacks(monkeypatch):
    # The documented observe-first-attack seam, used only to leave Hidden up for the second-attack control.
    monkeypatch.setitem(ext._HOOKS, "attack_reveal",
                        [*ext._HOOKS.get("attack_reveal", []), lambda ctx, target, hit: False])


def _hidden_advantage_receipts(roll):
    return [source for source in (roll.payload.get("mode_sources") or [])
            if source.get("kind") == "advantage" and source.get("effect") == "Hidden"]


def test_no_blind_side_suppresses_only_the_first_hidden_pole_attack(tmp_path, monkeypatch):
    service, ui, mid = duel(tmp_path, starts=((1, 6), (2, 6)))
    mark_pole(service, ui, mid, monkeypatch)
    _inject_hidden_on_turn_start(monkeypatch)
    _keep_hidden_through_attacks(monkeypatch)
    end_turn(ui, mid)
    engine = checked(service.userdata_root, mid)
    foe, owner = engine.state.actors[FOE], engine.state.actors[OWNER]
    assert stealth.hidden(foe)
    assert te.bears_mark(foe, OWNER, "Resonance")
    # Speculative option/tooltip queries see the suppression and spend nothing.
    before = len(engine.events)
    for _ in range(3):
        assert senses.masked_conditions(engine, foe, owner).get(FOE)
    assert len(engine.events) == before
    assert engine._attack_mode(foe, owner) == "NORMAL"
    commit(cast_sender(service, ui, mid, "Unarmed Strike", target=OWNER))
    engine = checked(service.userdata_root, mid)
    first = next(event for event in engine.events if event.event_type == "ATTACK_ROLLED")
    assert first.payload.get("mode") == "NORMAL"
    assert _hidden_advantage_receipts(first) == []
    assert stealth.hidden(engine.state.actors[FOE]), "the control keeps the same Hidden instance"
    # Same Hidden instance, second attack: the printed limit no longer applies.
    to_actor(ui, mid, OWNER)
    to_actor(ui, mid, FOE)
    engine = checked(service.userdata_root, mid)
    foe, owner = engine.state.actors[FOE], engine.state.actors[OWNER]
    assert senses.masked_conditions(engine, foe, owner) == {}
    assert engine._attack_mode(foe, owner) == "ADVANTAGE"
    commit(cast_sender(service, ui, mid, "Unarmed Strike", target=OWNER))
    engine = checked(service.userdata_root, mid)
    rolls = [event for event in engine.events if event.event_type == "ATTACK_ROLLED"]
    assert [roll.payload.get("mode") for roll in rolls] == ["NORMAL", "ADVANTAGE"]
    assert _hidden_advantage_receipts(rolls[-1]), "the second attack keeps Hidden's unseen Advantage"
    # Unseen-cause only: a fresh Hidden instance is masked, Invisible is not.
    # The mark from the opening Mind Spike has expired by this later turn, so
    # refresh the fixture's mark before asking the pure mask projection.
    engine._apply_condition(engine.state.actors[FOE], te.mark_condition_id("Resonance", OWNER), FEATURE, OWNER,
                            expires_on="UNTIL_REMOVED")
    before_hidden = {iid for iid, condition in engine.state.actors[FOE].conditions.items()
                     if condition.condition_id == HIDDEN}
    engine._apply_condition(engine.state.actors[FOE], HIDDEN, "test:no-blind-side", FOE, expires_on="UNTIL_REMOVED")
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.invisible", "test:no-blind-side", FOE, expires_on="UNTIL_REMOVED")
    foe = engine.state.actors[FOE]
    fresh_hidden = {iid for iid, condition in foe.conditions.items()
                    if condition.condition_id == HIDDEN} - before_hidden
    invisible_now = {iid for iid, condition in foe.conditions.items() if condition.condition_id == "condition:typed.invisible"}
    mask = senses.masked_conditions(engine, foe, engine.state.actors[OWNER])
    assert mask[FOE] == fresh_hidden and not (mask[FOE] & invisible_now)


def test_no_blind_side_is_inert_without_the_owner_tradition(tmp_path, monkeypatch):
    service, ui, mid = duel(tmp_path, owned=False, starts=((1, 6), (2, 6)))
    _inject_hidden_on_turn_start(monkeypatch)
    _keep_hidden_through_attacks(monkeypatch)
    end_turn(ui, mid)
    engine = checked(service.userdata_root, mid)
    assert stealth.hidden(engine.state.actors[FOE])
    assert senses.masked_conditions(engine, engine.state.actors[FOE], engine.state.actors[OWNER]) == {}
    commit(cast_sender(service, ui, mid, "Unarmed Strike", target=OWNER))
    engine = checked(service.userdata_root, mid)
    roll = next(event for event in engine.events if event.event_type == "ATTACK_ROLLED")
    assert roll.payload.get("mode") == "ADVANTAGE"
    assert _hidden_advantage_receipts(roll)


# ------------------------------------------------------------------------------------ Compass Strike: Mind Spike delivery
def test_mind_spike_is_a_martial_strike_for_approach_and_scoped_opportunity_denial(tmp_path, monkeypatch):
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)))
    mark_pole(service, ui, mid, monkeypatch)
    end_turn(ui, mid)
    end_turn(ui, mid, bearing="approach")
    engine = checked(service.userdata_root, mid)
    bearing = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BEARING)
    assert bearing.data["kind"] == "approach"
    move_to(ui, mid, (4, 6))
    engine = checked(service.userdata_root, mid)
    actor = engine.state.actors[OWNER]
    assert next(c for c in actor.conditions.values() if c.condition_id == BEARING).data["done"] == 1
    assert actor.resources.get("resource:named.bearing_approach", 0) == 1
    hp_before = engine.state.actors[FOE].current_hp
    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE))
    engine = checked(service.userdata_root, mid)
    foe, actor = engine.state.actors[FOE], engine.state.actors[OWNER]
    assert foe.current_hp < hp_before
    assert actor.turn_flags.get("compass_strike_used") is True
    assert any(event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == FEATURE for event in engine.events)
    held = [c for c in foe.conditions.values() if c.condition_id == NO_OPPORTUNITY]
    assert held and held[-1].data.get("against") == OWNER
    assert not any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values()), \
        "Enter the Line denies Opportunity Attacks against the practitioner, not every Reaction"


def test_orbit_expression_steps_to_a_legal_space_and_guards_against_the_pole(tmp_path, monkeypatch):
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)))
    mark_pole(service, ui, mid, monkeypatch)
    end_turn(ui, mid)
    end_turn(ui, mid, bearing="orbit")
    move_to(ui, mid, (1, 8))  # 10 ft, ending at the same 25-ft distance from the Pole
    engine = checked(service.userdata_root, mid)
    actor = engine.state.actors[OWNER]
    assert next(c for c in actor.conditions.values() if c.condition_id == BEARING).data["done"] == 1
    assert actor.resources.get("resource:named.bearing_orbit", 0) == 1
    before = actor.position

    def pick(prompt):
        ids = [option["id"] for option in (prompt.get("choice") or {}).get("options", [])]
        if ids and not ({"save", "step"} & set(ids)) and not ({"str", "wis"} & set(ids)):
            return (ids[0], True)  # the printed 5-foot step no longer offers "stay"
        return (None, False)

    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE), pick)
    engine = checked(service.userdata_root, mid)
    actor = engine.state.actors[OWNER]
    guard = next((c for c in actor.conditions.values() if c.condition_id == "condition:typed.compass_orbit_guard"), None)
    assert guard is not None and guard.data.get("against") == FOE
    assert actor.position != before, "Step Beyond the Angle moved to a legal space"
    assert actor.turn_flags.get("compass_strike_used") is True


@pytest.mark.parametrize("ability", ["str", "wis"])
def test_depart_asks_both_legal_save_abilities_and_reloads(tmp_path, monkeypatch, ability):
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)))
    mark_pole(service, ui, mid, monkeypatch)
    end_turn(ui, mid)
    end_turn(ui, mid, bearing="depart")
    engine = checked(service.userdata_root, mid)
    assert next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BEARING).data["kind"] == "depart"
    move_to(ui, mid, (0, 0))
    engine = checked(service.userdata_root, mid)
    assert next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BEARING).data["done"] == 1
    assert engine.state.actors[OWNER].resources.get("resource:named.bearing_depart", 0) == 1
    before = engine.state.actors[FOE].position
    offered = []

    def pick(prompt):
        ids = [option["id"] for option in (prompt.get("choice") or {}).get("options", [])]
        offered.append(set(ids))
        if {"save", "step"} <= set(ids):
            return ("save", True)
        if {"str", "wis"} <= set(ids):
            return (ability, True)
        return (None, False)

    commit(cast_sender(service, ui, mid, "Mind Spike", target=FOE), pick)
    engine = checked(service.userdata_root, mid)
    assert {"str", "wis"} in offered, "both printed saving throws must be offered to the player"
    saves = [event for event in engine.events
             if event.event_type == "SAVE_ROLLED" and event.source_definition_id == FEATURE]
    assert saves
    assert saves[-1].payload.get("reason") == f"SAVE:{FEATURE}:{ability.upper()}"
    assert saves[-1].payload.get("success") is False
    after = engine.state.actors[FOE].position
    assert after != before, "a failed Depart save moves the Pole 5 feet away from the practitioner"
    assert engine.grid.distance_ft(after, engine.state.actors[OWNER].position) > engine.grid.distance_ft(before, engine.state.actors[OWNER].position)


def test_depart_save_ability_is_automatic_for_an_ai_seat(tmp_path, monkeypatch):
    """A computer-controlled practitioner decides itself; no table prompt is left open."""
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)))
    mark_pole(service, ui, mid, monkeypatch)
    end_turn(ui, mid)
    end_turn(ui, mid, bearing="depart")
    move_to(ui, mid, (0, 0))
    checked(service.userdata_root, mid)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if "Mind Spike" in c.display_name and FOE in c.target_ids)
    real = service.controller

    class Selected:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    service.controller = Selected()
    service.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    prompts = commit(lambda answers=(): ui.auto_step(mid, ui.state(mid)["last_sequence"], list(answers)))
    assert prompts == [], "an AI seat must not leave the printed save-ability choice to the table"
    engine = checked(service.userdata_root, mid)
    saves = [event for event in engine.events
             if event.event_type == "SAVE_ROLLED" and event.source_definition_id == FEATURE]
    assert saves and saves[-1].payload.get("reason", "").endswith(":STR")


# ---------------------------------------------------------------------------------------------- legal Pole subject families
def test_object_cultivation_asset_and_anchor_are_legal_poles(tmp_path, monkeypatch):
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)),
                            objects=[{"id": 1, "x": 4, "y": 6, "kind": "custom", "name": "Practice block",
                                      "size": "medium", "material": "stone", "hp": 100, "ac": 10}])
    engine = service._load_session(mid).engine
    assert any(c.display_name == "Choose Pole: an object" for c in engine.legal_candidates())
    commit(cast_sender(service, ui, mid, "Choose Pole: an object"),
           lambda prompt: (prompt["choice"]["options"][0]["id"], True))
    engine = checked(service.userdata_root, mid)
    pole = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == POLE)
    assert pole.data.get("object") == "object:map.1"
    assert "Practice block" in pole.data.get("label", "")
    # The object is a reference subject: a Bearing can complete around it.
    end_turn(ui, mid)
    end_turn(ui, mid, bearing="approach")
    move_to(ui, mid, (3, 6))
    engine = checked(service.userdata_root, mid)
    actor = engine.state.actors[OWNER]
    assert next(c for c in actor.conditions.values() if c.condition_id == BEARING).data["done"] == 1
    assert actor.resources.get("resource:named.bearing_approach", 0) == 1


def test_object_pole_compass_strike_damages_the_object(tmp_path, monkeypatch):
    fixed_dice(monkeypatch, [20] * 400)  # the object attack must land
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)),
                            objects=[{"id": 1, "x": 4, "y": 6, "kind": "custom", "name": "Practice block",
                                      "size": "medium", "material": "stone", "hp": 100, "ac": 10}])
    commit(cast_sender(service, ui, mid, "Choose Pole: an object"),
           lambda prompt: (prompt["choice"]["options"][0]["id"], True))
    end_turn(ui, mid)
    end_turn(ui, mid, bearing="approach")
    move_to(ui, mid, (3, 6))
    hp_before = checked(service.userdata_root, mid).state.objects["object:map.1"].current_hp
    commit(cast_sender(service, ui, mid, "Attack an object", target="object:map.1"))
    engine = checked(service.userdata_root, mid)
    assert engine.state.objects["object:map.1"].current_hp < hp_before
    assert any(event.event_type == "PASSIVE_TRIGGERED"
               and str((event.payload or {}).get("log") or "").startswith("Compass Strike (Approach) against Practice block")
               for event in engine.events)
    updates = [event for event in engine.events
               if event.event_type == "OBJECT_UPDATED" and "object:map.1" in event.target_ids]
    assert len(updates) >= 2, "the object attack and the Compass Strike are separate object damage packets"


# --------------------------------------------------------------------------------------------- direction bands, no leakage
def test_marked_pole_direction_band_is_logged_without_its_exact_square(tmp_path, monkeypatch):
    service, ui, mid = duel(tmp_path, starts=((1, 6), (6, 6)))
    mark_pole(service, ui, mid, monkeypatch)
    end_turn(ui, mid)  # owner -> foe
    # The Pole's own voluntary move updates the band while the mark lasts.
    move_to(ui, mid, (10, 6))
    engine = checked(service.userdata_root, mid)
    moved = [event for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"
             and str((event.payload or {}).get("log") or "").startswith("Pole sense:")]
    assert moved and "30 to 60 feet away" in moved[-1].payload["log"]
    assert f"{engine.state.actors[FOE].position.x},{engine.state.actors[FOE].position.y}" not in moved[-1].payload["log"]
    # The start-of-turn sense gives direction and band, never the concealed square.
    end_turn(ui, mid)  # foe -> owner (the Bearing question is declined by the helper)
    engine = checked(service.userdata_root, mid)
    sense = [event for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"
             and str((event.payload or {}).get("log") or "").startswith("Pole sense:")]
    assert len(sense) >= 2
    text = sense[-1].payload["log"]
    foe = engine.state.actors[FOE]
    assert f"{foe.position.x},{foe.position.y}" not in text
    assert "30 to 60 feet away" in text


# --------------------------------------------------------------------------------------------- dormancy and recovery
def test_pole_dormant_resumes_when_the_pole_can_participate_again(tmp_path):
    service, ui, mid = duel(tmp_path)
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    engine = checked(service.userdata_root, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert compass.pole(engine, owner)[0] is foe
    foe.active = False
    assert compass.pole_dormant(engine, owner) is True
    assert compass.pole(engine, owner) == (None, None)
    foe.active = True
    assert compass.pole_dormant(engine, owner) is False
    assert compass.pole(engine, owner)[0] is foe
