"""OCF7 blocker 2: the Nullifying Strike toggles resolve their printed text on a qualifying hit.

    Printed rule (rules_text.json, TAL_VOID_NULLIFYING_STRIKE):
    "Trigger: You hit a creature with Void Needle, an unarmed strike, or a melee weapon attack.
     Cost: 2 CP or 2 Stamina. Deal extra Force, Necrotic, or Psychic damage (2d6/3d6/4d6 by CL).
     The target makes a Constitution saving throw.
     Failed Save: Choose one: ... Hollowed / cannot take Reactions / suppress one temporary
     Resistance / Speed -10 ... Successful Save: cannot gain Temporary HP."

Space Bunny's round-24 hunt reported that "its printed damage, Constitution save and failed-save
choice never resolve", quoting 22 presses of the talent's own buttons in ``oc11-PN2`` with no
RESOURCE_SPENT, DAMAGE_ROLLED, DAMAGE_COMMITTED, SAVE_ROLLED or choice prompt in the whole fight.
That fight never attacked: all 33 of its steps are round 1 and every step after the setup is a
press of a settings row (``oc11-PN2`` lines 49-67 of the journal, every "rows" entry a single
CONDITION_APPLIED), so nothing was ever triggered to resolve. Measured here, on the real table:

* a toggled modifier on a Void Needle hit spends 2 of the chosen pool once, rolls the extra
  damage, rolls the target's Constitution save and applies the chosen failed-save result
  (``test_a_toggled_nullifying_strike_resolves_its_printed_text_on_a_qualifying_hit``);
* it costs nothing and does nothing on a miss (``..._does_nothing_on_a_miss``);
* with "Ask me when it hits" the failed-save question is put to the player with the four printed
  results, and only the chosen one applies (``..._asks_the_failed_save_question...``);
* the printed trigger is enforced where it is typed: the rider rides Void Needle, the unarmed
  strike and melee weapon attacks, and no thrown or ranged attack (``only_the_printed_triggers...``);
* the choice is a free setting kept until changed, and it survives a commit and a reload
  (``the_toggle_is_a_free_setting_that_survives_a_commit_and_a_reload``).

So this file is the blocker-2 regression: it fails the moment any of that stops being true.
"""
from __future__ import annotations

import pytest

from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import script
from tests.hunt36_support import LEFT, RIGHT, fight, reload, send, turn

NULL = "TAL_VOID_NULLIFYING_STRIKE"
NEEDLE = "TAL_VOID_VOID_NEEDLE"
POOL = {"resource:core.stamina": "Stamina", "resource:core.qi": "Cultivation Points"}


@pytest.fixture()
def rolls(monkeypatch):
    """The dice the next attack and its rider use, then the seeded roller as it was."""
    original = Gate4ControllerEngine._resolve_attack_spec

    def use(values):
        def rolled(engine, *args, **kwargs):
            script(engine, list(values))
            return original(engine, *args, **kwargs)
        monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", rolled)
    return use


def setting(combat, table, mid, parent, field, value):
    """Press the free settings row that changes one field of one attack's rider."""
    engine = combat._load_session(mid).engine
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if (a.parameters.get("attack_modifier_setting") or {}) ==
                  {"family": parent, "modifier": NULL, "name": "Nullifying Strike", "field": field, "value": value})
    cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == source)
    send(combat, table, mid, cid)


def configure(combat, table, mid, attack, **fields):
    engine = combat._load_session(mid).engine
    parent = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == attack)
    for field, value in fields.items():
        setting(combat, table, mid, parent, field, value)
    return parent


def strike(combat, table, mid, attack, **kwargs):
    candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                     if c.display_name == attack and tuple(c.target_ids) == (RIGHT,))
    return send(combat, table, mid, candidate.candidate_id, **kwargs)


#: The attack is rolled at Disadvantage here (two dice), then its own damage, then the rider's save:
#: everything after the attack dice is scripted, so the save's outcome never depends on the seed.
HIT_THEN_FAILED_SAVE = [19, 19] + [1] * 20
HIT_THEN_SAVED = [19, 19] + [20] * 20
MISS = [1, 1] + [20] * 20


def since(engine, sequence, *kinds):
    return [e for e in engine.events if e.sequence > sequence and e.event_type in kinds]


def conditions(engine, actor=RIGHT):
    return {c.condition_id.rsplit(".", 1)[-1] for c in engine.state.actors[actor].conditions.values()}


