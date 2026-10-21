"""Automation lane 9 (Alchemy sphere): every printed effect this lane automated, run through the engine.

Three printed effects, each read from the owner's own text and each failing on the authority this lane started
from (``reviewed_final.d/auto9_alchemy.json`` + ``combat/ext/alchemy_riders.py``):

* **Seven-Flavor Furnace** -- "When an Alchemy technique lets you choose Acid, Fire, Poison, or Force damage, you
  may choose one of your selected damage types instead": the prepared types are offered *beside* the printed ones,
  wherever the printed choice is made (Rotting Pill, Furnace Vent, Explosive Pill, the Court's failed-save rider)
  and on the area World Within the Furnace makes, whose type is chosen when the area is created. The printed Long
  Rest choice is asked once and sealed, including when nothing (or nothing at all) is prepared.
* **Binding Dregs** -- "If the target is standing on a solid surface, it also cannot take the Dash action",
  qualified where the printed sentence puts it: when the save resolves.
* **Court of the Three-Legged Cauldron** -- "Once per turn when you use a Field Formula, reduce its CP cost by 1"
  and "the first time each turn a hostile creature fails a saving throw ... it takes extra Acid, Fire, Poison, or
  Force damage", which is itself one of the printed choices Seven-Flavor Furnace substitutes into.

Plus one pre-existing defect this lane found: Furnace Vent charged its printed "Cost: 1 CP and one Reagent Stock"
twice (the printed cost block and a hand-added spend_resource row for the same 1 CP).

Saves are forced with the sheet's technique DC (50: the foe fails every save; -40: it succeeds every one).
Overrides live in authority/typed_mechanics/reviewed_final.d/{auto9_alchemy.json,life.json}.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
H = importlib.import_module("test_review_sw-athletics")  # the shared harness: _bundle, _engine, _use, ...

ROOT = Path(__file__).resolve().parents[1]

ME, AN = H.ME, H.AN
NO_KIT = {"starting_kit": {"items": []}}
ALCHEMY = "tianxia.sphere.alchemy"
SEVEN = "tianxia.talent.alchemy.seven_flavor_furnace"
SEVEN_CONDITION = "condition:typed.seven_flavor_types"
ROTTING = "TAL_ALCHEMY_POISON_PILL"
VENT = "TAL_ALCHEMY_FURNACE_VENT"
DREGS = "TAL_ALCHEMY_BINDING_DREGS"
COURT = "tianxia.talent.alchemy.court_of_the_three_legged_cauldron"
FURNACE = "tianxia.talent.alchemy.world_within_the_furnace"
STAMINA, STOCK = "resource:core.stamina", "resource:named.reagent_stock"
FAIL, MADE = 50, -40


def _engine(talents, *, cl=15, dc=FAIL):
    return H._engine(H._bundle(ALCHEMY, list(talents), NO_KIT, cl=cl, dc=dc), foe_hp=400)


def _answering(answers):
    """A table that answers this lane's own choice namespaces (``answers`` maps a namespace's tail to its picks)
    and leaves every other window to the engine's own printed default. ``None`` declines a mapped question."""
    from combat.gate2_runtime_models import ReactionDecision

    asked: list[dict] = []

    def choose(request):
        source = str(request["reaction_source_id"])
        if not source.startswith("choice:needle."):
            return None, None
        for name, picks in answers.items():
            if not source.endswith(name):
                continue
            asked.append(request)
            if picks is None:
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                       reaction_source_id=source, selection="DECLINE", option_ids=()), None
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                   reaction_source_id=source, selection="USE", option_ids=tuple(picks)), None
        return None, None

    return choose, asked


def _prepared(actor):
    return [c for c in actor.conditions.values() if c.condition_id == SEVEN_CONDITION]


def _types_of(actor):
    return [c.data["types"] for c in _prepared(actor)]


def _damage_types(events):
    return [e.payload.get("damage_type") for e in events if e.event_type == "DAMAGE_COMMITTED"]


def _spent(events, resource):
    return sum(e.payload.get("amount", 0) for e in events
               if e.event_type == "RESOURCE_SPENT" and e.payload.get("resource_id") == resource)


def _end_turn(engine, actor_id):
    """One real turn boundary for ``actor_id`` (the harness's _use always acts as ME)."""
    from combat.gate2_runtime_models import ActionIntent

    candidate = next(c for c in engine.legal_candidates() if c.kind == "END_TURN")
    engine.execute_intent(ActionIntent(intent_id="i:end", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id))


def _resist(engine, subject, kind):
    engine._add_modifier(subject, "action:test.ward", "damage_resistance", "ADD", str(kind).upper(), "ALWAYS",
                         expires_on="UNTIL_REMOVED")


# ----------------------------------------------------------------------------------- Seven-Flavor Furnace


def test_seven_flavor_furnace_deals_a_prepared_type_beside_the_printed_pair():
    """"When an Alchemy technique lets you choose Acid, Fire, Poison, or Force damage, you may choose one of your
    selected damage types instead": Rotting Pill's printed "3d6 Necrotic or Poison damage" becomes the prepared type."""
    engine = _engine([ROTTING, SEVEN])
    choose, asked = _answering({"seven_flavor": ["thunder", "cold"]})
    engine.set_reaction_provider(choose)

    events = H._use(engine, "Poison Pill: Rotting Pill", target=None)

    assert _damage_types(events) == ["THUNDER"], "the prepared type did not stand in for the printed pair"
    assert _types_of(engine.state.actors[ME]) == ["thunder|cold"], _prepared(engine.state.actors[ME])
    assert len(asked) == 1, "the printed Long Rest choice must be asked once, not once per formula"

    H._ready(engine)
    again = H._use(engine, "Poison Pill: Rotting Pill", target=None)
    assert _damage_types(again) == ["THUNDER"], "a second formula in the same fight lost the prepared types"
    assert len(asked) == 1, "the prepared types were asked for again"


