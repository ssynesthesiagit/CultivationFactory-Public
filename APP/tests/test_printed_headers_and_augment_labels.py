"""What the fight and the sheet say about a cost, in words a newcomer can read (owner MMX69, MiniMax hunt 85 #1-#3).

Three leaks, all of them text a player reads rather than mechanics that misbehave:

  * Every free ability printed its cost as the literal ``None`` ("Cost: None"), which reads as a broken value
    rather than "this costs nothing".  A missing cost now reads as
    ``combat.display_text.FREE_COST_LINE`` ("Cost: no resource cost").  It says nothing about actions, because a
    resource-free ability can still cost an Action, a Bonus Action or a Reaction (MMX69r).
  * A few printed records lost the line break between two header lines, so the owner read one run-together word
    ("Cost: NoneConcentration: Not required").  combat/display_text.py puts the break back.
  * The button that clears every augment off an ability was labelled with the bare string
    "Augment Darkness: none", which reads as a broken value rather than the button that removes them all.

These fight at the level each bug showed.  The header leaks are checked across every printed ability the ship
ships, through the same two display paths a hover and a fight tooltip use; the clear-augment label is checked on
a real compiled fight's real menu, assembled by the real service, because that is where the owner read it.

Renaming the clear-augment button is display only.  ``source_definition_id`` and ``candidate_id`` are pinned
here so a later change cannot quietly move candidate identity: a candidate's identity is hashed from the kind,
the actor, the source, the targets and the state version (combat/gate2_engine.py), never from its label.
"""
import re
from pathlib import Path

from combat.display_text import FREE_COST_LINE, FREE_COST_VALUE, augment_toggle_label, printed_headers
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.status_text import printed_excerpt, printed_rules
from combat import tabletop
from combat.tabletop_service import TabletopService
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.nightshade"
DARK_SPHERE = "tianxia.sphere.dark"
#: A seed whose initiative puts the player up first, so the menu really is the player's.
MENU_SEED = "MMX66"

#: A printed cost that never got a value, in either of the shapes the owner's records use.
_NONE_COST = re.compile(r"Cost:\s*(?:None|null|nil)\b", re.I)
#: One printed header key running straight into the next one, e.g. "NoneConcentration:".
_RUN_TOGETHER = re.compile(r"[A-Za-z0-9](?:Concentration|Tags|Duration|Area|Range|Trigger|Effect|Target|Use Limit): ")


def _sheet(*talents: str) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": [DARK_SPHERE], "learned_talent_record_ids": list(talents)}}


def _menu(tmp_path, *talents: str, tag: str = "text") -> dict:
    """The fight menu exactly as a player's browser receives it: a real service, a real compiled fight, a real
    state answer -- not the engine's candidates seen from the side."""
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        [compile_character(_sheet(*talents), actor_id=ME, reaction_plan={"ask": False}),
         compile_character(_sheet(), actor_id=AN)], [ME, AN], {ME: "team:a", AN: "team:b"},
        {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [AN],
        control_modes={ME: "MANUAL", AN: "MANUAL"}, match_seed=MENU_SEED,
        display_name=f"MMX69 {tag}", maximum_rounds=5)["match_id"]
    menu = TabletopService(combat, tmp_path).state(mid)["menu"]
    # The seed decides who is up first; these labels are the player's, so say so plainly
    # rather than letting a seed change look like a missing button.
    assert menu.get("actor_id") == ME, f"the menu is not the player's turn: {menu.get('actor_id')}"
    return menu


# ------------------------------------------------------------------------------------- #1 a free ability never prints "Cost: None"
def test_no_printed_ability_shows_a_literal_none_cost_through_either_display_path():
    """Every shipped record is swept for the old defect on both text routes: the status hover (printed_excerpt ->
    plain) and the printed header block the fight tooltip is built from.  This is the sweep; the integration
    regressions further down are what a player actually reads, through the real service."""
    offenders = []
    for record in printed_rules():
        if _NONE_COST.search(printed_excerpt(record)):
            offenders.append((record, "hover"))
        if _NONE_COST.search(printed_headers(printed_rules()[record])):
            offenders.append((record, "printed block"))
    assert not offenders, f"a free ability still prints a literal None cost: {offenders[:5]}"


