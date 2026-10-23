"""A player prompt must never advertise a choice it cannot offer (HUNT99 #3).

'Cultivated Response' is a save_rescue reaction whose printed text opens with a build-time
"Choose one Defensive Discipline" (three sibling ### option sub-headings; "At CL15, learn a
second").  The table resolves that selection at compile time (combat/typed_reactions.py picks the
single weakest save), so the in-combat prompt is a Use/Pass reaction that offers NO buttons -- yet
combat/decision_text.py used to open its summary with the unanswerable selection, so the player saw
"Choose one Defensive Discipline" with nothing to click.

Two general guarantees are asserted here, neither keyed on an ability id:
  1. A choice-less prompt's summary omits an explicitly level-based advancement selection block
     (decision_text._build_time_selection); the full owner wording is still published under "rules".
  2. The compiled reaction really is choice-less (a Use/Pass, not a multi-option pick), so the
     printed disciplines are correctly absent from the decision the player is asked to make.

MMX98f1 (review fixes) adds two more general guarantees, both service level:
  3. The block ends at the end of the option RUN, not at the end of the text.  'Tempered Response'
     prints its procedure straight after its last option with no heading of its own, so a block that
     only stopped at a heading of another depth deleted the operative procedure and every limit.
  4. A choice-less summary is normalized with the same paying pool as the expanded rules, so a
     CP-bearing reaction never re-introduces a bare "CP" the cost line just explained.

SOLFMMX98r2 keeps target and activation-mode procedures, even with introductory prose:
missing buttons and sibling headings alone are not advancement evidence.
"""
import re
import pytest

from tests.h48_table_support import FOE, OWNER, fixture

CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
# Two CP-bearing reactions that compile choice-less, one paying from a named pool and one with no
# compiled pool at all, so both branches of the paying-pool wording are covered.
GRAVE_TAX = "TAL_DEATH_GRAVE_TAX"
INTERRUPTING_POINT = "tianxia.talent.pressure_points.interrupting_point"
SELECTION = "Choose one Defensive Discipline"


def _save_rescue_prompt(tmp_path, feature, ability, seed):
    """The real table prompt for a save_rescue Use/Pass, through the production builder
    (TabletopService._reaction_prompt -> build_decision_text) on a real match."""
    combat, table, match_id, _send, _commit = fixture(tmp_path, [feature], seed=seed)
    engine = combat._load_session(match_id).engine
    rows = [row for row in engine.typed_reaction_rows.get(OWNER, []) if row.get("feature_id") == feature]
    assert rows, f"{feature} did not compile into a save_rescue reaction"
    context = {
        "checkpoint": "TYPED:SAVE_RESULT_BEFORE_DECLARED@1",
        "reactor_id": OWNER,
        "reaction_source_id": f"reaction:typed.{feature}",
        "choice_trigger": {"ability": ability, "dc": 15, "total": 8},
    }
    return table._reaction_prompt(match_id, context, engine=engine), rows[0]


def _cultivated_prompt(tmp_path):
    return _save_rescue_prompt(tmp_path, CULTIVATED, "CHA", "MMX98-CR")


# --- 1. the visible bug, at table/service level ------------------------------------------------

def test_choice_less_prompt_never_opens_with_an_unanswerable_selection(tmp_path):
    prompt, _row = _cultivated_prompt(tmp_path)
    choice = prompt.get("choice") or {}
    # The prompt really is choice-less: a Use/Pass reaction, not a multi-option pick.
    assert not choice.get("options")
    summary = str(prompt.get("summary") or "")
    assert SELECTION not in summary, (
        "a choice-less prompt advertised a printed selection the player cannot pick from:\n" + summary)
    assert not re.match(r"^\s*Choose\b", summary, re.I), (
        "summary opens with an unanswerable 'Choose ...' instruction:\n" + summary)
    # It now describes the actual in-combat procedure instead.
    assert "Proficiency Bonus" in summary, summary


def test_owner_wording_is_preserved_under_rules(tmp_path):
    """Only the at-a-glance summary drops the selection; the printed rules are untouched."""
    prompt, _row = _cultivated_prompt(tmp_path)
    rules = str(prompt.get("rules") or "")
    assert SELECTION in rules
    assert "Reflexive" not in prompt.get("summary", "")  # summary is clean
    for printed in ("Your discipline applies to Dexterity saving throws.",
                    "Your discipline applies to Intelligence saving throws.",
                    "Your discipline applies to Charisma saving throws."):
        assert printed in rules, printed