def test_a_prepared_type_the_target_resists_loses_to_a_printed_type_that_lands():
    """The printed talent offers a *choice* between the two sets, so it may never take the printed types away.

    Preparing Cold against a creature that is immune to Cold damage must not make Rotting Pill deal nothing: the
    printed Necrotic (or Poison) damage is still on the table and lands hardest.
    """
    engine = _engine([ROTTING, SEVEN])
    engine.set_reaction_provider(_answering({"seven_flavor": ["cold"]})[0])
    _resist(engine, engine.state.actors[AN], "cold")

    events = H._use(engine, "Poison Pill: Rotting Pill", target=None)

    assert _damage_types(events) == ["NECROTIC"], _damage_types(events)


def test_the_seven_flavor_question_names_the_ability_the_action_and_what_each_type_needs():
    """Checklist 13: the prompt is the player's own decision and says what it is for (checklist 9: asked, not
    assumed; the triggering action and the affected creature are named)."""
    engine = _engine([ROTTING, SEVEN])
    choose, asked = _answering({"seven_flavor": ["cold"]})
    engine.set_reaction_provider(choose)
    H._use(engine, "Poison Pill: Rotting Pill", target=None)

    trigger = asked[0]["choice_trigger"]
    prompt = trigger["prompt"]
    assert asked[0]["reaction_source_id"] == "choice:needle.seven_flavor"
    assert asked[0]["legal_option_ids"] == ["acid", "cold", "fire", "lightning", "necrotic", "poison", "radiant", "thunder"]
    assert "Seven-Flavor Furnace" in prompt and "ingredients" in prompt, prompt
    assert "Poison Pill: Rotting Pill" in prompt, prompt
    assert trigger["name"] == "Seven-Flavor Furnace" and trigger["maximum"] == 3
    assert asked[0]["extension_choice"]["automatic_use"] is False, "a player's own preparation is not the AI's to assume"


@pytest.mark.parametrize("talents,answer", [
    ([ROTTING], {"seven_flavor": ["cold"]}),  # the talent is not owned: nothing changes for anybody else
    ([ROTTING, SEVEN], {}),                  # owned, but nobody is answering (an AI fighter, an old saved fight)
])
def test_seven_flavor_furnace_leaves_the_printed_types_exactly_as_printed(talents, answer):
    """A plug-in is inert for a creature that does not own the talent, and with no answer every printed type stands."""
    engine = _engine(talents)
    engine.set_reaction_provider(_answering(answer)[0])
    events = H._use(engine, "Poison Pill: Rotting Pill", target=None)
    assert _damage_types(events) == ["NECROTIC"], _damage_types(events)
    assert not any(_types_of(engine.state.actors[ME])), "no preparation was declared"


def test_declining_the_preparation_is_sealed_and_never_asked_again():
    """"choose up to three" is a choice once per Long Rest: declining records an empty preparation, so the next
    formula finds the decision made and cannot be re-answered after the player has seen the enemy."""
    engine = _engine([ROTTING, SEVEN])
    choose, asked = _answering({"seven_flavor": None})
    engine.set_reaction_provider(choose)

    H._use(engine, "Poison Pill: Rotting Pill", target=None)
    assert _types_of(engine.state.actors[ME]) == [""], "a decline left no record of the decision"

    H._ready(engine)
    events = H._use(engine, "Poison Pill: Rotting Pill", target=None)
    assert _damage_types(events) == ["NECROTIC"], "a declined preparation changed the printed types"
    assert len(asked) == 1, "the sealed decision was asked again"


# ----------------------------------------------------------------------------------- World Within the Furnace


@pytest.mark.parametrize("prepares,choice,expected", [
    (None, None, "ACID"),          # no talent, nobody answering: the printed type of the chosen option stands
    (["thunder", "cold"], None, "ACID"),   # preparing must not silently rewrite the area (a different printed option)
    (["thunder", "cold"], "thunder", "THUNDER"),
    (["thunder", "cold"], "cold", "COLD"),
    (["thunder", "cold"], "acid", "ACID"),  # a printed type stays on the menu
])
def test_the_furnace_area_carries_the_damage_type_its_creator_chose(prepares, choice, expected):
    """"When you create the area, choose Acid, Fire, or Poison": the creator chooses the type, from the printed
    three plus whatever Seven-Flavor Furnace lets them substitute, and the area keeps that choice."""
    talents = [FURNACE] + ([SEVEN] if prepares else [])
    engine = _engine(talents)
    answers = {"seven_flavor": prepares} if prepares else {}
    if choice:
        answers["furnace_type"] = [choice]
    if answers:
        engine.set_reaction_provider(_answering(answers)[0])

    H._use(engine, "World Within the Furnace: Acid at 4,6", target=None)
    events = H._use(engine, "End turn", target=None)  # the foe starts its turn inside the area

    assert _damage_types(events) == [expected], (talents, prepares, choice, _damage_types(events))


