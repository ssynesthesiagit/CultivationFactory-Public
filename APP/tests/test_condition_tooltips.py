"""Mapped condition tooltip coverage (owner playtest MMX85), verified at the real boundary.

The owner hovered "Golden Core" in round 24 and got no tooltip. Golden Core is the
``golden_core_form`` condition, and the one shared resolver every surface uses --
``conditionText()`` in static/tabletop/tabletop.js -- reads a single catalog that the
``/api/tabletop/conditions`` endpoint serves. Any key missing from that catalog renders its
chip without a per-row detail with an empty ``title``. Real selector rows have their own
detail, which must preserve its printed source rules.

This file deliberately keeps three separate layers, because each one can fail on its own:

* the real endpoint plus a real Golden Core table row, run through the SHIPPED resolver under
  ``node`` (``test_golden_core_hover_text_reaches_the_real_table_row``). This is the level the
  owner saw, and it is the only test that can catch a break in the endpoint wiring, the table
  row, or the resolver itself.
* an engine-level semantic test for Opportunity Attack suppression (``test_opportunity_attack...``).
  The reading used to state the reverse of what the engine does, and a catalog-only test cannot
  catch a sentence that is confidently wrong.
* cheap unit guards over the catalog itself, including a negative control that removes a key to
  prove the guard would notice.

``tests/condition_tooltip_resolver.test.mjs`` holds the resolver harness; it is run as a
subprocess, never reimplemented here. A first attempt at this regression transcribed
``conditionText()`` into Python and called ``all_conditions()`` directly, which skipped the
endpoint, the table row and the resolver's own ``row.detail`` precedence -- the MMX85f1 review
finding that produced the harness above.
"""
import json
import os
import pathlib
import subprocess
from types import SimpleNamespace

import pytest

from combat.condition_text import (READING, all_conditions,
                                   extension_readings)
from combat.ext.generated_status_text import SOURCES

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "tests/condition_tooltip_resolver.test.mjs"

# Internal structural markers. They are never applied to a creature as a condition, so the
# table never draws a chip for them and no player ever hovers one. "held" looks like
# condition:typed.held but the engine's real condition is condition:typed.concentration_held
# (combat/concentration.py), which has its own reading; "shared_occupancy" is a hook marker
# for a rider and mount sharing a square (combat/ext/mounts.py) and is never applied.
INTERNAL_ONLY = {"held", "shared_occupancy"}

# Extension condition keys that contain a dot. The shipped resolver looks a chip up by the
# LAST dot-separated component of its condition id (tabletop.js: `split(".").pop()`), but the
# catalog stores these under their full dotted key, so the lookup misses and their hover is
# blank when there is no row.detail. The catalog text is present -- this is a key-resolution gap in the client,
# inherited from before MMX85 and not fixed here. It is pinned as a named list so the gap stays
# visible and the "every condition is covered" claim stays honest (MMX85f1 review).
DOTTED_KEYS_UNRESOLVED_BY_CLIENT = {
    "stance.golden_bell_circulation",
    "wenxue.saber_line_guard_choice",
    "wenxue.hard_draw_ready",
}

GOLDEN = "tianxia.path.qi_cultivation.feature.golden_core_form"
GOLDEN_CONDITION = "condition:typed.golden_core_form"


# ----------------------------------------------------------------------- the real boundary
@pytest.fixture(scope="module")
def conditions_endpoint(tmp_path_factory):
    """The catalog exactly as ``GET /api/tabletop/conditions`` serves it over HTTP."""
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings

    data = tmp_path_factory.mktemp("conditions-endpoint")
    app = create_app(Settings.from_env(ROOT, data))
    with TestClient(app) as client:
        response = client.get("/api/tabletop/conditions")
        assert response.status_code == 200, response.text
        payload = response.json()
    assert payload["schema"] == "TianxiaTabletopConditions.v1"
    return payload["conditions"]


def _golden_core_table_row(tmp_path):
    """A real Golden Core condition row, produced by a real table action and read back off the table."""
    from tests.h52_identity_support import character, commit, fight, option, turn_of

    owner = character("85a00001", "Qi Learner", [GOLDEN], cl=10)
    foes = [character("85a00002", "Sparring Partner", [], cl=10),
            character("85a00003", "Second Foe", [], cl=10)]
    _user, _service, table, mid, owner_id = fight(tmp_path, [owner, *foes], "MMX85f1-GOLDEN")
    state = turn_of(table, mid, owner_id)
    commit(table, mid, option(state, "Golden Core Form: Circulating Golden Core"))
    actors = table.state(mid)["presentation"]["actors"]
    me = next(actor for actor in actors if actor["entity_id"] == owner_id)
    row = next(r for r in me["conditions"] if r.get("condition_id") == GOLDEN_CONDITION)
    return row, table, _service, mid, owner_id


def _run_shipped_resolver(catalog, rows, *, expect_nonempty=True):
    """Run the shipped ``conditionText`` over ``rows`` with ``catalog``, and return the hover titles.

    Both payloads go through standard input, without scratch files. ``expect_nonempty`` is False only for the
    negative control, which deliberately removes a catalog entry and wants a blank title back.
    """
    result = subprocess.run(["node", str(RESOLVER)], cwd=ROOT, env={
        **os.environ, "MMX85_EXPECT_NONEMPTY": "1" if expect_nonempty else "0"},
        input=json.dumps({"conditions": catalog, "rows": rows}), capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("MMX85_RESOLVED "))
    return json.loads(line.removeprefix("MMX85_RESOLVED "))