def test_a_free_ability_says_in_words_that_it_costs_no_resource():
    """The replacement is plain English, not a code value, and keeps the printed header block around it.  The
    literal words are asserted, not just the helper's constant, so renaming the constant cannot pass this."""
    text = printed_excerpt("TAL_ILLUSION_MINOR_ILLUSION")
    assert "Cost: no resource cost" in text
    assert "None" not in _NONE_COST.sub("", text).split("Tags:")[0].replace("Not required", "")


def test_a_free_ability_never_promises_that_it_costs_no_action():
    """A resource-free ability can still cost an Action, a Bonus Action or a Reaction.  Saying "no action or
    resource" told a player to use Darkness, Minor Illusion, Shadow Stash and Carry Voice for free, which
    contradicts the timing requirement each of them prints.  The wording this lane adds speaks only about
    resources, and the ability's own timing line must survive beside it (MMX69r).

    The check is on the wording the cleanup adds, not on the owner's prose: 25 shipped records explain
    themselves with the words "no action" ("the rider does not require an additional Action"), and 45 print their
    own "Action Type: No Action" header.  That is the owner's real text and must not be touched."""
    assert "action" not in FREE_COST_LINE.casefold(), FREE_COST_LINE
    assert "action" not in FREE_COST_VALUE.casefold(), FREE_COST_VALUE

    free_abilities = [record for record, text in printed_rules().items() if _NONE_COST.search(text)]
    assert free_abilities, "no printed record has a missing cost, so this guard is no longer checking anything"
    offenders = [record for record in free_abilities
                 if "no action or resource" in str(printed_excerpt(record)).casefold()
                 or "no action or resource" in printed_headers(printed_rules()[record]).casefold()]
    assert not offenders, f"a free ability still promises a free action: {offenders[:5]}"

    # The three the review named still say what they cost to use, right next to the cost line.
    for record, timing in (("TAL_ILLUSION_MINOR_ILLUSION", "Action Type: Action"),
                           ("TAL_DARK_SHADOW_STASH", "Action Type: Bonus Action"),
                           ("DARK_BASE_DARKNESS", "Action Type: Action")):
        text = printed_excerpt(record)
        assert timing in text, f"{record} lost its timing requirement: {text[:160]!r}"
        assert "Cost: no resource cost" in text, f"{record} lost its readable cost: {text[:160]!r}"
    assert "Timing Detail: Bonus Action or 1 minute" in printed_excerpt("TAL_SOUND_CARRY_VOICE")


def test_a_cost_that_explains_itself_keeps_the_owners_own_words():
    """"None, or 1 CP for extended use" is a real printed cost: the missing word becomes English, the rest is the
    owner's own sentence and is not lost.  The conditional form says "no resource cost" too, so it cannot promise
    a free Bonus Action either."""
    text = printed_excerpt("TAL_SOUND_CARRY_VOICE")
    assert "Cost: no resource cost, or 1 CP for extended use" in text
    assert "no action" not in text.casefold()


def test_a_cost_that_is_already_readable_is_left_exactly_as_printed():
    """A real cost is never rewritten, so the fix cannot quietly change what an ability charges."""
    for record, kept in (("TAL_ILLUSION_MINOR_ILLUSION", "Action Type: Action"),
                         ("DARK_BASE_DARKNESS", "Area:")):
        assert kept in printed_headers(printed_rules()[record])


# ------------------------------------------------------------------------------------- #2 two header lines never run together
def test_no_printed_record_runs_two_header_lines_together():
    """The three records that lost their line break read as one word ("Cost: NoneConcentration: Not required").
    A filter cannot tell that from a real cost, so the break is put back before the cost is read.  The missing
    break is in the owner's printed compendium, which is bundled content and is not edited here; what a player
    must never see is the run-together word, so that is what is checked, on both routes."""
    offenders = []
    for record, raw in printed_rules().items():
        for label, text in (("hover", printed_excerpt(record)), ("printed block", printed_headers(raw))):
            if _RUN_TOGETHER.search(str(text)):
                offenders.append((record, label))
    assert offenders == [], f"a rendered record still runs two header lines together: {offenders[:5]}"