def test_the_furnace_creation_menu_keeps_the_printed_types_beside_the_prepared_ones():
    """The creation choice is the printed one plus the owner's prepared types, never the prepared list alone."""
    engine = _engine([FURNACE, SEVEN])
    choose, asked = _answering({"seven_flavor": ["thunder", "cold"], "furnace_type": ["thunder"]})
    engine.set_reaction_provider(choose)
    H._use(engine, "World Within the Furnace: Acid at 4,6", target=None)

    menu = next(request for request in asked if request["reaction_source_id"] == "choice:needle.furnace_type")
    assert menu["legal_option_ids"] == ["thunder", "cold", "acid"], menu["legal_option_ids"]
    assert menu["choice_trigger"]["prompt"].startswith("World Within the Furnace: World Within the Furnace: Acid")


# ----------------------------------------------------------------------------------- the table


def _portable(tmp_path, owner_abilities, foe_abilities, *, owner_hp=60, foe_hp=200, dc=FAIL):
    from tests.h1_support import sheet

    for pid, abilities, hp, name in (("aaaaaaaa", owner_abilities, owner_hp, "Alchemist"),
                                     ("ffffffff", foe_abilities, foe_hp, "Target")):
        doc = sheet(abilities, primary="Stamina", dc=dc)
        doc["identity"]["display_name"] = name
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
        folder = Path(tmp_path) / "portable_characters" / pid
        folder.mkdir(parents=True)
        import zipfile

        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return ROOT


