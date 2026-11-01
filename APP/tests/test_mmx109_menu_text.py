"""Every ability/toggle the table offers carries its printed rule text, and an Ask-me prompt names its own
creature (fight audit 2026-10-03, HUNT108 items 1 and 2).

HUNT108 #1: 140 ability/toggle labels reached the table menu with a completely EMPTY description, the four
universal actions among them (258 button presses). Pressing "Core Tempering Expression: Blood-Furnace
Circulation" -- a button that said nothing -- silently applied a whole-fight self-condition. The rule text for
all of them already existed: BASIC_DESCRIPTIONS for the engine's built-in actions, each plug-in's own
setting_description, and the owning feature's authority entry. The table menu read none of it, because
tabletop_service._menu_descriptions filled group["description"] from engine_button_description() alone, and that
function is empty for a row with no rules entry of its own.

HUNT108 #2: a plug-in choice riding the reaction transport (Lian Feng's "Beast Aspects") reported
action="Disengage" -- the warhorse summon's move two steps earlier. The choice is the reactor's own decision
about their own state, so the outer turn's action is not this prompt's action.

Overlaps: MMX104 builds one shared hover/description formatter (it formats descriptions that already exist; it
did not cover a button with no source text at all) and MMX102 fixes prompt naming for summons. Both touch the
same two functions; this lane fixes the missing source and the foreign `action`, not the wording of either.

Pre-merge review fixes (MMX109f1), all in the text and in this file's own protective tests:
  * the five Tension Responses said "Free" while `vessel.tension` spends a Tension Mark (and spends it before the
    target's save runs, and spends it on the NEAREST marked creature for Guarding Vessel, not the protected one);
  * the Raise tooltip told every owner "one active vessel at a time" although _limit() allows two with Two-Body
    Control, so it is now derived from _limit() and the two cases are asserted apart;
  * `test_a_plug_in_choice_does_not_name_another_creatures_action` supplied no trigger actor, so `attacker_id` was
    None and the base already returned an empty action -- the test passed on the unfixed code. It now supplies the
    warhorse, which is what makes it fail without the fix;
  * the corpus guard swallowed every exception from both presentation surfaces and from the compiler, so a new
    crash could pass. Exclusions are now named (KNOWN_UNREADABLE) and coverage is asserted; the test is renamed
    to say it is a stride-7 sample, not a whole-corpus guarantee.

Not a saved-fight lock file: combat/tabletop.py and combat/tabletop_service.py only.
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat.ext import bodya_body_refining as body
from combat.ext import vessel
from combat.factory_compiler import compile_character
from combat.tabletop import BASIC_DESCRIPTIONS, SYSTEM_ACTION_DESCRIPTIONS, auto_buttons, untyped_button_text
from combat.tabletop_service import TabletopService
from tests.h1_support import mechanics, sheet
from tests.h48_table_support import fixture

CTE = "tianxia.path.body_refining.feature.core_tempering_expression"
UNIVERSAL = ("Dodge", "Dash", "Disengage", "Hold position")


class _CatalogRow:
    """The engine hands _menu_descriptions an ActionDefinition, not the compiled row."""

    def __init__(self, row):
        self._row = row
        self.economy = row.get("economy", "NONE")
        self.costs = row.get("costs", ())
        self.parameters = row.get("parameters", {})

    def model_dump(self, mode="json"):
        return self._row


def _engine_for(bundle):
    return SimpleNamespace(action_catalog={row["source_definition_id"]: _CatalogRow(row)
                                           for row in bundle["action_catalog"]},
                           state=SimpleNamespace(actors={}))


def _menu_descriptions(bundle):
    """{label: description} for a compiled character, exactly as the table menu presents its buttons."""
    menu = {"actions": [{"source_definition_id": row["source_definition_id"], "label": row["display_name"]}
                        for row in bundle["action_catalog"]]}
    TabletopService._menu_descriptions(menu, _engine_for(bundle))
    return {group["label"]: group.get("description") or "" for group in menu["actions"]}


# --------------------------------------------------------------------------- #1 the reported table-menu failure


def test_universal_actions_and_core_tempering_expression_carry_their_rule_text_on_the_table(tmp_path):
    """The exact HUNT108 F13 failure: real persisted match, real menu, no empty description."""
    for name, path_features in (("plain", ()), ("cte", (CTE,))):
        _, table, match_id, _send, _commit = fixture(tmp_path / name, [], seed="mmx109", path_features=path_features)
        groups = table.state(match_id)["menu"]["actions"]
        assert groups
        empty = [g["label"] for g in groups if not (g.get("description") or "").strip()]
        assert not empty, f"{name}: {empty}"
        by_label = {g["label"]: g["description"] for g in groups}
        for label in UNIVERSAL:
            assert by_label[label] == BASIC_DESCRIPTIONS["Hold Position" if label == "Hold position" else label], label
            group = next(g for g in groups if g["label"] == label)
            assert group["description"] in group["hover"]["text"], "the shared card must retain the fallback rule"


def test_each_core_tempering_expression_button_says_which_expression_it_picks(tmp_path):
    """One printed text per button: a player must be able to tell the three apart (checklist 13)."""
    _, table, match_id, _send, _commit = fixture(tmp_path / "cte-text", [], seed="mmx109", path_features=(CTE,))
    by_label = {g["label"]: g["description"] for g in table.state(match_id)["menu"]["actions"]}
    picks = {label: text for label, text in by_label.items() if label.startswith("Core Tempering Expression: ")}
    assert len(picks) == len(body.LABELS), sorted(picks)
    for label, text in picks.items():
        option = label.partition(": ")[2]
        assert f"This button picks: {option}." in text, label
        assert "Stamina" in text, label


def test_untyped_button_text_covers_every_builtin_action_and_is_inert_for_a_typed_ability():
    """The shared seam, and its default-inert behaviour for a row that has its own text (checklist 3)."""
    for source, text in SYSTEM_ACTION_DESCRIPTIONS.items():
        assert text, source
        assert untyped_button_text({"source_definition_id": source, "display_name": source}) == text
    assert untyped_button_text({"source_definition_id": "system:combat.hold_position",
                                "display_name": "Hold position"}) == BASIC_DESCRIPTIONS["Hold Position"]
    # No bundle: a toggle cannot be matched to its feature, so it stays empty rather than guessing.
    assert untyped_button_text({"source_definition_id": "action:typed.x.y", "display_name": "Nothing: here"}) == ""


def test_the_initiative_roll_says_what_it_does():
    """The corpus guard found this one: the sheet's Initiative button carried no text at all."""
    button = next(b for b in auto_buttons({"action_catalog": []}, {"initiative": 3}) if b["id"] == "roll:initiative")
    assert button["description"] == BASIC_DESCRIPTIONS["Initiative"]
    assert "Dexterity" in button["description"]