def test_a_toggled_nullifying_strike_resolves_its_printed_text_on_a_qualifying_hit(tmp_path, rolls):
    rolls(HIT_THEN_FAILED_SAVE)
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-hit")
    turn(combat, table, mid)
    engine = reload(combat, mid)
    attack = "Void Needle: Unsettle Invisibility"
    before = engine.state.event_sequence
    stamina = engine.state.actors[LEFT].resources["resource:core.stamina"]
    configure(combat, table, mid, attack, on="toggle", option="0", payment="0", damage="necrotic")
    strike(combat, table, mid, attack)
    engine = reload(combat, mid)
    events = since(engine, before, "ATTACK_ROLLED", "RESOURCE_SPENT", "DAMAGE_ROLLED", "DAMAGE_COMMITTED",
                   "SAVE_ROLLED", "CONDITION_APPLIED")
    assert [e for e in events if e.event_type == "ATTACK_ROLLED"][0].payload["provisional_hit"]
    paid = [e for e in events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == NULL]
    assert len(paid) == 1 and paid[0].payload["amount"] == 2, paid
    assert engine.state.actors[LEFT].resources["resource:core.stamina"] == stamina - 2
    extra = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Nullifying Strike"]
    assert len(extra) == 1 and extra[0].payload["expression"] == "2d6+0", extra
    committed = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
                 and e.payload.get("display_source_id") == f"passive:{NULL}"]
    assert [e.payload["damage_type"] for e in committed] == ["NECROTIC"], committed
    save = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == f"passive:{NULL}"]
    assert len(save) == 1, "the printed Constitution save was never rolled"
    assert save[0].payload["actor_id"] == RIGHT, save[0].payload
    assert "reaction_denied" in conditions(engine), "the chosen failed-save result was not applied"


def test_the_same_toggle_costs_nothing_and_does_nothing_on_a_miss(tmp_path, rolls):
    rolls(MISS)
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-miss")
    turn(combat, table, mid)
    engine = reload(combat, mid)
    attack = "Void Needle: Unsettle Invisibility"
    before = engine.state.event_sequence
    pools = dict(engine.state.actors[LEFT].resources)
    configure(combat, table, mid, attack, on="toggle", option="0", payment="0", damage="necrotic")
    strike(combat, table, mid, attack)
    engine = reload(combat, mid)
    events = since(engine, before, "ATTACK_ROLLED", "RESOURCE_SPENT", "DAMAGE_ROLLED", "SAVE_ROLLED")
    assert not [e for e in events if e.event_type == "ATTACK_ROLLED"][0].payload["provisional_hit"]
    assert not [e for e in events if e.source_definition_id == NULL], events
    assert not [e for e in events if e.payload.get("damage_label") == "Nullifying Strike"], events
    assert engine.state.actors[LEFT].resources == pools, "a miss cost the rider's price"


def test_the_failed_save_question_is_asked_and_only_the_chosen_result_applies(tmp_path, rolls):
    rolls(HIT_THEN_FAILED_SAVE)
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-ask")
    turn(combat, table, mid)
    engine = reload(combat, mid)
    attack = "Void Needle: Unsettle Invisibility"
    before = engine.state.event_sequence
    configure(combat, table, mid, attack, on="toggle", payment="0", damage="necrotic")
    prompts = strike(combat, table, mid, attack, pick=lambda option: "Hollowed" in str(option["label"]))
    questions = [p for p in prompts if p.get("choice") and "failed-save" in p["context"]["checkpoint"]]
    assert len(questions) == 1, f"the failed-save question was never put to the player: {prompts}"
    labels = " ".join(option["label"] for option in questions[0]["choice"]["options"])
    for printed in ("No Reactions", "Speed -10", "Hollowed", "Suppress Resistance"):
        assert printed in labels, f"the printed results are not all offered: {labels}"
    engine = reload(combat, mid)
    events = since(engine, before, "SAVE_ROLLED", "CONDITION_APPLIED")
    assert len([e for e in events if e.event_type == "SAVE_ROLLED"]) == 1
    assert "hollowed" in conditions(engine), conditions(engine)
    assert "reaction_denied" not in conditions(engine), "an effect the player did not choose was applied"