def _table(monkeypatch, tmp_path, abilities, *, stock=5, owner="actor:factory.aaaaaaaa",
           foe="actor:factory.ffffffff"):
    """A real saved fight on the portable table, with the owner's inventory granted through a joined event hook."""
    from combat import ext
    from combat.gate5_service import CombatService
    from combat.tabletop import ButtonStore
    from combat.tabletop_service import TabletopService
    from tests.test_hidden_targeting import turn
    from tests.test_lock2_persistence import act

    _portable(tmp_path, abilities, ["TAL_ALCHEMY_QI_INFUSION_PILL"])
    ButtonStore(Path(tmp_path) / "tabletop_buttons").save_reactions("aaaaaaaa", {"mode": "ask"}, abilities)

    def prepared(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs["actor_id"] == owner:
            actor = engine.state.actors[owner]
            if STOCK in actor.resource_maximums:
                engine._gain_resource(actor, STOCK, stock, "test:prepared-inventory")
    # The prepared-inventory hook joins the engine's own event subscribers: replacing the list would switch off
    # every other plug-in's event reader (combat/ext/life_state._events among them), so a defeated creature
    # never finalizes and the fight never ends.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), prepared])
    combat = CombatService(ROOT, Path(tmp_path))
    combat.tabletop_maps.save({"display_name": "Alchemy yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[6, 4]]}})
    mid = combat.create_factory_match(project_ids=["aaaaaaaa"], opponent_actor_ids=[foe],
                                      control_modes={owner: "MANUAL", foe: "MANUAL"},
                                      arena_id="battlefield:map.alchemy-yard", match_seed="AUTO9F1-ALCHEMY")["match_id"]
    table = TabletopService(combat, Path(tmp_path))
    turn(table, mid, owner)
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    return combat, table, mid


def _first_or_decline(prompt):
    """Answer a window the printed rules do not let a player refuse with its first option, and refuse it otherwise."""
    choice = prompt.get("choice") or {}
    options = choice.get("options") or []
    if choice.get("allow_decline") or not options:
        return None, False
    return options[0].get("id"), True


def _pick(prompt, namespace, option):
    """Answer this lane's own prompt at the table: its named option, or a plain decline.

    A window this helper does not own falls back to :func:`_first_or_decline`, so a menu the printed rules
    require an answer to is never left hanging."""
    if f"choice:needle.{namespace}" in json.dumps(prompt):
        return (option, True) if option else (None, False)
    return _first_or_decline(prompt)


def _reloaded(tmp_path, mid):
    """The fight as it comes back from disk, verified and replayed."""
    from combat.gate5_service import CombatService

    session = CombatService(ROOT, Path(tmp_path))._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    return session.engine


def _turn_to(table, mid, actor_id):
    """Play the fight on to ``actor_id``'s turn, answering each turn's own prompts (a furnace area asks which
    creatures it catches when their turn starts). ``tests.test_hidden_targeting.turn`` ends turns unanswered."""
    from tests.r10_fixup_support import commit

    def end_turn(answers=()):
        state = table.state(mid)
        menu = state["menu"]
        return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], list(answers))

    while table.state(mid)["menu"]["actor_id"] != actor_id:
        commit(end_turn, _first_or_decline)


def test_the_prepared_types_survive_a_table_commit_and_reload(monkeypatch, tmp_path):
    """Checklist 7: what the fight remembers is stored as a string and comes back with the fight."""
    from tests.r10_fixup_support import cast_sender, commit

    owner = "actor:factory.aaaaaaaa"
    combat, table, mid = _table(monkeypatch, tmp_path, [ROTTING, SEVEN])
    prompts = commit(cast_sender(combat, table, mid, "Poison Pill", contains="Rotting Pill"),
                     lambda prompt: _pick(prompt, "seven_flavor", "thunder"))
    assert any("Seven-Flavor Furnace" in json.dumps(prompt) for prompt in prompts), \
        "the table was never asked which damage types the Alchemist prepared"

    engine = _reloaded(tmp_path, mid)
    assert _types_of(engine.state.actors[owner]) == ["thunder"], _prepared(engine.state.actors[owner])
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert [e.payload["damage_type"] for e in damage] == ["THUNDER"], [e.payload for e in damage]


def test_a_declined_preparation_is_not_asked_again_after_a_reload(monkeypatch, tmp_path):
    """Checklist 7/9: the once-per-rest decision is sealed in the saved fight, not re-put on every formula."""
    from tests.r10_fixup_support import cast_sender, commit
    from tests.test_hidden_targeting import turn
    from tests.test_lock2_persistence import act

    owner, foe = "actor:factory.aaaaaaaa", "actor:factory.ffffffff"
    combat, table, mid = _table(monkeypatch, tmp_path, [ROTTING, SEVEN])
    sender = cast_sender(combat, table, mid, "Poison Pill", contains="Rotting Pill")
    first = commit(sender, lambda prompt: _pick(prompt, "seven_flavor", None))
    assert any("Seven-Flavor Furnace" in json.dumps(prompt) for prompt in first), first
    assert _types_of(_reloaded(tmp_path, mid).state.actors[owner]) == [""], \
        "the declined preparation did not survive the commit"

    turn(table, mid, foe)  # a later turn of the same fight, with the same sealed decision
    assert act(table, mid, "end")["status"] == "COMMITTED"
    turn(table, mid, owner)
    second = commit(cast_sender(combat, table, mid, "Poison Pill", contains="Rotting Pill"))
    assert not any("Seven-Flavor Furnace" in json.dumps(prompt) for prompt in second), \
        f"the sealed decision was asked again: {second}"
    engine = _reloaded(tmp_path, mid)
    assert _types_of(engine.state.actors[owner]) == [""], _prepared(engine.state.actors[owner])
    assert [e.payload["damage_type"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED"][-1] == "NECROTIC"


@pytest.mark.parametrize("choice,expected", [("thunder", "THUNDER"), ("acid", "ACID")])
def test_the_area_the_table_created_keeps_its_chosen_type_through_a_reload(monkeypatch, tmp_path, choice, expected):
    """Checklist 7: the creation choice is stored on the area, so the reloaded fight still deals it."""
    from combat.ext.alchemy_riders import zone_damage_types
    from tests.r10_fixup_support import cast_sender, commit

    owner, foe = "actor:factory.aaaaaaaa", "actor:factory.ffffffff"
    combat, table, mid = _table(monkeypatch, tmp_path, [FURNACE, SEVEN])
    commit(cast_sender(combat, table, mid, "World Within the Furnace", contains="Acid", at=(6, 4)),
           lambda prompt: _pick(prompt, "seven_flavor", "thunder")
           if "seven_flavor" in json.dumps(prompt) else _pick(prompt, "furnace_type", choice))

    engine = _reloaded(tmp_path, mid)
    zone = next(iter(engine.state.zones.values()))
    assert set(zone_damage_types(zone.trigger_profile)) == {choice}, zone.trigger_profile["triggers"]

    _turn_to(table, mid, foe)
    engine = _reloaded(tmp_path, mid)
    dealt = [e.payload["damage_type"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert expected in dealt, dealt


def test_the_court_extra_damage_is_offered_the_prepared_types_at_the_table(monkeypatch, tmp_path):
    """Checklist 9 + finding 3: the Court's failed-save damage is one of the printed Acid, Fire, Poison or Force
    choices, so at the table it offers the owner's prepared types too, and a formula that offers no damage type of
    its own (Binding Dregs) is enough to open the printed Long Rest question."""
    from tests.r10_fixup_support import cast_sender, commit

    owner, foe = "actor:factory.aaaaaaaa", "actor:factory.ffffffff"
    combat, table, mid = _table(monkeypatch, tmp_path, [COURT, DREGS, SEVEN])
    commit(cast_sender(combat, table, mid, "Court of the Three-Legged Cauldron"))
    prompts = commit(cast_sender(combat, table, mid, "Binding Dregs", target=foe),
                     lambda prompt: (_pick(prompt, "seven_flavor", "thunder")
                                     if "seven_flavor" in json.dumps(prompt)
                                     else _pick(prompt, "cauldron_damage", "thunder")))
    asked = [json.dumps(prompt) for prompt in prompts]
    assert any("choice:needle.seven_flavor" in text for text in asked), asked
    assert any("choice:needle.cauldron_damage" in text for text in asked), asked

    engine = _reloaded(tmp_path, mid)
    assert _types_of(engine.state.actors[owner]) == ["thunder"], _prepared(engine.state.actors[owner])
    extra = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == owner]
    assert [e.payload["damage_type"] for e in extra] == ["THUNDER"], [e.payload for e in extra]


# ----------------------------------------------------------------------------------- who is asked, and when

#: The owner's actor id in the portable table :func:`_table` builds.
OWNER = "actor:factory.aaaaaaaa"


@pytest.mark.parametrize("answer,damaged", [("include", True), ("exclude", False)])
def test_the_areas_turn_start_question_is_asked_of_the_human_on_the_foes_turn(monkeypatch, tmp_path, answer, damaged):
    """Checklist 9: a player-owned decision is *asked* -- on the player's own turn and on another
    creature's turn alike -- and the human's answer is what happens.

    World Within the Furnace catches a creature that starts its turn in the area, so the printed "Hostile
    creatures of your choice" question arrives while the **foe** is starting its turn. It is still the
    caster's decision, so the table puts it to the caster, who is MANUAL with Ask me here, and nothing
    happens to the foe until they answer.
    """
    from tests.r10_fixup_support import cast_sender, commit

    owner, foe = OWNER, "actor:factory.ffffffff"
    combat, table, mid = _table(monkeypatch, tmp_path, [FURNACE, SEVEN])
    commit(cast_sender(combat, table, mid, "World Within the Furnace", contains="Acid", at=(6, 4)),
           lambda prompt: _pick(prompt, "seven_flavor", "thunder")
           if "seven_flavor" in json.dumps(prompt) else _pick(prompt, "furnace_type", "thunder"))

    def end_turn(answers=()):
        """Ending the owner's turn is what starts the foe's, so this is where the off-turn question lands."""
        state, menu = table.state(mid), table.state(mid)["menu"]
        return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], list(answers))

    asked = []

    def selections(prompt):
        if (prompt.get("context") or {}).get("reaction_source_id") == "choice:needle.furnace_target":
            asked.append(prompt)
            return answer, True
        return _first_or_decline(prompt)

    commit(end_turn, selections)

    assert len(asked) == 1, f"the off-turn question was not put to the caster exactly once: {asked}"
    window = asked[0]
    assert window["context"]["reactor_id"] == owner, "the question went to the caught creature, not its caster"
    assert window["reactor"] == "Alchemist" and window["affected"] == "Target", window
    # Checklist 9 and 13: it names the ability, the action that raised it and the creature it is about.
    for part in ("World Within the Furnace", "Acid", "Target"):
        assert part in window["moment"], (part, window["moment"])
    assert [option["label"] for option in window["choice"]["options"]] == \
challenge_options(), [option["label"] for option in window["choice"]["options"]]

    engine = _reloaded(tmp_path, mid)
    on_the_foe = [e for e in engine.events if e.actor_id == foe]
    saves = [e for e in on_the_foe if e.event_type == "SAVE_ROLLED"]
    damage = [e.payload["damage_type"] for e in on_the_foe if e.event_type == "DAMAGE_COMMITTED"]
    assert bool(saves) is damaged, (answer, [e.event_type for e in on_the_foe])
    # Whatever the save rolled, the area deals the type its creator chose (here the prepared Thunder), never
    # one of the printed three: a made save may leave nothing to damage, so the type is bounded, not counted.
    assert set(damage) <= {"THUNDER"}, (answer, damage)
    assert _types_of(engine.state.actors[owner]) == ["thunder"], _prepared(engine.state.actors[owner])


def challenge_options():
    """The printed pair of answers, in the words the table shows them."""
    return ["Affect this creature", "Leave this creature unaffected"]


#: Ten Thousand Dregs Field's printed area: "The first time a hostile creature enters the area on a turn
#: or starts its turn there, it makes a Constitution saving throw", with a fixed 3d6 Poison failure.
#: Its printed damage type is *not* a choice, so casting it does not open Seven-Flavor Furnace's
#: once-per-rest preparation -- which is what makes the Court hook the first thing to ask for it.
DREGS_FIELD = "tianxia.talent.alchemy.ten_thousand_dregs_field"
#: The printed four the Court offers for its extra damage, and the fixed type the field itself deals.
COURT_TYPES = {"acid", "fire", "poison", "force"}
FIELD_TYPE = "poison"


def _owner_damage(engine, owner):
    """Every damage type the owner was the source of, lower-cased, in resolution order."""
    return [str(event.payload["damage_type"]).lower() for event in engine.events
            if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == owner]


def _court_extra(owner_damage):
    """The damage the Court added, told apart from the area's own printed failure type.

    Both are committed by the caster -- the area belongs to them -- so the one printed type the area
    always deals is set aside and what is left is the extra damage the Court's own question chose.
    """
    return [kind for kind in owner_damage if kind != FIELD_TYPE]


def _court_then_dregs_field(combat, table, mid):
    """The owner's own turn: the Court's domain goes up, then the area that will catch the foe.

    Neither of these offers a damage-type choice of its own, so Seven-Flavor Furnace's once-per-rest
    preparation is still unanswered when the owner's turn ends -- which is the point of the two tests
    below. A window that is not one of this lane's own falls back to its printed default.
    """
    from tests.r10_fixup_support import cast_sender, commit

    commit(cast_sender(combat, table, mid, "Court of the Three-Legged Cauldron"), _first_or_decline)
    commit(cast_sender(combat, table, mid, "Ten Thousand Dregs Field", at=(6, 4)), _first_or_decline)
    return combat._load_session(mid).engine


def _owner_turn_end(table, mid, answers=()):
    """Ending the owner's turn is what starts the foe's, so this is where the off-turn questions land."""
    state, menu = table.state(mid), table.state(mid)["menu"]
    return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers))