# The one inherited defect this guard may step over, named by mechanic id.  A full-corpus probe (not this stride-7
# sample) found a single mechanic whose COMPILED effect is a plain string, which tabletop.damage_text's walk cannot
# read.  It is a pre-existing data defect, not a presentation regression, and repairing it is its own follow-up --
# the review was explicit that fixing this guard must not wait on it.  Empty today, because the id lives outside this
# sample; if it ever falls inside, add it here deliberately rather than re-opening a silent `except Exception`.
KNOWN_UNREADABLE: frozenset[str] = frozenset()
# The sheet's generic per-ability rolls are named by the roll itself ("Perception check", "Stealth"): a player
# already knows what they are, and they are not an ability or a toggle.  A named skip, not a swallowed crash.
GENERIC_ROLL_KINDS = frozenset({"check", "save", "skill"})


def test_no_offered_button_in_a_stride7_sample_of_the_corpus_has_an_empty_description():
    """A stride-7 SAMPLE of the ability corpus, not a whole-corpus guarantee: sheet button and table-menu
    description for every row the compiler produces.

    Nothing is skipped silently any more.  A mechanic that will not compile fails the test outright, and one whose
    presentation raises fails unless its id is named in KNOWN_UNREADABLE, so a NEW crash introduced by this fallback
    surfaces instead of turning a broken character into a passing test.  The last assertion checks the sample was
    really presented, so a shrink cannot make the guard vacuous.
    """
    sample = list(mechanics())[::7]
    assert sample, "the mechanics corpus is empty: this guard would pass on nothing"
    empty = []
    presented = []
    for mid in sample:
        bundle = compile_character(sheet(mid, cl=10), actor_id="actor:mmx109")
        try:
            buttons = auto_buttons(bundle, {})
            menu = {"actions": [{"source_definition_id": row["source_definition_id"]} for row in bundle["action_catalog"]]}
            TabletopService._menu_descriptions(menu, _engine_for(bundle))
        except Exception as exc:  # noqa: BLE001 - re-raised unless the mechanic is a named inherited failure
            if mid not in KNOWN_UNREADABLE:
                raise AssertionError(f"{mid} crashed a presentation surface: {type(exc).__name__}: {exc}") from exc
            continue
        presented.append(mid)
        for button in buttons:
            if str(button.get("id", "")).split(":")[0] in GENERIC_ROLL_KINDS:
                continue
            if not (button.get("description") or "").strip():
                empty.append(("sheet", mid, button["label"]))
        for row, group in zip(bundle["action_catalog"], menu["actions"]):
            if not (group.get("description") or "").strip():
                empty.append(("menu", mid, row["display_name"]))
    assert not empty, empty[:20]
    assert len(presented) == len(sample) - len(KNOWN_UNREADABLE.intersection(sample)), \
        f"only {len(presented)} of {len(sample)} sampled mechanics reached the presentation surfaces"