def test_choose_one_reaction_is_collapsed_to_one_save_at_compile(tmp_path):
    """choose_one compiles to ONE save, so the prompt must be a Use/Pass, not a choice, and the
    printed options must never leak as the decision.

    AUTO1 2026-10-04: which of the printed disciplines that one save is comes from the owner's
    recorded pick when there is one (combat/ext/defensive_disciplines.py); with nothing recorded
    the compiler's weakest save stands, so this fixture still compiles exactly one ability.
    """
    _prompt, row = _cultivated_prompt(tmp_path)
    assert row.get("block") == "save_rescue"
    assert len(row.get("abilities") or []) == 1, row.get("abilities")


# --- 3. the structure-only helper ------------------------------------------------------------

def test_build_time_selection_lifts_only_a_sibling_heading_block():
    from combat.decision_text import _build_time_selection
    text = ("Choose one Discipline.\n\n"
            "### Alpha\nApplies to Dexterity saving throws.\n\n"
            "### Beta\nApplies to Intelligence saving throws.\n\n"
            "#### Response Procedure\n\nReaction\nAdd your Proficiency Bonus.\n"
            "At CL15, learn a second Discipline.\n")
    out = _build_time_selection(text)
    assert "Choose one Discipline" not in out
    assert "Applies to Dexterity" not in out
    assert "Applies to Intelligence" not in out
    assert "Response Procedure" in out and "Proficiency Bonus" in out


def test_build_time_selection_leaves_prose_and_inline_choices_alone():
    from combat.decision_text import _build_time_selection
    prose = "You may Choose one of the following: Attack, or Move. Move: shift 5 feet."
    assert _build_time_selection(prose) == prose
    no_block = "Reaction\nTrigger: You fail a save.\nAdd your Proficiency Bonus."
    assert _build_time_selection(no_block) == no_block
    assert _build_time_selection("") == ""


# --- 4. MMX98f1: the block ends at the end of the option run, not at the end of the text --------

def test_tempered_response_keeps_the_procedure_behind_its_options(tmp_path):
    """Tempered Response prints its procedure straight after its last option, with no heading of
    its own.  Lifting the selection must stop there, or the summary loses what the ability does."""
    prompt, row = _save_rescue_prompt(tmp_path, TEMPERED, "STR", "MMX98F1-TR")
    assert not (prompt.get("choice") or {}).get("options"), "expected a choice-less Use/Pass prompt"
    assert len(row.get("abilities") or []) == 1, row.get("abilities")  # choose_one resolves the discipline
    summary = str(prompt.get("summary") or "")
    assert SELECTION not in summary, summary
    # The operative procedure survives: the player can still tell what the ability does.
    assert "spend 1 Stamina to add your Proficiency Bonus" in summary, (
        "Tempered Response lost its operative procedure:\n" + summary)
    assert "saving-throw proficiencies from their Path" in summary, summary
    # The build-time disciplines stay owner wording only.  The option bodies are prose, so they are
    # the ones that can leak into the summary; the ### names are headings and never reach the player.
    rules = str(prompt.get("rules") or "")
    assert SELECTION in rules
    for printed in ("Your chosen saving throw is Strength.",
                    "Your chosen saving throw is Dexterity.",
                    "Your chosen saving throw is Constitution."):
        assert printed in rules, printed
        assert printed not in summary, printed
    # The usage limits and the advancement line are part of what the ability does, and stay.
    assert "You may use it once per round." in rules
    assert "Indomitable Body" in rules