def test_the_court_asks_the_owner_for_the_preparation_and_then_the_damage_type_on_the_ai_foes_turn(
        monkeypatch, tmp_path):
    """Round 1's requested case, reached at last: a pending preparation followed by the Court's own
    damage choice while an AI opponent takes its turn.

    Ten Thousand Dregs Field catches a creature that *starts its turn* in the area, so the save that
    fails there resolves while the foe -- an AI fighter -- begins its turn. Nothing the owner did on its
    own turn offered a damage-type choice, so Seven-Flavor Furnace's once-per-rest preparation is still
    open: the Court's failed-save hook asks for it first and then for the extra damage's type
    (``combat/ext/alchemy_riders.py``, ``court_failed_save``). Both are the caster's own decisions, so
    the table puts both to the caster, who is MANUAL with Ask me here, and nothing is dealt to the foe
    until they are answered.
    """
    from tests.r10_fixup_support import commit

    owner, foe = OWNER, "actor:factory.ffffffff"
    combat, table, mid = _table(monkeypatch, tmp_path, [COURT, DREGS_FIELD, SEVEN])
    engine = _court_then_dregs_field(combat, table, mid)
    assert not _types_of(engine.state.actors[owner]), \
        "the preparation was already answered on the owner's own turn, so nothing was pending off-turn"
    combat.set_controller_mode(mid, actor_id=foe, controller_mode="LOCAL_AUTO")

    asked = []

    def selections(prompt):
        source = (prompt.get("context") or {}).get("reaction_source_id")
        asked.append((source, prompt))
        if source == "choice:needle.seven_flavor":
            return "cold", True
        if source == "choice:needle.cauldron_damage":
            return "cold", True
        return _first_or_decline(prompt)

    prompts = commit(lambda answers=(): _owner_turn_end(table, mid, answers), selections)

    assert [source for source, _ in asked] == ["choice:needle.seven_flavor", "choice:needle.cauldron_damage"], \
        f"the two nested questions did not arrive in the printed order: {[source for source, _ in asked]}"
    assert len(prompts) == len(asked) >= 2, prompts
    for (_, window), source in zip(asked, ("choice:needle.seven_flavor", "choice:needle.cauldron_damage")):
        assert window["context"]["reaction_source_id"] == source
        # Checklist 9: the decision is the caster's, asked on another creature's turn, not the foe's.
        assert window["context"]["reactor_id"] == owner, \
            f"{source} went to the caught creature instead of its caster"
        assert window["reactor"] == "Alchemist", window
    # Checklist 9 and 13: each prompt names the ability, the action that raised it and the creature.
    preparation, cauldron = (window for _, window in asked)
    for part in ("Seven-Flavor Furnace", "Ten Thousand Dregs Field", "Target"):
        assert part in preparation["moment"], (part, preparation["moment"])
    assert cauldron["affected"] == "Target", cauldron
    for part in ("Court of the Three-Legged Cauldron", "Ten Thousand Dregs Field", "Target"):
        assert part in cauldron["moment"], (part, cauldron["moment"])

    engine = _reloaded(tmp_path, mid)
    assert _types_of(engine.state.actors[owner]) == ["cold"], _prepared(engine.state.actors[owner])
    dealt = _owner_damage(engine, owner)
    assert FIELD_TYPE in dealt, f"the area did not deal its own printed {FIELD_TYPE}: {dealt}"
    assert _court_extra(dealt) == ["cold"], \
        f"the Court's extra damage did not use the type that was chosen: {dealt}"

    # The AI fighter now takes its own turn with no window left hanging on the caster.
    state = table.state(mid)
    assert state["menu"]["actor_id"] == foe, state["menu"]["actor_id"]
    assert table.auto_step(mid, state["last_sequence"])["status"] == "COMMITTED"