# ------------------------------------- #1b/#2 the vessel text the pre-merge review found misleading (MMX109f1)

TWO_BODY = "tianxia.talent.puppetry.two_body_control"
PUPPET_WITHOUT_TWO_BODY = "tianxia.talent.puppetry.long_silk_thread"  # a Puppetry talent that is not Two-Body Control
ON_TARGET = ("tug", "cross", "snap", "snap_last")  # the responses that spend the mark on the chosen target


def _vessel_menu(*talents, cl=10):
    labels = _menu_descriptions(compile_character(sheet(list(talents) or [PUPPET_WITHOUT_TWO_BODY], cl=cl),
                                                   actor_id="actor:mmx109f1"))
    return {label: text for label, text in labels.items()
            if label.startswith("Tension Response:") or label.startswith("Raise the Vessel")}


def test_every_tension_response_says_it_spends_a_tension_mark():
    """Review finding 1: the buttons all said "Free" while execution removed a Tension Mark (vessel.py `tension`).

    A player must be able to see what a button costs before pressing it, and the mark really is gone afterwards --
    including when the target's Strength save succeeds.
    """
    responses = {label: text for label, text in _vessel_menu(PUPPET_WITHOUT_TWO_BODY).items()
                 if label.startswith("Tension Response:")}
    assert len(responses) == len(vessel.RESPONSES), sorted(responses)
    for label, text in sorted(responses.items()):
        assert "spends one of your Tension Marks" in text, f"{label}: {text}"
        assert "one Tension Response per turn" in text, label
        # The old text opened with "Free", which is what a player reads as "this costs nothing".
        assert not text.startswith("Free"), label
    # The ordinary responses spend the mark on the creature the player chose as the target.
    for key in ON_TARGET:
        text = responses[f"Tension Response: {vessel.RESPONSES[key]}"]
        assert "the mark on the marked creature you choose" in text, f"{key}: {text}"
    # Guarding Vessel is the exception: the +2 AC goes where the player points, the mark comes off another creature.
    guarding = responses["Tension Response: Guarding Vessel"]
    assert "not on the creature you protect" in guarding, guarding
    assert "nearest to you" in guarding, guarding
    # The mark is removed before the save runs, so a successful Strength save does not keep it.
    tug = responses["Tension Response: Tug the Joint"]
    assert "spent even if that creature's saving throw succeeds" in tug, tug


@pytest.mark.parametrize("cl,dice", [(1, 1), (4, 1), (5, 2), (10, 2), (11, 3), (16, 3), (17, 4), (20, 4)])
def test_snap_the_thread_menu_states_its_level_scaled_d6_damage(cl, dice):
    """Both menu buttons show Snap's own dice, never Puppet Strike's d8 damage."""
    menu = _vessel_menu(cl=cl)
    for response, damage in (("snap", f"{dice}d6 Force damage"),
                             ("snap_last", f"{dice}d6 damage of the type of the vessel's last Puppetry attack")):
        text = menu[f"Tension Response: {vessel.RESPONSES[response]}"]
        assert f"The target takes {damage}." in text, text
        assert "spends one of your Tension Marks" in text, text
        assert "the mark on the marked creature you choose" in text, text
        assert "own damage die" not in text, text