def test_build_time_selection_stops_at_the_paragraph_after_the_last_option():
    """The delimiter-free layout, as printed: no different-depth heading separates the options
    from the procedure, so the block must end at the blank line before that paragraph."""
    from combat.decision_text import _build_time_selection
    text = ("Choose one Defensive Discipline.\n\n"
            "### Rooted Frame\n\nYour chosen saving throw is Strength.\n\n"
            "### Flowing Frame\n\nYour chosen saving throw is Dexterity.\n\n"
            "### Enduring Frame\n\nYour chosen saving throw is Constitution.\n\n"
            "When you fail a saving throw using your chosen ability, you may spend 1 Stamina to add "
            "your Proficiency Bonus to the result.\n\n"
            "- You may use it once per round.\n\n"
            "You gain a second Defensive Discipline through Indomitable Body at CL13.\n")
    out = _build_time_selection(text)
    assert "Choose one Defensive Discipline" not in out
    for lifted in ("Rooted Frame", "Flowing Frame", "Enduring Frame",
                   "Your chosen saving throw is Strength.", "Your chosen saving throw is Dexterity.",
                   "Your chosen saving throw is Constitution."):
        assert lifted not in out, lifted
    for kept in ("spend 1 Stamina to add your Proficiency Bonus",
                 "You may use it once per round.",
                 "You gain a second Defensive Discipline through Indomitable Body at CL13."):
        assert kept in out, kept


# --- 5. MMX98f1: a choice-less summary keeps the paying-pool wording -----------------------------

def test_choice_less_prompt_keeps_the_paying_pool_wording(tmp_path):
    """A choice-less summary is normalized exactly like the expanded rules, so a CP-bearing
    reaction never re-introduces a bare "CP" that the cost line and the rules just explained."""
    from combat.tabletop_service import _rules_texts
    printed = _rules_texts()
    combat, table, match_id, _send, _commit = fixture(tmp_path, [GRAVE_TAX, INTERRUPTING_POINT],
                                                      seed="MMX98F1-CP")
    engine = combat._load_session(match_id).engine
    for feature in (GRAVE_TAX, INTERRUPTING_POINT):
        rows = [row for row in engine.typed_reaction_rows.get(OWNER, []) if row.get("feature_id") == feature]
        assert rows, f"{feature} did not compile into a reaction"
        context = {"checkpoint": "TYPED:REACTION_WINDOW_OPENED", "reactor_id": OWNER,
                   "reaction_source_id": f"reaction:typed.{feature}",
                   "choice_trigger": {"action_actor_id": FOE}}
        prompt = table._reaction_prompt(match_id, context, engine=engine)
        assert not (prompt.get("choice") or {}).get("options"), f"{feature} is no longer choice-less"
        summary = str(prompt.get("summary") or "")
        rules = str(prompt.get("rules") or "")
        # The owner's wording really does say CP, so this is the regression's subject.
        assert re.search(r"\bCP\b", printed[feature]), feature
        assert not re.search(r"\bCP\b", rules), f"{feature}: rules lost the paying-pool wording"
        assert not re.search(r"\bCP\b", summary), (
            f"{feature}: the summary re-introduced a bare 'CP' the cost line explains:\n" + summary)


def test_choice_less_summary_and_rules_agree_on_the_paying_pool(tmp_path):
    """The named pool and the no-pool fallback both reach the summary, and match the rules."""
    from combat.tabletop_service import _rules_texts
    printed = _rules_texts()
    combat, table, match_id, _send, _commit = fixture(tmp_path, [GRAVE_TAX, INTERRUPTING_POINT],
                                                      seed="MMX98F1-CP2")
    engine = combat._load_session(match_id).engine

    def summary_of(feature):
        context = {"checkpoint": "TYPED:REACTION_WINDOW_OPENED", "reactor_id": OWNER,
                   "reaction_source_id": f"reaction:typed.{feature}",
                   "choice_trigger": {"action_actor_id": FOE}}
        prompt = table._reaction_prompt(match_id, context, engine=engine)
        return str(prompt.get("summary") or ""), str(prompt.get("rules") or "")

    # Grave Tax pays from a named pool: the printed "regain CP" reads as the pool that pays.
    summary, rules = summary_of(GRAVE_TAX)
    assert "regain Qi equal to your Proficiency Bonus" in summary, summary
    assert "regain Qi equal to your Proficiency Bonus" in rules, rules
    # Interrupting Point has no compiled pool: the summary must still explain what CP is.
    summary, rules = summary_of(INTERRUPTING_POINT)
    assert "cultivation points (your Path resource)" in summary, summary
    assert "cultivation points (your Path resource)" in rules, rules
    # Both are genuinely the printed CP sentences, so the assertions above are not vacuous.
    assert "regain CP equal to your Proficiency Bonus" in printed[GRAVE_TAX]
    assert "any CP or resource spent are not lost" in printed[INTERRUPTING_POINT]


# --- 6. MMX98f1: never trade a description for a summary of nothing ----------------------------