def test_the_three_run_together_records_read_as_two_lines():
    for record in ("EARTH_BASE_SET_FOUNDATION", "ICE_BASE_CRYSTALLIZE_PATH", "TAL_ILLUSION_MINOR_ILLUSION"):
        text = printed_headers(printed_rules()[record])
        assert "NoneConcentration" not in text
        assert "Concentration: Not required" in text, f"{record} lost its Concentration line: {text[:200]!r}"


def test_a_header_value_that_merely_starts_with_a_header_word_is_not_split():
    """"Duration: Concentration, up to 1 minute" is one header line whose value happens to be a Concentration:
    splitting it would invent a header the owner never printed."""
    text = printed_excerpt("DARK_BASE_DARKNESS")
    assert "Concentration, up to 1 minute" in text or "Duration: Concentration" in text


# --------------------------------- the text a player actually reads, through the real service (MMX69r)
def test_the_fight_menu_description_says_what_a_free_ability_costs(tmp_path):
    """The hover text on a fight button, exactly as a player's browser receives it: a real service, a real compiled
    fight, the real ``menu`` answer.  Literal expected text, not the helper's constant, so unwiring the cleanup
    from either display path fails here instead of passing on a helper call."""
    menu = _menu(tmp_path, "DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")
    rows = {group["label"]: str(group.get("description") or "") for group in menu["actions"]}
    for label, cost in (("Darkness", "no resource cost"), ("Darkness + Obfuscation", "1 Qi")):
        assert label in rows, f"the menu has no {label} row: {sorted(rows)}"
        description = rows[label]
        assert f"Cost: {cost}" in description, f"{label} still misprices itself: {description[:200]!r}"
        assert "Action Type: Action" in description, f"{label} lost its action requirement: {description[:200]!r}"
        assert "no action or resource" not in description.casefold(), description[:200]
        assert "Cost: None" not in description, description[:200]


def test_the_augment_toggle_tooltip_reads_as_two_lines(tmp_path):
    """The augment buttons are the one place a real fight row is described by tabletop._compiled_description
    (combat/tabletop.py), the wiring the sweep tests above never touch.  That path is checked here, through the
    service, so removing the cleanup call from it fails the build."""
    menu = _menu(tmp_path, "DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")
    toggles = {group["label"]: str(group.get("description") or "") for group in menu["actions"]
               if group["label"].startswith("Augment Darkness")}
    assert toggles, f"the menu has no augment buttons: {[g['label'] for g in menu['actions']]}"
    for label, description in toggles.items():
        # Obfuscation costs 1 CP when used; selecting its setting is free.
        assert "Choosing this option takes no action and costs nothing" in description, description
        if label.endswith("Obfuscation"):
            assert "Augment - 1 cultivation points (your Path resource)" in description, description
        assert "NoneConcentration" not in description, f"{label} runs two header lines together: {description[:200]!r}"
        assert "no action or resource" not in description.casefold(), description[:200]


def test_a_joined_header_record_reaches_the_tooltip_as_two_lines():
    """The two joined-header records read through the exact function tabletop.py feeds a fight button
    (engine_button_description -> _compiled_description), which is the wiring the sweep tests never touch.

    The two are checked for what each one returns: _compiled_description keeps the owner's line breaks, so the
    split is visible there; engine_button_description is what the service hands the browser and flattens them,
    so the words are checked there.  Both must be free of the joined word and the old promise."""
    for record in ("EARTH_BASE_SET_FOUNDATION", "ICE_BASE_CRYSTALLIZE_PATH"):
        row = {"parameters": {"typed": {"forged_from": record}}}
        compiled = tabletop._compiled_description(row)
        assert compiled, f"{record} has no compiled description at all"
        assert "NoneConcentration" not in compiled, f"{record} still runs together: {compiled[:200]!r}"
        assert "Cost: no resource cost\nConcentration: Not required" in compiled, \
            f"{record} did not reach the tooltip as two lines: {compiled[:260]!r}"
        assert "Action Type: Action" in compiled, f"{record} lost its action requirement: {compiled[:200]!r}"

        served = tabletop.engine_button_description(row)
        assert served, f"{record} has no service description at all"
        assert "NoneConcentration" not in served, served[:200]
        assert "Cost: no resource cost" in served and "Concentration: Not required" in served, served[:260]
        assert "no action or resource" not in served.casefold(), served[:200]