def test_an_ai_owner_settles_the_same_nested_court_path_without_a_window(monkeypatch, tmp_path):
    """Checklist 9: the same off-turn sequence with an AI owner is resolved by the AI, not asked.

    Same Court, same area, same foe's turn start -- but the owner fights on Auto, so the pending
    preparation and the Court's damage-type choice are decided inside the step. The decision is still
    recorded on the owner's own condition and survives the commit and the reload, so the sealed answer
    is a fact in the saved fight rather than something only the AI remembered.
    """
    from combat.gate4_adapters import ManualControllerAdapter

    owner, foe = OWNER, "actor:factory.ffffffff"
    combat, table, mid = _table(monkeypatch, tmp_path, [COURT, DREGS_FIELD, SEVEN])
    plan = [("Court of the Three-Legged Cauldron", None), ("Ten Thousand Dregs Field", (6, 4))]
    real = combat.controller

    class PlannedAI:
        """The owner's two printed formulae in order, then every later decision is End turn, so neither
        fighter walks out of the area the test is about."""

        def choose_primary_action(self, context):
            engine = combat._load_session(mid).engine
            wanted = plan[0] if plan else None
            candidates = [c for c in engine.legal_candidates() if wanted and wanted[0] in c.display_name
                          and (wanted[1] is None
                               or (c.destination and (c.destination.x, c.destination.y) == wanted[1]))]
            if not candidates:
                return ManualControllerAdapter(lambda _: (
                    next(c.candidate_id for c in engine.legal_candidates() if c.kind.value == "END_TURN"),
                    ())).choose_primary_action(context)
            plan.pop(0)
            return ManualControllerAdapter(lambda _: (candidates[0].candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = PlannedAI()
    for actor in (owner, foe):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    for _ in range(6):
        state = table.state(mid)
        if state["menu"]["actor_id"] is None:
            break
        result = table.auto_step(mid, state["last_sequence"])
        assert result["status"] == "COMMITTED", \
            f"an AI owner was left a player-owned window: {json.dumps(result.get('reaction'))[:400]}"
    assert not plan, f"the AI owner never used its printed formulae: {plan}"

    engine = _reloaded(tmp_path, mid)
    decided = _types_of(engine.state.actors[owner])
    assert decided == [""], f"the AI owner's once-per-rest decision was not recorded: {decided}"
    dealt = _owner_damage(engine, owner)
    extra = _court_extra(dealt)
    assert extra, f"the Court's extra damage never resolved for an AI owner: {dealt}"
    # Nothing prepared, so the extra damage stays on one of the printed four -- never the engine's pick
    # of something outside them.
    assert set(extra) <= COURT_TYPES, dealt


def test_an_ai_owner_decides_its_own_preparation_without_a_window(monkeypatch, tmp_path):
    """Checklist 9: an AI actor decides for itself. The table refuses a human action on an AI fighter, so
    the only way an AI owner's turn runs is Auto Step -- which is why "the AI turns in the paired captures"
    was never proof that this question is answered rather than raised. Here it is: the step commits.

    The decision it reaches is recorded on the owner's own condition and survives the commit and reload, so
    the sealed Long Rest answer is a fact in the saved fight rather than something only the AI remembered.
    """
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.tabletop import TabletopError
    from tests.r10_fixup_support import answer

    owner = OWNER
    combat, table, mid = _table(monkeypatch, tmp_path, [ROTTING, SEVEN])
    candidates = [c for c in combat._load_session(mid).engine.legal_candidates()
                  if "Poison Pill" in c.display_name and "Rotting" in c.display_name]
    chosen = min(candidates, key=lambda c: len(c.display_name))
    real = combat.controller

    class SelectingAI:
        """The AI's own choice, narrowed to this one formula so the test reaches the question in one step."""

        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = SelectingAI()
    for actor in (owner, "actor:factory.ffffffff"):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")

    state, menu = table.state(mid), table.state(mid)["menu"]
    with pytest.raises(TabletopError):
        table.act(mid, chosen.candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])

    answers = []
    for _ in range(4):
        state = table.state(mid)
        result = table.auto_step(mid, state["last_sequence"], list(answers))
        assert result["status"] == "COMMITTED", \
            f"an AI owner was left a player-owned window: {json.dumps(result.get('reaction'))[:400]}"
        break
    assert not answers, "no window was answered: the AI decided for itself"

    engine = _reloaded(tmp_path, mid)
    decided = _types_of(engine.state.actors[owner])
    assert decided == [""], f"the AI owner's once-per-rest decision was not recorded: {decided}"
    damage = [e.payload["damage_type"] for e in engine.events if e.event_type == "DAMAGE_COMMITTED"]
    assert damage == ["NECROTIC"], \
        f"an AI that prepared nothing must still deal the printed types, not the engine's pick: {damage}"

    # A second formula on the same sealed decision: the AI is not asked again either.
    combat.controller = SelectingAI()
    candidates = [c for c in combat._load_session(mid).engine.legal_candidates()
                  if "Poison Pill" in c.display_name and "Rotting" in c.display_name]
    if candidates:
        later = min(candidates, key=lambda c: len(c.display_name))
        real.choose_primary_action = lambda context: ManualControllerAdapter(
            lambda _: (later.candidate_id, ())).choose_primary_action(context)
        for _ in range(4):
            state = table.state(mid)
            result = table.auto_step(mid, state["last_sequence"])
            if result["status"] == "COMMITTED":
                break
        assert result["status"] == "COMMITTED", json.dumps(result.get("reaction"))[:400]
        assert _types_of(_reloaded(tmp_path, mid).state.actors[owner]) == [""], "the sealed decision was lost"


# ----------------------------------------------------------------------------------- Binding Dregs


def test_binding_dregs_takes_the_dash_away_when_the_target_is_on_solid_ground_when_the_save_resolves():
    """"If the target is standing on a solid surface, it also cannot take the Dash action until the start of your
    next turn": the clause is settled as the save resolves. A creature on the ground keeps the ban even if it takes
    off before the expiry; a creature already in the air never gains it, on the ground or in the air."""
    from combat.typed_executor import condition_rules

    engine = _engine([DREGS])
    foe = engine.state.actors[AN]
    events = H._use(engine, "Binding Dregs")
    assert next(e for e in events if e.event_type == "SAVE_ROLLED").payload["success"] is False
    rules = [r for r in condition_rules(foe) if r.get("no_dash")]
    assert rules and rules[0]["requires_ground"] is True, rules

    H._use(engine, "End turn", target=None)  # the foe's own turn: its action menu is the printed Dash
    assert not [c for c in engine.legal_candidates() if "Dash" in c.display_name], "the printed Dash was still offered"

    foe.position = foe.position.model_copy(update={"z": 10})
    assert not [c for c in engine.legal_candidates() if "Dash" in c.display_name], \
        "taking off must not hand back the Dash the formula took away"
    foe.position = foe.position.model_copy(update={"z": 0})
    assert not [c for c in engine.legal_candidates() if "Dash" in c.display_name]

    airborne = _engine([DREGS])
    flying = airborne.state.actors[AN]
    # A hovering creature 5 feet up is still inside Binding Dregs' printed 30-foot range (the engine measures it in
    # three dimensions), so the formula reaches it and only the printed solid-surface clause is in question. It
    # hovers rather than flies so the engine's own falling rule does not put it back on the floor first.
    flying.hover = True
    flying.position = flying.position.model_copy(update={"z": 5})
    airborne._apply_condition(flying, "condition:typed.no_dash", "test:independent-dash-ban", AN,
                              expires_on="UNTIL_REMOVED")
    events = H._use(airborne, "Binding Dregs")
    assert flying.position.z == 5, "the target fell before the clause could be read"
    assert len([r for r in condition_rules(flying) if r.get("no_dash")]) == 1
    assert [c.source_definition_id for c in flying.conditions.values()] == ["test:independent-dash-ban"], \
        "airborne Dregs must leave the independent ban alone and add no ban of its own"
    riders = [e.payload.get("rider", "") for e in events if e.event_type == "GM_RIDER"]
    assert any("does not prevent" in text and "Dash" in text for text in riders), riders
    _end_turn(airborne, ME)
    assert not [c for c in airborne.legal_candidates() if c.source_definition_id == "system:combat.dash"]


def test_airborne_binding_dregs_message_preserves_an_independent_dash_ban_at_the_table(monkeypatch, tmp_path):
    """Dregs qualifies only its own ban; another effect still removes Dash after commit/reload."""
    from tests.auto9f1_replay_evidence import STOCK as setup_stock
    from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, turn
    from tests.test_lock_choices import install

    install(monkeypatch, "d20_result", lambda engine, roll, context:
            {"source_id": "test:airborne-dregs", "operation": "replace", "natural_result": 1}
            if engine.d20_context().get("kind") == "save" else None)
    independent_ban = [{"type": "condition", "condition": "no_dash", "applies_to": "self",
                        "expires_on": "UNTIL_REMOVED"}]
    combat, table, mid = fight(tmp_path, owned=[DREGS], effects=setup_stock,
                               right=["TAL_ALCHEMY_QI_INFUSION_PILL"], right_effects=independent_ban,
                               primary="Stamina", seed="AUTO9-AIRBORNE-DASH",
                               positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6, "z": 5}},
                               actor_template_overrides={RIGHT: {"hover": True}})
    turn(combat, table, mid, RIGHT)
    act(combat, table, mid, "Test setup")
    turn(combat, table, mid, LEFT)
    act(combat, table, mid, "Test setup")
    act(combat, table, mid, "end")
    turn(combat, table, mid, LEFT)
    act(combat, table, mid, "Binding Dregs")
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    assert target.position.z == 5
    bans = [c for c in target.conditions.values() if c.condition_id == "condition:typed.no_dash"]
    assert len(bans) == 1 and bans[0].source_definition_id.startswith("action:test.h36.")
    riders = [e.payload.get("rider", "") for e in engine.events if e.event_type == "GM_RIDER"]
    assert any("Binding Dregs" in text and "does not prevent" in text
               and "Dash" in text and "not standing on a solid surface" in text for text in riders), riders
    assert not any("can still take the Dash action" in text for text in riders)
    act(combat, table, mid, "end")
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == RIGHT
    assert not any(c.source_definition_id == "system:combat.dash" for c in engine.legal_candidates())