def test_golden_core_hover_text_reaches_the_real_table_row(tmp_path, conditions_endpoint):
    """The reported bug, end to end: a real Golden Core chip, the real endpoint, the real resolver.

    Fails without the endpoint serving the entry, without the row reaching the table, and without the
    resolver reading it -- which a unit call to ``all_conditions()`` could not do.

    Two hover paths are checked, because the table really has both. ``conditionText`` returns
    ``row.detail`` when the row carries one, and that is what a Golden Core chip raised by the
    Qi path buttons gets: the setting's own description, which already quotes the printed rule.
    A row without that description -- an older saved fight, or any surface that sends the bare
    condition -- falls through to the endpoint catalog, which is the entry this lane adds. Both
    must produce readable text, so neither path is allowed to go blank.
    """
    row, table, service, mid, owner_id = _golden_core_table_row(tmp_path)
    from combat.canonical import canonical_sha256
    session = service._load_session(mid)
    state_before = canonical_sha256(session.engine.state.model_dump(mode="json"))
    events_before = canonical_sha256([event.model_dump(mode="json") for event in session.engine.events])

    # The chip really is on the table and really is the condition the owner hovered.
    assert row["condition_id"] == GOLDEN_CONDITION
    assert row["display_name"].startswith("Golden Core Form:")
    # The endpoint must actually serve the entry, or the negative control below would pass vacuously.
    assert "golden_core_form" in conditions_endpoint, "the endpoint does not serve the Golden Core entry"

    # Path 1: the row as the table really ships it, detail and all.
    [shipped] = _run_shipped_resolver(conditions_endpoint, [row])
    assert shipped["title"], "the Golden Core chip has an empty hover"
    assert "Choose one Golden Core Form." in shipped["title"]
    assert "Golden Core Reservoir" in shipped["title"], "the printed rule is missing from the hover"

    # Path 2: no per-row description, so the resolver must fall back to the endpoint's catalog.
    catalog_only = {k: v for k, v in row.items() if k != "detail"}
    assert not catalog_only.get("detail")
    [from_catalog] = _run_shipped_resolver(conditions_endpoint, [catalog_only])
    assert from_catalog["title"], "Golden Core has no hover when the row carries no detail"
    assert from_catalog["title"].startswith("CL10 — Golden Core Form")
    assert "Golden Core Reservoir" in from_catalog["title"]

    # The setting action already committed; a fresh service must show the same hover
    # without changing combat state or the committed events.
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    resumed = TabletopService(CombatService(service.source_root, service.userdata_root), service.userdata_root)
    actors = resumed.state(mid)["presentation"]["actors"]
    me = next(actor for actor in actors if actor["entity_id"] == owner_id)
    reloaded = next(r for r in me["conditions"] if r.get("condition_id") == GOLDEN_CONDITION)
    assert _run_shipped_resolver(conditions_endpoint, [reloaded])[0]["title"] == shipped["title"]
    loaded = resumed.combat._load_session(mid)
    assert canonical_sha256(loaded.engine.state.model_dump(mode="json")) == state_before
    assert canonical_sha256([event.model_dump(mode="json") for event in loaded.engine.events]) == events_before


def test_the_golden_core_regression_notices_a_broken_catalog(conditions_endpoint, tmp_path):
    """Negative control: the test above is real, not a tautology.

    Drop the Golden Core entry from the served catalog and the shipped resolver must go blank on
    the catalog path -- the same empty hover the owner saw.
    """
    row, *_ = _golden_core_table_row(tmp_path)
    catalog_only = {k: v for k, v in row.items() if k != "detail"}
    broken = {k: v for k, v in conditions_endpoint.items() if k != "golden_core_form"}
    assert _run_shipped_resolver(broken, [catalog_only], expect_nonempty=False)[0]["title"] == ""


# ----------------------------------------------------------------------- Stone Womb ending rules
def test_stone_shell_hover_says_how_the_protection_ends(conditions_endpoint):
    """The shell's three early-ending rules, on the hover a player actually reads.

    The engine's evidence sentence names the file that implements the shell as its subject
    ("combat/ext/stone_womb.py ends it early on healing, ..."), so the shared cleaners have to drop
    the file and keep the predicate. A cleaner that dropped the whole parenthetical instead served a
    hover that said only "cannot move or take actions": nothing told the player that healing ends
    the shell or how much damage breaks it, so a player who did either had no warning (SOL123f1
    review finding). The assertions are the rules themselves rather than a comparison with whatever
    the catalog happens to hold, because two surfaces that omit the same rule still compare equal.
    """
    served = conditions_endpoint["stone_shell"]
    shown = " ".join([served.get("reading") or "", *(served.get("mechanics") or [])])
    # What the engine really enforces (combat/ext/stone_womb.py stone_shell_end).
    assert "healing" in shown, shown
    assert "dismissal" in shown, shown
    assert "damage equal to 10 + the Source key ability modifier + Proficiency Bonus" in shown, shown
    # The file that implements it is not part of the sentence, and neither is its shorthand.
    assert ".py" not in shown and "Source key modifier" not in shown and "PB" not in shown, shown

    # The same three rules through the shipped resolver, on a row with no description of its own.
    [hovered] = _run_shipped_resolver(
        conditions_endpoint, [{"condition_id": "condition:typed.stone_shell"}])
    for rule in ("healing", "dismissal", "damage equal to 10 + the Source key ability modifier + Proficiency Bonus"):
        assert rule in hovered["title"], f"{rule} missing from the hover: {hovered['title']}"