def test_the_raise_tooltip_agrees_with_the_active_vessel_limit_the_owner_gets():
    """Review finding 2: the tooltip said "one at a time" for everyone, but _limit() allows two with Two-Body Control."""
    without = _vessel_menu(PUPPET_WITHOUT_TWO_BODY)["Raise the Vessel (1 CP)"]
    with_talent = _vessel_menu(TWO_BODY)["Raise the Vessel (1 CP)"]
    assert "one active vessel at a time" in without, without
    assert "raising a second makes the first inactive" in without, without
    assert "two active vessels at once" in with_talent, with_talent
    assert "does not put the first down" in with_talent, with_talent
    assert without != with_talent, "the limit sentence must depend on the talent the owner has"


def test_the_vessel_buttons_never_reach_a_character_without_the_puppetry_sphere():
    """Checklist 3: the corrected text is inert for anyone who does not own the sphere (it needs a mark and a thread)."""
    labels = _menu_descriptions(compile_character(sheet(CTE, cl=10), actor_id="actor:mmx109f1"))
    assert not [label for label in labels if label.startswith("Tension Response:") or "Vessel" in label], \
        sorted(label for label in labels if "Vessel" in label)


# --------------------------------------------------------------------------- #2 a prompt must not name another creature's action


def _prompt(reactor, *, trigger, extension_choice, recent_events, checkpoint="TYPED:CHOICE"):
    service = TabletopService.__new__(TabletopService)
    service._names = {"m": ({"actor:a": "Ally", "actor:me": "Lian Feng", "actor:horse": "Warhorse"},
                           {"system:combat.disengage": "Disengage", "beast": "Beast Aspects"})}
    context = {"reactor_id": "actor:me", "checkpoint": checkpoint, "reaction_source_id": "choice:beast.active:1",
               "choice_trigger": trigger, "extension_choice": extension_choice, "recent_events": recent_events}
    return service._reaction_prompt_fields("m", context)


def test_a_plug_in_choice_does_not_name_another_creatures_action():
    """HUNT108 F02 step 11: the Aspect choice is the reactor's own, not their mount's Disengage.

    `actor_id` on the trigger is what makes this protective: it is the outer turn's actor, and `attacker_id` is read
    from it (tabletop_service.py:935).  Without it the recent-event lookup finds nothing on the base either, so the test
    passed on the unfixed code as well.  With it, the base returns the warhorse's "Disengage" and this fails.
    """
    spec = {"option_ids": ["Tiger", "Crane"], "minimum_selections": 1, "maximum_selections": 1}
    recent = [{"actor_id": "actor:horse", "source_definition_id": "system:combat.disengage"}]
    prompt = _prompt("actor:me", trigger={"name": "Beast Aspects", "feature_id": "beast", "actor_id": "actor:horse"},
                     extension_choice=spec, recent_events=recent)
    assert prompt["action"] == "", prompt
    assert "Disengage" not in prompt["moment"], prompt["moment"]
    assert prompt["reactor"] == "Lian Feng" and prompt["reaction"] == "Beast Aspects"


def test_a_plug_in_choice_still_names_the_trigger_when_the_trigger_names_its_own_action():
    """The same question, genuinely caused by an attack: the names must still reach the player (item 9)."""
    spec = {"option_ids": ["yes", "no"], "minimum_selections": 1, "maximum_selections": 1}
    prompt = _prompt("actor:me", trigger={"name": "Exploit", "feature_id": "needle", "action_name": "Hidden Strike",
                                          "source_definition_id": "hidden", "action_actor_id": "actor:a",
                                          "affected_id": "actor:horse"}, extension_choice=spec, recent_events=[])
    assert prompt["action"] == "Hidden Strike", prompt
    assert prompt["affected"] == "Warhorse", prompt
    assert "Ally uses Hidden Strike on Warhorse" in prompt["moment"], prompt["moment"]


def test_an_ordinary_reaction_still_names_the_triggering_action_from_recent_events():
    """Checklist 3: the fix is inert for every prompt that is not a plug-in choice."""
    service = TabletopService.__new__(TabletopService)
    service._names = {"m": ({"actor:a": "Ally", "actor:me": "Lian Feng"}, {"system:combat.disengage": "Disengage"})}
    context = {"reactor_id": "actor:me", "checkpoint": "TYPED:DAMAGE_APPLICATION",
               "reaction_source_id": "reaction:typed.stamina_guard", "attacking_actor_id": "actor:a",
               "recent_events": [{"actor_id": "actor:a", "source_definition_id": "system:combat.disengage"}],
               "pending_damage": 5, "damaged_target_id": "actor:me"}
    prompt = service._reaction_prompt_fields("m", context)
    assert prompt["action"] == "Disengage", prompt