def test_options_that_run_to_the_end_of_the_text_keep_the_owner_wording():
    """Some texts print the options with no procedure after them, so the options ARE the ability.
    Lifting the selection there would leave a summary of nothing, so the owner's wording is kept.
    (Function level: no fixture reaches this -- the ability's target pick is a targeting step, not a
    choice.options list -- but this is the production builder, called on its engine-free path.)"""
    from combat.decision_text import build_decision_text
    text = ("#### Blood Thread\n"
            "Action Type: Action\n"
            "Range: 60 feet\n"
            "Cost: None\n"
            "Choose one creature with meaningful circulation.\n"
            "##### Willing Creature\n"
            "Apply Blood Thread automatically.\n"
            "The Thread lasts for 1 minute.\n"
            "##### Unwilling Creature\n"
            "Make a ranged Cultivation Attack.\n"
            "Hit: Deal Piercing or Necrotic damage equal to the listed dice.\n")
    context = {"checkpoint": "TYPED:TECHNIQUE_DECLARED", "reactor_id": OWNER,
               "reaction_source_id": "reaction:typed.BLOOD_BASE_BLOOD_THREAD"}
    prompt = {"reaction": "Blood Thread", "reactor": OWNER,
              "moment": "Blood Thread is about to be used."}
    result = build_decision_text(None, context, prompt, {}, {}, {"BLOOD_BASE_BLOOD_THREAD": text})
    summary = str(result.get("summary") or "")
    # Something the player can act on, not "No printed rule summary is available".
    assert "No printed rule summary" not in summary, summary
    assert "Choose one creature with meaningful circulation." in summary, summary
    assert "Apply Blood Thread automatically." in summary, summary
    assert "The Thread lasts for 1 minute." in summary, summary


@pytest.mark.parametrize("feature,target,procedure", [
    ("TAL_BRUTE_THE_HAND_THAT_REPOSITIONED_HEAVEN",
     "Choose one creature, unattended object, temporary Barrier, or ordinary structure section.",
     "Make one Brutal Shove with Advantage."),
    ("TAL_SWORD_SEVERING_FATE",
     "Choose one creature, object, temporary Barrier, or ordinary ongoing supernatural effect.",
     "Make one Sword attack or ranged Cultivation Attack with:"),
    ("tianxia.talent.music.court_of_resonant_measure",
     "Choose one mode when activating the Domain.",
     "Allies inside who can hear or spiritually perceive you gain:"),
])
def test_quote_prefixed_target_and_mode_rules_keep_operative_summary(tmp_path, feature, target, procedure):
    """Exercise the production builder on a persisted table's engine with actual owner text."""
    from combat.decision_text import build_decision_text, _build_time_selection
    from combat.tabletop_service import _rules_texts
    text = _rules_texts()[feature]
    assert text.splitlines()[1].startswith("“"), "regression requires surviving introductory prose"
    assert _build_time_selection(text) == text
    combat, _table, match_id, _send, _commit = fixture(tmp_path, [], seed="SOLFMMX98R2")
    engine = combat._load_session(match_id).engine
    context = {"checkpoint": "TYPED:TECHNIQUE_DECLARED", "reactor_id": OWNER,
               "reaction_source_id": f"reaction:typed.{feature}"}
    prompt = {"reaction": "Reviewed ability", "reactor": OWNER, "moment": "Activation"}
    result = build_decision_text(engine, context, prompt, {}, {}, {feature: text})
    assert not (result.get("choice") or {}).get("options")
    assert target in result["summary"]
    assert procedure in result["summary"]
    assert target in result["rules"] and procedure in result["rules"]


def test_heading_selection_without_advancement_evidence_is_preserved():
    from combat.decision_text import _build_time_selection
    text = ("An introductory quotation.\nChoose one Discipline.\n"
            "### Alpha\nMake an attack.\n### Beta\nMove 10 feet.\n"
            "#### Procedure\nSpend your action.\n")
    assert _build_time_selection(text) == text


def test_advancement_options_with_only_introductory_prose_are_preserved():
    from combat.decision_text import _build_time_selection
    text = ("An introductory quotation.\nAt CL15, learn a second Discipline.\n"
            "Choose one Discipline.\n### Alpha\nMake an attack.\n"
            "### Beta\nMove 10 feet.\n")
    assert _build_time_selection(text) == text