# ----------------------------------------------------------------------- Opportunity Attack meaning
def _opportunity_engine():
    """The smallest engine the real ``wants_opportunity_attack`` will decide on."""
    return SimpleNamespace(typed_reaction_rows={"actor:reactor": [{"block": "opportunity", "action_id": "act:oa"}]},
                           typed_passive_rows={}, typed_actor_ids=set(), action_catalog={},
                           state=SimpleNamespace(actors={}, current_actor_id="actor:reactor"))


def _fighter(entity_id, conditions=()):
    """An actor stub the real reaction code will decide on; ``conditions`` is ``((condition_id, data), ...)``."""
    held = {condition_id: SimpleNamespace(condition_id=condition_id, source_actor_id="actor:source",
                                          data=data, active=True)
            for condition_id, data in conditions}
    return SimpleNamespace(entity_id=entity_id, active=True, reaction_available=True, conditions=held,
                           turn_flags={}, zones=[])


NO_OA = "condition:typed.no_opportunity_attacks"
NO_OA_KEY = "no_opportunity_attacks"


def test_opportunity_attack_reading_describes_what_the_engine_actually_does():
    """Checklist: the sentence must match the rule, not merely be present.

    The engine reads this condition on the creature that would REACT, so the affected creature
    stops being able to MAKE an Opportunity Attack. The old text said the opposite ("does not
    provoke"), which would have led players to walk past the creature in safety.
    """
    from combat.typed_reactions import wants_opportunity_attack

    engine, mover = _opportunity_engine(), _fighter("actor:mover")

    # What the engine does, asserted directly rather than read out of the text.
    assert wants_opportunity_attack(engine, _fighter("actor:reactor"), mover) is True
    assert wants_opportunity_attack(engine, _fighter("actor:reactor", [(NO_OA, {})]), mover) is False
    # The restricted form ("against you", Hammer Rebuke) spares only that one creature.
    assert wants_opportunity_attack(engine, _fighter("actor:reactor", [(NO_OA, {"against": "actor:mover"})]),
                                    mover) is False
    assert wants_opportunity_attack(engine, _fighter("actor:reactor", [(NO_OA, {"against": "actor:someone-else"})]),
                                    mover) is True

    # And the text says the same thing.
    reading = READING[NO_OA_KEY]
    assert "cannot make an Opportunity Attack" in reading
    # The reversed claim that caused the finding must not come back, in any wording.
    assert "does not provoke" not in reading
    assert "provokes again" not in reading
    # It must not imply the creature is protected from being attacked.
    assert "cannot be attacked" not in reading and "immune" not in reading
    # The two things that really vary between sources are named rather than guessed.
    assert "single creature" in reading and "how long it lasts" in reading


# ----------------------------------------------------------------------- catalog guards
def test_every_extension_condition_has_hover_text():
    """The general guard: no condition the extensions create may reach the catalog without text."""
    catalog = all_conditions()
    missing = sorted(key for key in SOURCES
                     if not (catalog.get(key, {}).get("reading") or catalog.get(key, {}).get("mechanics")))
    assert not missing, f"conditions shown with no hover text: {missing}"


def test_no_displayable_condition_is_missing_hover_text():
    """Guard: every condition the catalog may draw a chip for has something to show on hover."""
    empty = sorted(key for key, info in all_conditions().items()
                   if key not in INTERNAL_ONLY and not (info.get("reading") or info.get("mechanics")))
    assert not empty, f"conditions shown with no hover text: {empty}"


def test_colour_only_metadata_does_not_advertise_an_empty_catalog_reading():
    from combat.typed_executor import rules
    catalog = all_conditions()
    for key, rule in rules()["conditions"].items():
        if set(rule) == {"pill_tone"}:
            assert rule["pill_tone"] in {"beneficial", "harmful"}
            if key in catalog:
                assert catalog[key]["reading"] or catalog[key]["mechanics"]


def test_extension_readings_do_not_replace_engine_readings():
    """The extension catalog only fills gaps; it must not overwrite text the engine owns."""
    catalog = all_conditions()
    for key in ("dodge", "blinded", "exhaustion", "concentration_held", "prone"):
        if key in catalog:
            from combat.condition_text import rules, plain_reading
            from combat.player_text import reading
            raw = rules()["conditions"][key].get("_rule", "")
            expected = reading(READING.get(key) or plain_reading(raw))
            assert catalog[key]["reading"] == expected, f"{key} changed its existing reading"
            assert catalog[key]["mechanics"] or catalog[key]["rule"], f"{key} lost its mechanics"