# ------------------------------------------------------------------------------------- #3 the clear-augment button says what it does
def test_the_clear_augment_button_is_labelled_in_words(tmp_path):
    """The bug as an owner saw it: the button that clears every augment off Darkness read "Augment Darkness:
    none", beside the real choices.  It now says what pressing it does."""
    labels = [group["label"] for group in _menu(tmp_path, "DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")["actions"]]
    clear = [label for label in labels if label.startswith("Augment Darkness") and "no augments" in label]
    assert len(clear) == 1, f"no clear-augment button for Darkness: {labels}"
    assert not [label for label in labels if label.endswith(": none")], f"a button still reads ': none': {labels}"
    assert not [label for label in labels if ": None" in label], f"a button still prints a code value: {labels}"


def test_both_supported_darkness_augments_get_a_clear_augment_button(tmp_path):
    """Both augment talents a Darkness character can learn get the clear button, named from the ability.

    Coverage is honestly Darkness-only: of the spheres a character sheet can be built on, Darkness is the only
    one whose printed "Augment" lines compile into an augment loadout (checked against Fire, Ash, Flowers, Dreams
    and Life here before this claim was narrowed, in MMX69r).  The naming rule itself is general and is checked
    per ability in the compiler-level test below."""
    for talent in ("TAL_DARK_OBFUSCATION", "TAL_DARK_GREATER_DARKNESS"):
        # A different character is a different immutable bundle, so each gets its own userdata directory.
        labels = [group["label"] for group in _menu(tmp_path / talent, "DARK_BASE_DARKNESS", talent, tag=talent)["actions"]]
        assert augment_toggle_label("Darkness", None) in labels, f"Darkness has no clear-augment button for {talent}: {labels}"


def test_the_clear_button_is_named_from_the_ability_whatever_it_is():
    """The rule is general, at the place it is built: the compiler takes the ability's own printed name, so any
    ability with an augment loadout gets a clear button named for it, and a real choice keeps its printed name.
    Checked here over the compiler's own rows so the claim does not rest on Darkness being the only family."""
    catalog = compile_character(_sheet("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION"),
                                actor_id=ME, reaction_plan={"ask": False})["action_catalog"]
    clear = [row["source_definition_id"] for row in catalog if row.get("display_name") == augment_toggle_label("Darkness", None)]
    assert clear == ["action:typed.1a4cfe2e3d.DARK_BASE_DARKNESS.toggle.none"], catalog
    assert augment_toggle_label("Greater Darkness", None) == "Augment Greater Darkness: no augments (clears all of them)"
    assert augment_toggle_label("Set Foundation", None).startswith("Augment Set Foundation:")
    assert augment_toggle_label("Set Foundation", "Warded Stone") == "Augment Set Foundation: Warded Stone"


def test_the_real_augment_choices_are_not_renamed(tmp_path):
    """Only the clear button's wording changed; the choices a player picks are still labelled as printed."""
    labels = [group["label"] for group in _menu(tmp_path, "DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION")["actions"]]
    assert "Augment Darkness: Obfuscation" in labels, labels


# ------------------------------------------------------------------------------------- the rename is display only
def test_renaming_the_clear_augment_button_does_not_move_candidate_identity():
    """A candidate's id is hashed from its kind, actor, source, targets, destination and state version -- never
    from its label (combat/gate2_engine.py).  Proved here rather than argued: building the very same candidate
    under a different label yields the very same id, so renaming a button cannot lock a player out of a saved
    fight.  The clear toggle also keeps the source id its identity has always been built from."""
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX69", typed_bundles=(compile_character(
        _sheet("DARK_BASE_DARKNESS", "TAL_DARK_OBFUSCATION"), actor_id=ME),),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    actor = engine.state.actors[ME]
    real = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(".toggle.none"))
    assert real.display_name == augment_toggle_label("Darkness", None)

    relabelled = engine._candidate(real.kind, actor, real.source_definition_id, "a completely different label",
                                   target_ids=real.target_ids, metadata=(real.metadata or None) or None)
    assert relabelled.candidate_id == real.candidate_id, "the button's label is part of its identity"
    assert relabelled.source_definition_id == real.source_definition_id