def test_binding_dregs_reduces_the_printed_speed_on_both_save_outcomes_and_then_expires():
    """The Speed rider is untouched by the Dash work: 10 feet off a failed save, 5 off a made one, both ending at
    the start of the caster's next turn."""
    for dc, penalty in ((FAIL, -10), (MADE, -5)):
        engine = _engine([DREGS], dc=dc)
        foe = engine.state.actors[AN]
        base = engine._effective_speed(foe)
        events = H._use(engine, "Binding Dregs")
        saved = next(e for e in events if e.event_type == "SAVE_ROLLED")
        assert saved.payload["success"] is (dc == MADE), saved.payload["success"]
        applied = [e for e in events if e.event_type == "MODIFIER_APPLIED"
                   and e.payload.get("target_field") == "speed_ft"]
        assert [e.payload["value"] for e in applied] == [penalty], [e.payload for e in applied]
        assert engine._effective_speed(foe) == base + penalty, (dc, engine._effective_speed(foe))

        _end_turn(engine, ME)
        _end_turn(engine, AN)  # the caster's next turn starts: the printed duration is over
        assert engine._effective_speed(foe) == base, (dc, engine._effective_speed(foe))


# ----------------------------------------------------------------------------------- Court of the Three-Legged Cauldron


def test_the_court_gives_one_cp_back_for_a_field_formula_once_per_turn():
    """"Once per turn when you use Field Formula, reduce its CP cost by 1, minimum 0": the fighter's own Path pool
    is given the 1 CP back as the formula resolves, and only once in the turn."""
    engine = _engine([COURT, VENT])
    me = engine.state.actors[ME]
    engine.state.actors[ME].resources[STOCK] = 5
    H._use(engine, "Court of the Three-Legged Cauldron")
    assert "condition:typed.alchemy_court_damage" in {c.condition_id for c in me.conditions.values()}, \
        "the Court's own domain is not up"

    before = me.resources[STAMINA]
    first = H._use(engine, "Furnace Vent at 5,7", target=None)
    assert _spent(first, STAMINA) == 1, "Furnace Vent charged its printed 1 CP more than once"
    assert me.resources[STAMINA] == before, "the printed 1 CP discount was not given back"
    assert any(e.event_type == "RESOURCE_GAINED" and e.payload.get("resource_id") == STAMINA for e in first)

    me.action_available, me.bonus_action_available = True, True
    me.resources[STOCK] = 5
    before = me.resources[STAMINA]
    second = H._use(engine, "Furnace Vent at 5,7", target=None)
    assert me.resources[STAMINA] == before - 1, "the discount was paid twice in one turn"


def test_a_formula_with_no_court_pays_its_printed_cp_once():
    """The regression this lane found: the printed "Cost: 1 CP and one Reagent Stock" was charged twice."""
    engine = _engine([VENT])
    me = engine.state.actors[ME]
    me.resources[STOCK] = 5
    before = me.resources[STAMINA], me.resources[STOCK]
    events = H._use(engine, "Furnace Vent at 5,7", target=None)
    assert (_spent(events, STAMINA), _spent(events, STOCK)) == (1, 1), [
        e.payload for e in events if e.event_type == "RESOURCE_SPENT"]
    assert (me.resources[STAMINA], me.resources[STOCK]) == (before[0] - 1, before[1] - 1)


def test_the_court_discount_never_reaches_past_the_cost_floor():
    """A formula the fighter can only pay part of is still not theirs to use; the discount is given back, not lent."""
    engine = _engine([COURT, VENT])
    me = engine.state.actors[ME]
    me.resources[STOCK] = 5
    H._use(engine, "Court of the Three-Legged Cauldron")
    me.resources[STAMINA] = 0
    assert not [c for c in engine.legal_candidates() if "Furnace Vent" in c.display_name], \
        "a formula the fighter cannot pay became legal"