def test_only_the_named_dotted_keys_remain_unresolved_by_the_client():
    """The catalog contains 50 mapped keys; its fallback cannot resolve these three.

    The shipped resolver looks up the last dot-separated component, so a dotted condition key is
    stored under a name it can never match. The list is pinned here rather than left implicit so
    the gap is a known, countable follow-up and not a false "everything is covered".
    """
    dotted = {key for key in SOURCES if "." in key}
    assert dotted == DOTTED_KEYS_UNRESOLVED_BY_CLIENT
    catalog = all_conditions()
    for key in dotted:
        # The catalog does hold their text; only the client's lookup is the problem.
        assert catalog[key]["reading"], f"{key} lost its catalog text"
    assert len(SOURCES) == 50
    assert SOURCES["severing_arm"] == "tianxia.subpath.body.kensei.feature.severing_palm"
    assert catalog["severing_arm"]["reading"]
    rows = [{"condition_id": "condition:typed." + key} for key in sorted(dotted)]
    assert all(not row["title"] for row in _run_shipped_resolver(catalog, rows, expect_nonempty=False))


# ----------------------------------------------------------------------- newcomer readability
def test_double_dip_served_text_preserves_individual_dirty_trick_deadlines(conditions_endpoint):
    """The source does not invent a shared expiry for the two Dirty Trick effects."""
    reading = conditions_endpoint["double_dip_pick"]["reading"]
    assert "two different Dirty Trick effects instead of one" in reading
    assert "removing one does not remove the other" in reading
    assert "does not allow a second Trick talent" in reading
    assert "Both stay until" not in reading


def test_break_the_guard_served_text_names_only_its_exact_benefits(conditions_endpoint):
    reading = conditions_endpoint["destruction_break_the_guard"]["reading"]
    for phrase in ("its AC is reduced by 1", "next attack roll against it before the start of your next turn gains Advantage",
                   "it cannot benefit from half cover", "start of your next turn",
                   "only one option from Break the Guard at a time"):
        assert phrase in reading
    for stronger in ("vulnerable target", "Vulnerability", "no cover", "three-quarters", "total cover"):
        assert stronger.lower() not in reading.lower()


def test_modify_characteristics_served_text_preserves_each_owners_limit(conditions_endpoint):
    reading = conditions_endpoint["eye_modified_save"]["reading"]
    assert "Duration: 1 hour" in reading
    assert "only one modification from your Modify Characteristics talent at a time" in reading
    assert "Applying a new modification ends your previous one on that creature." in reading
    assert "a creature can only suffer one at a time" not in reading


@pytest.mark.parametrize("key,phrases", [
    ("skewer_pick", ("you may expend Martial Focus", "two different Exploits you know",
                     "Both Exploits must legally affect the target", "to that attack instead of one")),
    ("pressure_point_choice", ("Cost: 1 Stamina", "Saving Throw: Constitution",
                               "Speed reduced by 10 feet", "No Reactions until the start of its next turn",
                               "On a successful save, it cannot take Reactions until the start of its next turn")),
    ("return_the_grip_choice", ("When your Flowing Response succeeds",
                                "Strength or Dexterity saving throw, choosing which",
                                "Grappled condition until the start of your next turn",
                                "if you have a free hand or another eligible grappling body part",
                                "Successful Save: The creature cannot take Reactions until the start of its next turn")),
    ("turn_the_foot_choice", ("When your Flowing Response succeeds",
                              "makes a Dexterity saving throw",
                              "Speed is reduced by 10 feet until the start of its next turn",
                              "next Opportunity Attack it makes before the start of its next turn",
                              "falls Prone if it moved at least 10 feet immediately before triggering Flowing Response",
                              "Successful Save: No effect")),
])
def test_preference_served_text_preserves_activation_costs_and_effect_limits(conditions_endpoint, key, phrases):
    for phrase in phrases:
        assert phrase in conditions_endpoint[key]["reading"]