def test_a_saved_target_gets_the_printed_successful_save_result_and_no_question(tmp_path, rolls):
    rolls(HIT_THEN_SAVED)
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-save")
    turn(combat, table, mid)
    engine = reload(combat, mid)
    attack = "Void Needle: Unsettle Invisibility"
    configure(combat, table, mid, attack, on="toggle", payment="0", damage="force")
    prompts = strike(combat, table, mid, attack)
    assert not [p for p in prompts if p.get("choice") and "failed-save" in p["context"]["checkpoint"]], prompts
    engine = reload(combat, mid)
    assert "no_temp_hp" in conditions(engine), conditions(engine)
    assert "hollowed" not in conditions(engine), "a failed-save result applied to a target that saved"


def test_only_the_printed_triggers_carry_the_rider(tmp_path):
    """'Void Needle, an unarmed strike, or a melee weapon attack': nothing thrown rides it."""
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-trigger")
    engine = reload(combat, mid)
    carried, thrown = [], []
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        groups = [g["id"] for g in typed.get("attack_modifier_loadout") or []]
        if NULL not in groups:
            continue
        assert "Nullifying Strike" not in action.display_name or " + Nullifying Strike:" in action.display_name, (
            f"a settings row was published as an ability of its own: {action.display_name}")
        if typed.get("weapon") and (typed.get("range_ft") or action.range_ft or 0) > 5:
            thrown.append(action.display_name)
        else:
            carried.append(action.display_name)
    assert carried, "no attack carries the rider at all"
    assert not thrown, f"a thrown or ranged attack carries the rider: {thrown}"
    assert any("Void Needle" in name for name in carried), carried
    assert any("Unarmed Strike" in name for name in carried), carried
    assert any("attack" in name for name in carried), carried
    # And the compiled answer is the same one: a thrown version of an attack that does carry it.
    assert not [a for a in engine.action_catalog.values() if "thrown" in a.display_name
                and "Nullifying Strike" in a.display_name], "a thrown attack offers the rider as its own ability"


def test_the_toggle_is_a_free_setting_that_survives_a_commit_and_a_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-keep")
    turn(combat, table, mid)
    engine = reload(combat, mid)
    attack = "Void Needle: Unsettle Invisibility"
    before = dict(engine.state.actors[LEFT].resources)
    hp = engine.state.actors[RIGHT].current_hp
    configure(combat, table, mid, attack, on="toggle", option="2", payment="0", damage="psychic")
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources == before, "choosing a rider setting is free and spends nothing"
    assert engine.state.actors[RIGHT].current_hp == hp
    kept = [c.data for c in engine.state.actors[LEFT].conditions.values() if c.condition_id.endswith("attack_modifiers")]
    assert kept == [{"damage": "psychic", "family": next(a.source_definition_id for a in engine.action_catalog.values()
                                                        if a.display_name == attack),
                     "label": "Nullifying Strike", "modifier": NULL, "on": 1, "option": "2", "payment": "0",
                     "reading": "Attack modifier choices stay until changed; only a qualifying hit pays the selected cost."}], kept


def test_the_choice_is_offered_on_the_attack_it_changes(tmp_path):
    """The table shows the rider under the attack it rides; the settings rows are that panel's transport."""
    combat, table, mid = fight(tmp_path, [NULL, NEEDLE], primary="Stamina", cl=5, seed="OCF7-panel")
    turn(combat, table, mid)
    state = table.state(mid)
    attack = "Void Needle: Unsettle Invisibility"
    entry = next(row for row in state["shapes"][LEFT] if row["name"] == attack)
    modifier = next(row for row in entry["modifiers"] if row["name"] == "Nullifying Strike")
    assert modifier["candidate_id"], "the panel offers no way to turn the rider on or off"
    for selector in modifier["selectors"]:
        assert all(option["candidate_id"] for option in selector["options"] if option["value"] != "ask"), selector
        assert selector["current"] == "ask"
    assert modifier["cost"] in ("2 Stamina", "2 CP or 2 Stamina"), modifier["cost"]
    # The fight-level rows that carry those candidates name the attack they belong to, so the action
    # bar (static/tabletop/tabletop.js: a group carrying `shape` is listed as an option, not an action)
    # keeps them out of the ability list.
    families = {group["shape"] for group in state["menu"]["actions"] if group.get("shape")}
    assert entry["base"] in families, "the rider's settings rows are not tied to their attack"
    ids = {option["candidate_id"] for group in state["menu"]["actions"] if group.get("shape") == entry["base"]
           for option in group["options"]}
    assert modifier["candidate_id"] in ids
    assert POOL  # the two prices the printed cost offers, named for the report