@pytest.mark.parametrize("features,button,key,trigger,forbidden", [
    (["tianxia.talent.blacksmith.hammer_rebuke"],
     "Hammer Rebuke: Speed -10 feet", "hammer_rebuke_choice", "The attacker makes a Strength saving throw",
     "your Strength saving throw"),
    (["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_DOUBLE_DIP"],
     "Double Dip: also Ears Ringing", "double_dip_pick", "When you succeed on Dirty Trick", "you spent Martial Focus"),
    (["TAL_FENCING_SKEWER", "TAL_FENCING_ARM_STRIKE", "TAL_FENCING_SHADOW_STRIKE"],
     "Skewer: also Arm Strike", "skewer_pick", "When you apply an Exploit", "you spent Martial Focus"),
    (["tianxia.subpath.body.shinobi.feature.pressure_point_strike"],
     "Pressure-Point Strike: prefer speed reduced by 10 feet until the start of its next turn "
     "(1 Stamina on an unarmed hit; once per turn)", "pressure_point_choice",
     "Trigger: You hit with an unarmed strike", "your last hit tried to inflict"),
    (["TAL_FLOWING_RIVER_FLOWING_RESPONSE", "TAL_FLOWING_RIVER_RETURN_THE_GRIP"],
     "Return the Grip: Grapple", "return_the_grip_choice", "against a Grapple or Shove attempt",
     "what your Flowing Response did"),
    (["TAL_FLOWING_RIVER_FLOWING_RESPONSE", "TAL_FLOWING_RIVER_TURN_THE_FOOT"],
     "Turn the Foot: Speed -10 feet", "turn_the_foot_choice", "When your Flowing Response succeeds",
     "what your Flowing Response did"),
    (["tianxia.talent.destruction.break_the_guard", "tianxia.talent.destruction.fracturing_break"],
     "Break the Guard: Reduce AC", "destruction_break_the_guard", "fails its saving throw",
     "a vulnerable target"),
])
def test_reviewed_preferences_reach_real_selector_before_activation_and_after_reload(
        tmp_path, conditions_endpoint, features, button, key, trigger, forbidden):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h52_identity_support import character, commit, fight, option, turn_of

    owner = character("85c00001", "Preference Learner", features, cl=14, primary="Stamina")
    others = [character("85c00002", "Partner", [], cl=14),
              character("85c00003", "Foe", [], cl=14)]
    _, service, table, mid, owner_id = fight(tmp_path, [owner, *others], "SOLFMMX85r5-SELECTOR")
    state = turn_of(table, mid, owner_id)
    engine = service._load_session(mid).engine
    actor = engine.state.actors[owner_id]
    resources = dict(actor.resources)
    economy = (actor.action_available, actor.bonus_action_available, actor.reaction_available)
    other_states = {aid: a.model_dump(mode="json") for aid, a in engine.state.actors.items() if aid != owner_id}
    commit(table, mid, option(state, button))
    saved = service._load_session(mid).engine
    saved_state = saved.state.model_dump(mode="json")
    saved_events = [e.model_dump(mode="json") for e in saved.events]
    resumed = TabletopService(CombatService(service.source_root, service.userdata_root), service.userdata_root)
    titles = []
    for current in (table, resumed):
        actors = current.state(mid)["presentation"]["actors"]
        me = next(a for a in actors if a["entity_id"] == owner_id)
        row = next(r for r in me["conditions"] if r.get("condition_id") == "condition:typed." + key)
        assert row["detail"], "exercise the real selector detail, which wins over the catalog"
        [resolved] = _run_shipped_resolver(conditions_endpoint, [row])
        title = resolved["title"]
        assert "Selected setting:" in title and trigger in title
        assert "Choosing this setting costs no action or resource" in title
        assert "stays selected until you change it" in title
        assert forbidden not in title
        titles.append(title)
        loaded = current.combat._load_session(mid).engine
        actor = loaded.state.actors[owner_id]
        assert actor.resources == resources
        assert (actor.action_available, actor.bonus_action_available, actor.reaction_available) == economy
        assert {aid: a.model_dump(mode="json") for aid, a in loaded.state.actors.items() if aid != owner_id} == other_states
        assert loaded.state.model_dump(mode="json") == saved_state
        assert [e.model_dump(mode="json") for e in loaded.events] == saved_events
    assert titles[0] == titles[1]


@pytest.mark.parametrize("key,required,forbidden", [
    ("body_dragon_step_clinch", (
        "your Speed is reduced by 10 feet while maintaining it",
        "unless it was Opened when the grapple began"), "It costs you 10 feet of Speed"),
    ("hammer_rebuke_choice", (
        "within your reach misses you with a melee attack using a weapon or natural weapon",
        "Cost: Spend 1 Forge Mark", "The attacker makes a Strength saving throw",
        "triggering weapon or limb", "against you until the start of its next turn"), "your Strength saving throw"),
    ("flowing_response_step", (
        "Action Type: Reaction", "Cost: no resource cost", "Use Limit: Once per round",
        "After the attack resolves, you may move 5 feet",
        "without provoking Opportunity Attacks from the triggering creature"), "now spent"),
])
def test_r6_openings_preserve_rule_exceptions_and_future_preferences(conditions_endpoint, key, required, forbidden):
    # Independent printed-rule expectations; runtime upgrade/preference assertions remain below.
    reading = conditions_endpoint[key]["reading"]
    for phrase in required:
        assert phrase in reading
    assert forbidden not in reading


@pytest.mark.parametrize("opened,upgraded", [(False, False), (True, False), (False, True), (True, True)])
def test_r6_real_clinch_chip_preserves_exceptions_after_reload(tmp_path, conditions_endpoint, opened, upgraded):
    from combat import ext
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import bears_mark
    from tests.hunt51_grapple_support import fight, grapple, on_turn, send, verify_reloaded

    user, service, table, mid, ids = fight(tmp_path, "r6-clinch", six=True,
                                          dragon_clinch=True, heaven_clinch=upgraded)
    on_turn(table, mid, ids[0])
    if opened:
        send(table, mid, lambda o: "Unarmed Strike" in str(o.get("label", ""))
             and "Grapple" not in str(o.get("label", "")) and "Shove" not in str(o.get("label", ""))
             and o.get("target_ids") == [ids[3]])
        assert bears_mark(service._load_session(mid).engine.state.actors[ids[3]], ids[0], "Opened")
        send(table, mid)
        on_turn(table, mid, ids[0])
    # The upgraded strike can move its target. Approach through the actual
    # movement menu before testing the grapple; keep the existing opening.
    engine = service._load_session(mid).engine
    owner, target = engine.state.actors[ids[0]], engine.state.actors[ids[3]]
    if engine.grid.distance_ft(owner.position, target.position) > 5:
        move = min(table.state(mid)["menu"]["moves"], key=lambda m:
                   max(abs(m["destination"]["x"] - target.position.x),
                       abs(m["destination"]["y"] - target.position.y)))
        send(table, mid, lambda o: o["candidate_id"] == move["candidate_id"])
    send(table, mid, grapple(ids[3]), reaction_pick=lambda choice: ["body:dragon_step_clinch"])
    verify_reloaded(user, service, mid)
    resumed = TabletopService(CombatService(service.source_root, user), user)
    titles = []
    for current in (table, resumed):
        engine = current.combat._load_session(mid).engine
        owner, held = engine.state.actors[ids[0]], engine.state.actors[ids[3]]
        grip = next(c for c in held.conditions.values() if c.data.get("grappling_part") == "body:dragon_step_clinch")
        assert grip.data["clinch_escape_advantage"] == int(not opened)
        assert ("ADVANTAGE" in ext.run("escape_mode", engine, held, [grip])) == (not opened)
        assert (-10 in ext.run("speed", engine, owner)) == (not upgraded)
        actor = next(a for a in current.state(mid)["presentation"]["actors"] if a["entity_id"] == ids[0])
        row = next(r for r in actor["conditions"] if r["condition_id"] == "condition:typed.body_dragon_step_clinch")
        [resolved] = _run_shipped_resolver(conditions_endpoint, [row])
        assert "unless it was Opened when the grapple began" in resolved["title"]
        assert "your Speed is reduced by 10 feet while maintaining it" in resolved["title"]
        titles.append(resolved["title"])
    assert titles[0] == titles[1]


@pytest.mark.parametrize("upgraded", [False, True])
def test_r6_step_selection_reload_and_repeated_success_eligibility(tmp_path, conditions_endpoint, upgraded):
    from combat.ext import flowing_river
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.hunt51_grapple_support import fight, on_turn, send, verify_reloaded

    talents = ["TAL_FLOWING_RIVER_FLOWING_RESPONSE"]
    if upgraded:
        talents.append("TAL_FLOWING_RIVER_EMPTY_STEP")
    user, service, table, mid, ids = fight(tmp_path, "r6-step", talents=talents,
                                          actor_scores={"actor:factory.luna38-a": 50})
    on_turn(table, mid, ids[0])
    before = service._load_session(mid).engine.state.actors[ids[0]].model_dump(mode="json")
    send(table, mid, lambda o: o.get("label") == "Flowing Response: step away")
    verify_reloaded(user, service, mid)
    resumed = TabletopService(CombatService(service.source_root, user), user)
    titles = []
    for current in (table, resumed):
        engine = current.combat._load_session(mid).engine
        owner = engine.state.actors[ids[0]]
        after = owner.model_dump(mode="json")
        for field in ("position", "movement_remaining_ft", "resources", "action_available",
                      "bonus_action_available", "reaction_available"):
            assert after[field] == before[field]
        setting = next(c for c in owner.conditions.values() if c.condition_id == flowing_river.STEP)
        assert setting.expires_on == "UNTIL_REMOVED"
        actor = next(a for a in current.state(mid)["presentation"]["actors"] if a["entity_id"] == ids[0])
        row = next(r for r in actor["conditions"] if r["condition_id"] == flowing_river.STEP)
        [resolved] = _run_shipped_resolver(conditions_endpoint, [row])
        assert "After the attack resolves, you may move 5 feet" in resolved["title"]
        assert "Choosing this setting costs no action or resource" in resolved["title"]
        assert "now spent" not in resolved["title"]
        assert "without provoking Opportunity Attacks from the triggering creature" in resolved["title"]
        titles.append(resolved["title"])
    assert titles[0] == titles[1]

    # Two real melee misses on separate rounds: commit the response and its
    # movement, reload, then approach again without reselecting the preference.
    for _ in range(2):
        on_turn(resumed, mid, ids[0])
        send(resumed, mid, lambda o: o.get("label") == "Dodge")
        send(resumed, mid)
        on_turn(resumed, mid, ids[2])
        engine = resumed.combat._load_session(mid).engine
        owner = engine.state.actors[ids[0]]
        foe = engine.state.actors[ids[2]]
        if engine.grid.distance_ft(owner.position, foe.position) > 5:
            move = min(resumed.state(mid)["menu"]["moves"], key=lambda m:
                       max(abs(m["destination"]["x"] - owner.position.x),
                           abs(m["destination"]["y"] - owner.position.y)))
            send(resumed, mid, lambda o: o["candidate_id"] == move["candidate_id"])
        state = resumed.state(mid)
        menu = state["menu"]
        attack = next(o for g in menu["actions"] if g["label"] == "Unarmed Strike"
                      for o in g["options"] if o.get("target_ids") == [ids[0]])
        before_events = len(resumed.combat._load_session(mid).engine.events)
        answers = []
        for _retry in range(20):
            result = resumed.act(mid, attack["candidate_id"], menu["decision_id"],
                                 menu["state_version"], state["last_sequence"], answers)
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            answers.append({**prompt["context"], "selection":
                            "USE" if flowing_river.RESPONSE in prompt["context"]["reaction_source_id"] else "DECLINE"})
        assert result["status"] == "COMMITTED", result
        verify_reloaded(user, resumed.combat, mid)
        engine = CombatService(service.source_root, user)._load_session(mid).engine
        owner = engine.state.actors[ids[0]]
        events = engine.events[before_events:]
        assert any(e.event_type == "PASSIVE_TRIGGERED" and
                   e.payload.get("trigger") == "Flowing Response succeeds" for e in events)
        moves = [e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ids[0]]
        assert len(moves) == 1
        assert len(moves[0].payload["path"]) - 1 == (2 if upgraded else 1)
        assert any(c.condition_id == flowing_river.STEP for c in owner.conditions.values())
    # Only choosing Hold Ground clears the persisted preference.
    on_turn(resumed, mid, ids[0])
    send(resumed, mid, lambda o: o.get("label") == "Flowing Response: hold ground")
    verify_reloaded(user, resumed.combat, mid)
    assert not any(c.condition_id == flowing_river.STEP for c in
                   CombatService(service.source_root, user)._load_session(mid).engine.state.actors[ids[0]].conditions.values())


def test_crawling_fever_opening_preserves_printed_protection_limits():
    opening = extension_readings()["crawling_fever_choice"]
    for phrase in (
        "Advantage on saving throws against Disease",
        "Resistance to Poison and Necrotic damage caused by Disease talents",
        "immunity to your Quarantine Veil and Plague Cloud damage",
        "remove one of your Contagion Tokens from themselves at the start of each of their turns",
    ):
        assert phrase in opening
    assert "resist disease and poison" not in opening.lower()


def test_severing_palm_opening_preserves_printed_effect_limits():
    opening = extension_readings()["severing_palm_choice"]
    for phrase in (
        "does not sever anatomy, create an Injury",
        "Distinct named effects can coexist",
        "reapplication refreshes its duration",
        "Arm: On a failed save, Disadvantage on all weapon attacks until the end of your next turn",
        "Leg: On a failed save, Speed is halved until the end of your next turn",
        "Breath: On a failed save, no Reactions until the end of your next turn",
        "Flow: On a failed save, Disadvantage on Concentration saving throws and Cultivation Checks made to maintain techniques until the end of your next turn",
        "Guard: On a failed save, AC is reduced by 2 until the start of your next turn",
        "On a successful save, the chosen effect lasts until the start of your next turn",
        "Guard instead reduces AC by 1",
    ):
        assert phrase in opening
    assert "last unarmed hit" not in opening
    assert "only suffer one at a time" not in opening


@pytest.mark.parametrize("feature,button,key,meaning,forbidden", [
    ("tianxia.talent.disease.court_of_the_crawling_fever", "Crawling Fever: No Reactions",
     "crawling_fever_choice", "Selected setting: Crawling Fever",
     "the disease aura standing around you"),
    ("tianxia.subpath.body.kensei.feature.severing_palm", "Severing Palm: Guard",
     "severing_palm_choice", "Selected setting: Severing Palm",
     "your last unarmed hit tried to inflict"),
])
def test_free_selector_does_not_claim_an_active_effect(
        tmp_path, conditions_endpoint, feature, button, key, meaning, forbidden):
    """Commit just the setting, then resolve the real table chip before and after reload."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h52_identity_support import character, commit, fight, option, turn_of

    owner = character("85b00001", "Selector Learner", [feature], cl=14)
    foes = [character("85b00002", "Partner", [], cl=14),
            character("85b00003", "Foe", [], cl=14)]
    _user, service, table, mid, owner_id = fight(tmp_path, [owner, *foes], "SOLFMMX85b-SELECTOR")
    state = turn_of(table, mid, owner_id)
    commit(table, mid, option(state, button))
    resumed = TabletopService(CombatService(service.source_root, service.userdata_root), service.userdata_root)
    titles = []
    for current in (table, resumed):
        actors = current.state(mid)["presentation"]["actors"]
        me = next(actor for actor in actors if actor["entity_id"] == owner_id)
        row = next(r for r in me["conditions"] if r.get("condition_id") == "condition:typed." + key)
        [resolved] = _run_shipped_resolver(conditions_endpoint, [row])
        title = resolved["title"]
        assert meaning in title
        assert "Choosing this setting costs no action or resource" in title
        assert forbidden not in title
        titles.append(title)
        if key == "crawling_fever_choice":
            # The selection stores a preference; it has not created the Court's aura.
            assert not current.combat._load_session(mid).engine.state.zones
    assert titles[0] == titles[1]


def test_extension_readings_are_readable_plain_prose():
    """Checklist 13: hover text reads for someone who knows only basic D&D rules."""
    for key, text in sorted(extension_readings().items()):
        assert text.strip(), key
        assert "combat/" not in text, f"{key} leaks an internal path"
        assert "condition:typed." not in text, f"{key} leaks an internal id"
        assert "`" not in text and "**" not in text, f"{key} leaks markup"


def test_generated_tracker_detail_includes_the_shared_opening():
    """A non-selector detail also bypasses the catalog in the shipped client."""
    from combat.ext.generated_status_text import describe
    engine = SimpleNamespace(action_catalog={}, typed_bundle_documents=[])
    row = {"condition_id": "condition:typed.body_dragon_step_clinch"}
    description = describe(engine, None, row, {})
    assert description["text"] == extension_readings()["body_dragon_step_clinch"]
    assert describe(engine, None, {"condition_id": "condition:typed.unmapped_control"}, {}) is None


def _source_prose(text):
    """Ignore presentation and approved resource expansions, keeping rule content."""
    import re
    # Approved 25.x player wording expands CP and the printed empty cost.
    # Normalize those substitutions and PB's expansion; every other word is kept.
    text = text.replace("cultivation points (your Path resource)", "CP")
    text = text.replace("Proficiency Bonus", "PB")
    text = re.sub(r"\bno resource cost\b", "None", text, flags=re.I)
    return " ".join(re.sub(r"(?m)^#+\s*", "", text.replace("**", "").replace("`", "")).split())


def test_every_extension_entry_quotes_its_printed_source(conditions_endpoint):
    """Independent guard: no added catalog entry may paraphrase its source's benefits."""
    sources = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    served = extension_readings()
    assert set(served) == set(SOURCES)
    for key, record in SOURCES.items():
        printed = _source_prose(sources[record])
        reading = _source_prose(served[key])
        assert reading and reading in printed, key
        assert _source_prose(conditions_endpoint[key]["reading"]) == reading, key
        # Detail takes precedence over the catalog, so also guard the mapped tracker provider.
        from combat.ext.generated_status_text import describe
        description = describe(SimpleNamespace(action_catalog={}, typed_bundle_documents=[]),
                               None, {"condition_id": "condition:typed." + key}, {})
        assert _source_prose(description["text"]) in printed, key


def test_the_golden_core_hover_preserves_printed_advancement_and_armament_rules(conditions_endpoint):
    reading = conditions_endpoint["golden_core_form"]["reading"]
    for phrase in ("after a successful CL15 breakthrough before using your CL15 Nascent Soul feature",
                   "At CL17, your chosen Form becomes Perfected", "At CL20, choose a second Golden Core Form",
                   "Move your Domain Armament 10 feet"):
        assert phrase in reading
    armament = conditions_endpoint["domain_armament"]["reading"]
    assert "It is not a Spirit Awakening Domain." in armament
    assert "Cost: 1 Qi" in armament and "Duration: 1 hour" in armament


def _assert_r7_restrictions(key, text):
    """Printed expectations independent of the production text/provider constants."""
    if key == "eye_court_ally":
        assert "a creature you can perceive enters or leaves the Domain" in text
        assert "does not grant sight through Total Cover, automatically reveal hidden creatures" in text
        assert "notice who enters it" not in text
    else:
        assert "1 Stamina or 1" in text
        assert "through an explicit non-Body access feature" in text
        assert "a 1-Stamina, or 1 CP" not in text


@pytest.mark.parametrize("key", ["eye_court_ally", "monkey_caper"])
def test_r7_served_rules_preserve_perception_and_payment_access(conditions_endpoint, key):
    reading = conditions_endpoint[key]["reading"]
    _assert_r7_restrictions(key, reading)
    # Prove this oracle rejects the previous overbroad openings even with correct rules later.
    bad = ("notice who enters it. " if key == "eye_court_ally" else "a 1-Stamina, or 1 CP. ") + reading
    with pytest.raises(AssertionError):
        _assert_r7_restrictions(key, bad)


@pytest.mark.parametrize("feature,button,key,on_ally", [
    ("TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE", "Court of the Hidden Eye", "eye_court_ally", True),
    ("TAL_MONKEY_STYLE_CAPERING_FOOTWORK", "Capering Footwork", "monkey_caper", False),
])
def test_r7_real_tracker_chip_preserves_restrictions_after_commit_reload(
        tmp_path, conditions_endpoint, feature, button, key, on_ally):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h52_identity_support import CLOSE_STARTS, character, commit, fight, option, turn_of

    owner = character("85d00001", "Tracker Learner", [feature], cl=14, primary="Stamina")
    ally = character("85d00002", "Court Ally", [], cl=14)
    foe = character("85d00003", "Partner", [], cl=14)
    _, service, table, mid, owner_id = fight(tmp_path, [owner, ally, foe], "SOLFMMX85r7-TRACKER",
                                            starts=CLOSE_STARTS)
    state = turn_of(table, mid, owner_id)
    commit(table, mid, option(state, button))
    engine = service._load_session(mid).engine
    saved_state = engine.state.model_dump(mode="json")
    saved_events = [e.model_dump(mode="json") for e in engine.events]
    resumed = TabletopService(CombatService(service.source_root, service.userdata_root), service.userdata_root)
    holder_id = "actor:factory.85d00002" if on_ally else owner_id
    titles = []
    for current in (table, resumed):
        actor = next(a for a in current.state(mid)["presentation"]["actors"] if a["entity_id"] == holder_id)
        row = next(r for r in actor["conditions"] if r["condition_id"] == "condition:typed." + key)
        assert row["detail"], "the real chip must exercise detail precedence"
        [resolved] = _run_shipped_resolver(conditions_endpoint, [row])
        _assert_r7_restrictions(key, resolved["title"])
        # Both row detail and catalog fallback reach the same shipped resolver.
        bare = {k: v for k, v in row.items() if k != "detail"}
        _assert_r7_restrictions(key, _run_shipped_resolver(conditions_endpoint, [bare])[0]["title"])
        titles.append(resolved["title"])
        loaded = current.combat._load_session(mid).engine
        assert loaded.state.model_dump(mode="json") == saved_state
        assert [e.model_dump(mode="json") for e in loaded.events] == saved_events
    assert titles[0] == titles[1]
    assert resumed.combat._load_session(mid).mechanical.replay()["status"] == "PASS"
