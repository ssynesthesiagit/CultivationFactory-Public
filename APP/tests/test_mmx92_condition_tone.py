"""MMX92: a condition pill is coloured by what it does to the creature carrying it.

Owner 2026-09-30: "debuffs shouldnt be green. green is for buffs not debuffs" - an enemy-applied
'Lethargic' was drawn with a green outline, the same as the bearer's own Meld: Clearsight. The table
worked the colour out from three hand-kept lists of condition names, so any condition missing from
the lists came out green whenever the bearer or an ally applied it. The table now works it out from
the condition's own rule and from which side applied it (combat/condition_tone.py).
"""
import json
import re
import zipfile
import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_auto_docket import _sheet, DARK
from tests.h1_support import ROOT

ME = FACTORY_ACTOR_PREFIX + "mmx92"
FOE = FACTORY_ACTOR_PREFIX + "mmx92-foe"
ALLY = FACTORY_ACTOR_PREFIX + "mmx92-ally"

# combat/ext/tabik_dark.py: Creeping Lethargy, exactly as that ability applies it.
LETHARGIC = "condition:typed.creeping_lethargy"
LETHARGIC_LABEL = ("Lethargic: an Action or a Bonus Action on its turn, not both "
                   "(until it starts a turn outside the Darkness)")


def _match(tmp_path, *, with_ally=False, character=None):
    """A real two-fighter fight, both fighters played by hand so a real table action can be committed."""
    from combat.factory_compiler import compile_character

    me = character if character is not None else _sheet(DARK, ["tianxia.sphere.dark"])
    me["identity"] = {**me["identity"], "name": "Tabik Damu"}
    bundles = [compile_character(me, actor_id=ME), compile_character(me, actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    teams = {ME: "team:factory", FOE: "team:opponents"}
    positions = {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}
    if with_ally:
        bundles.append(compile_character(me, actor_id=ALLY))
        teams[ALLY] = "team:factory"
        positions[ALLY] = {"x": 2, "y": 6}
    match_id = combat._finish_factory_match(
        bundles, list(teams), teams, positions,
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY] if with_ally else [ME], [FOE],
        control_modes={actor: "MANUAL" for actor in teams}, match_seed="MMX92",
        display_name="MMX92 condition pill colour", maximum_rounds=20)["match_id"]
    return combat, table, match_id


def _conditions_of(state, actor_id=ME):
    """{condition id: tone} for one fighter, from a table state or a bare presentation."""
    presentation = state.get("presentation", state)
    actor = next(row for row in presentation["actors"] if row["entity_id"] == actor_id)
    return {row["condition_id"]: row["tone"] for row in actor["conditions"]}


def test_condition_pill_colour_reads_from_the_condition_and_its_applier(tmp_path):
    """A drawback is red and a help is green on the real table projection, whoever applied them.

    Each applier side gets its OWN projection: re-applying the same condition first and then reading
    one row cannot tell the enemy case from the self case apart (review checklist 7).
    """
    combat, table, match_id = _match(tmp_path)
    session = combat._load_session(match_id)
    bearer = session.engine.state.actors[ME]

    # The enemy applied Creeping Lethargy (the owner's screenshot).
    session.engine._apply_condition(bearer, LETHARGIC, "TAL_DARK_CREEPING_LETHARGY", FOE,
                                    expires_on="UNTIL_REMOVED", data={"label": LETHARGIC_LABEL})
    # A help, a tracker, and an enemy-applied core debuff. The enemy's Lethargic above is asserted on
    # its own, so the self-applied Lethargic is projected in a separate fight (below).
    session.engine._apply_condition(bearer, "condition:core.dodge", "DODGE", ME, expires_on="START_OF_SELF_NEXT_TURN")
    session.engine._apply_condition(bearer, "condition:core.concentration", "CONC", ME, expires_on="UNTIL_REMOVED")
    session.engine._apply_condition(bearer, "condition:typed.prone", "PRONE", FOE, expires_on="UNTIL_REMOVED")

    tones = _conditions_of(combat.presentation(match_id, feed=False, session=session))

    assert tones[LETHARGIC] == "harmful", "an enemy's Lethargic is a drawback, so its pill is red"
    assert tones["condition:core.dodge"] == "beneficial", "Dodge helps its bearer, so its pill is green"
    assert tones["condition:core.concentration"] == "neutral", "Concentration is a note for play, so its pill is grey"
    assert tones["condition:typed.prone"] == "harmful", "Prone is a drawback"


def test_a_self_applied_drawback_is_not_a_buff(tmp_path):
    """The regression itself: a drawback the bearer applied to itself was green before the fix.

    Projected on the real table for the self case, and asserted directly for the enemy case, so the
    two applier sides are established independently.
    """
    from combat.condition_tone import tone

    # Self-applied Lethargy on a real projection: this is the owner's own screenshot shape.
    combat, table, match_id = _match(tmp_path)
    session = combat._load_session(match_id)
    bearer = session.engine.state.actors[ME]
    session.engine._apply_condition(bearer, LETHARGIC, "TAL_DARK_CREEPING_LETHARGY", ME,
                                    expires_on="UNTIL_REMOVED", data={"label": LETHARGIC_LABEL})
    self_tone = _conditions_of(combat.presentation(match_id, feed=False, session=session))[LETHARGIC]
    assert self_tone == "harmful", "a drawback the bearer applied to itself is still a drawback"

    for applied_by_the_bearer in (True, False):
        assert tone(LETHARGIC, source_is_ally=applied_by_the_bearer) == "harmful"


def test_a_help_is_green_and_a_creature_s_own_stance_stays_green(tmp_path):
    from combat.condition_tone import tone

    # Stances, forms and Meld are the bearer's own help; Hidden reads as a help because the rules give
    # it Advantage on its own attacks and Disadvantage for attacks against it.
    for condition_id in ("condition:core.dodge", "condition:typed.meld_set", "condition:typed.golden_core_form",
                         "condition:typed.hidden", "condition:typed.invisible", "condition:typed.dug_in"):
        assert tone(condition_id, source_is_ally=True) == "beneficial", condition_id
    # An enemy-applied Mark is a drawback on its bearer.
    assert tone("condition:typed.mark.some_mark.actor:factory.other", source_is_ally=True) == "harmful"


def test_the_tone_survives_a_table_commit_and_reload(tmp_path):
    """The tone is worked out from saved fight state, so it must read the same back off disk."""
    combat, table, match_id = _match(tmp_path)
    # A real action committed through the real table, so the condition is saved the way a player's is.
    while table.state(match_id)["menu"]["actor_id"] != ME:
        from tests.test_lock2_persistence import act
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    state = table.state(match_id)
    dodge = next(candidate for candidate in combat._load_session(match_id).engine.legal_candidates()
                 if candidate.display_name == "Dodge" and candidate.actor_id == ME)
    from tests.iron_fist_support import answering_iron_fist
    answering_iron_fist(lambda answers: table.act(match_id, dodge.candidate_id, state["menu"]["decision_id"],
                                                  state["menu"]["state_version"], state["last_sequence"],
                                                  answers))([])
    before = _conditions_of(table.state(match_id))

    # A fresh service and a fresh table, so the answer comes off disk rather than a cached view.
    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    after = _conditions_of(reloaded.state(match_id))
    assert after.get("condition:core.dodge") == "beneficial", after
    assert before.get("condition:core.dodge") == after.get("condition:core.dodge")


def test_the_client_draws_the_harmful_and_beneficial_classes():
    """The table's own classes: a known drawback is drawn is-harmful and a known help is-beneficial."""
    table_css = (ROOT / "static" / "tabletop" / "tabletop.css").read_text(encoding="utf-8")
    sheet_css = (ROOT / "static" / "tabletop" / "sheet.css").read_text(encoding="utf-8")
    for name in ("harmful", "beneficial", "neutral"):
        assert f".tt-pill.is-condition.is-{name}" in table_css, name
        assert f".cond.{name}" in sheet_css, name
    client = (ROOT / "static" / "tabletop" / "tabletop.js").read_text(encoding="utf-8")
    assert 'is-${conditionTone(row)}' in client, "the side panel pill must take its class from the tone"
    # The colour no longer comes from a hand-kept list of condition names.
    assert "HARMFUL = new Set" not in client and "BUFFS = new Set" not in client


# The 25 names the removed client HARMFUL set protected. Every one must still read red, so no
# de-buffing a name can quietly hand it back to the applier-side default (review finding 2).
REMOVED_HARMFUL_NAMES = (
    "blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated", "paralyzed",
    "petrified", "poisoned", "prone", "restrained", "stunned", "unconscious", "exhaustion",
    "burning", "bleeding", "sickened", "hollowed", "reaction_denied", "no_temp_hp",
    "no_invisible", "no_cp_regain", "no_dash", "slowed", "marked",
)


def test_a_prohibition_the_removed_client_protected_is_still_a_debuff():
    """no_temp_hp / no_invisible: the base client guarded these by name; typed data must keep them red.

    Both are declarations the rules can only state in words, so nothing in the rule says "this costs
    the bearer something" -- without `effect_kind: "harmful"` they fell back to the applier's side and
    an allied prohibition came out green (review finding 2).
    """
    from combat.condition_tone import tone

    for name in ("no_temp_hp", "no_invisible"):
        for applied_by_the_bearer in (True, False):
            assert tone(f"condition:typed.{name}", source_is_ally=applied_by_the_bearer) == "harmful", (
                f"{name} is a prohibition: it takes something away whoever applied it")


def test_no_condition_the_table_used_to_guard_as_a_debuff_is_green_from_its_own_side():
    """The whole removed HARMFUL set, self/ally-applied, which is the side that regressed."""
    from combat.condition_tone import tone

    green = [name for name in REMOVED_HARMFUL_NAMES
             if tone(f"condition:typed.{name}", source_is_ally=True) != "harmful"]
    assert not green, f"these used to be red on the table and are not any more: {green}"


def test_a_scoped_roll_mode_is_read_from_its_mode_member():
    """save_against / check_against carry a mode beside a list of what it applies to.

    Reading the whole dict as if every value were a mode made a real scoped rule speak nothing, so a
    bearer's own Disadvantage fell back to the applier's side (green) and an enemy's Advantage to red
    (review finding 3). This is the exact shape combat/typed_executor.py builds.
    """
    from combat.condition_tone import tone

    disadvantage = {"save_against": {"mode": "DISADVANTAGE", "against": ["frightened"],
                                     "abilities": ["CON"], "next": False}}
    advantage = {"save_against": {"mode": "ADVANTAGE", "against": ["poisoned"],
                                  "abilities": [], "next": False}}
    for applied_by_the_bearer in (True, False):
        assert tone("condition:typed.x", data={"rule": disadvantage},
                    source_is_ally=applied_by_the_bearer) == "harmful", "a bearer losing its own save is red"
        assert tone("condition:typed.x", data={"rule": advantage},
                    source_is_ally=applied_by_the_bearer) == "beneficial", "a bearer gaining it is green"


def test_a_mixed_ability_map_keeps_its_disadvantage():
    """A map that helps on one ability and hurts on another is a trade, not a free buff."""
    from combat.condition_tone import tone

    mixed = {"check_mode": {"CON": "DISADVANTAGE", "STR": "ADVANTAGE"}}
    for applied_by_the_bearer in (True, False):
        assert tone("condition:typed.x", data={"rule": mixed}, source_is_ally=applied_by_the_bearer) == "harmful"


def test_the_hover_card_draws_the_tone_the_table_sends_it():
    """The map token hover card must style every tone the client renders, or a buff pill comes out red.

    board.js builds `is-${row.tone}`; the stylesheet only styled `is-buff`, so Dodge and Hidden were
    drawn in the red base style while the inspector and the sheet showed them green (review finding 1).
    A harmful pill is the red base style itself, so it needs no override; the other two need one.
    """
    css = (ROOT / "static" / "tabletop" / "tabletop.css").read_text(encoding="utf-8")
    board = (ROOT / "static" / "tabletop" / "board.js").read_text(encoding="utf-8")
    assert 'is-${row.tone' in board, "the hover-card pill must take its class from the tone the table sends"
    for name in ("beneficial", "neutral"):
        assert f".tt-card-cond-row.is-{name}" in css, f"the hover card must style is-{name}"
    # The base pill is the red a harmful pill falls back to, and it uses the danger colour.
    base = re.search(r"^\.tt-card-cond \{[^}]*\}", css, re.M).group(0)
    assert "--danger" in base, base


@pytest.mark.parametrize("source", [ME, ALLY, FOE], ids=["self", "ally", "enemy"])
def test_review_regressions_on_independent_table_projections(tmp_path, source):
    """Exercise each applier on its own real table projection, including scoped and mixed modes."""
    combat, table, match_id = _match(tmp_path, with_ally=True)
    session = combat._load_session(match_id)
    bearer = session.engine.state.actors[ME]
    expected = {}

    def apply(name, rule=None, wanted="harmful"):
        condition_id = f"condition:typed.{name}"
        session.engine._apply_condition(
            bearer, condition_id, "MMX92_REGRESSION", source,
            expires_on="UNTIL_REMOVED", data={"rule": rule} if rule else {})
        expected[condition_id] = wanted

    # LIVE Petrified grants Poisoned immunity. Apply poison before that protection
    # so this display fixture actually contains every condition it asserts.
    for name in ("poisoned", *(n for n in REMOVED_HARMFUL_NAMES if n != "poisoned"), "creeping_lethargy"):
        apply(name)
    for field in ("save_against", "check_against"):
        for mode, wanted in (("ADVANTAGE", "beneficial"), ("DISADVANTAGE", "harmful")):
            apply(f"mmx92_{field}_{mode.lower()}",
                  {field: {"mode": mode, "against": ["poisoned"], "abilities": ["CON"], "next": False}},
                  wanted)
    for field in ("save_mode", "check_mode"):
        apply(f"mmx92_{field}_mixed", {field: {"CON": "DISADVANTAGE", "STR": "ADVANTAGE"}})
    actual = _conditions_of(combat.presentation(match_id, feed=False, session=session))
    assert {key: actual.get(key) for key in expected} == expected


# Audit of the removed client BUFFS set. These benefits must not depend on an applier.
REMOVED_BUFF_NAMES = (
    "active_ability", "dodge", "dodging", "guarding", "hidden", "invisible", "afterimage",
    "unburdened", "meld_set", "aura_active", "body_adrenaline_active", "court_of_returning_water",
    "domain_armament", "focused_might_ready", "golden_core_form", "mountain_rending_ready",
    "saint_body_frame_advantage", "cooperative_stealth_available", "destruction_calamity_mantle",
    "core_tempering_expression", "flowing_response_step", "grandstanding_slam_immune",
    "needle_court", "needle_sovereign", "needle_magical",
)


@pytest.mark.parametrize("minimal", [False, True], ids=["enemy-applied", "source-less"])
def test_removed_benefits_stay_green_on_real_projections(tmp_path, minimal):
    combat, table, match_id = _match(tmp_path)
    session = combat._load_session(match_id)
    bearer = session.engine.state.actors[ME]
    ids = [f"condition:typed.{name}" for name in REMOVED_BUFF_NAMES if name != "dodge"]
    ids.append("condition:core.dodge")
    if not minimal:
        for cid in ids:
            session.engine._apply_condition(bearer, cid, "MMX92_BENEFITS", FOE,
                                            expires_on="UNTIL_REMOVED")
        projection = combat.presentation(match_id, feed=False, session=session)
    else:
        raw = session.engine.state.model_dump(mode="json")
        metadata = combat._metadata_readonly(match_id, raw)
        state = combat._history_state_view(raw, metadata)
        actor = next(row for row in state["actors"] if row["entity_id"] == ME)
        actor["conditions"] = {}
        actor["condition_ids"] = ids + [LETHARGIC]
        projection = combat.presenter.project(
            match_id=match_id, metadata=metadata, state=state, catalog=combat.catalog(), mode="LIVE",
        ).model_dump(mode="json", by_alias=True)
        assert _conditions_of(projection)[LETHARGIC] == "harmful"
    assert {cid: _conditions_of(projection).get(cid) for cid in ids} == dict.fromkeys(ids, "beneficial")


def test_enemy_grandstanding_slam_grants_a_green_immunity(tmp_path):
    from types import SimpleNamespace
    from combat.ext.gu_wrestling import _grandstanding_burst

    combat, table, match_id = _match(tmp_path, with_ally=True)
    session = combat._load_session(match_id)
    engine = session.engine
    # Real successful save and real plug-in application: ME is hostile to the slam's source FOE.
    ctx = SimpleNamespace(engine=engine, actor=engine.state.actors[FOE],
                          numbers={"save_dc": -100}, source="TAL_WRESTLING_GRANDSTANDING_SLAM")
    _grandstanding_burst(ctx, engine.state.actors[ALLY])
    cid = "condition:typed.grandstanding_slam_immune"
    immunity = next(row for row in engine.state.actors[ME].conditions.values() if row.condition_id == cid)
    assert immunity.source_actor_id == FOE
    assert _conditions_of(combat.presentation(match_id, feed=False, session=session))[cid] == "beneficial"


def test_exhaustion_fallback_explains_the_automated_penalties():
    from combat.condition_text import all_conditions

    text = all_conditions()["exhaustion"]["reading"]
    assert "each level reduces d20 Tests (attacks, ability checks and saves) by 2" in text
    assert "Speed by 5 feet" in text
    assert "At level 6 the creature dies" in text
    # The fight tracks the penalties and the level 6 defeat, so the player has nothing to resolve.
    # The evidence sentence calls the fight "the table"; that workshop word cannot reach a player,
    # so the shared cleaners keep the statement and name the fight instead (SOL123f1).
    assert "applies the penalties and defeat at level 6" in text, text
    assert "the table" not in text.casefold(), text
    assert "ability scores" not in text and "GM call" not in text


def test_pill_metadata_does_not_change_buff_removal_or_hide_a_drawback():
    from types import SimpleNamespace
    from combat.condition_tone import declared_rule, tone
    from combat.ext.end_effect import helpful
    from combat.condition_text import mechanics

    for name in REMOVED_BUFF_NAMES:
        item = SimpleNamespace(condition_id=f"condition:typed.{name}", data={})
        # LIVE Dodge now carries its printed defensive mechanics as well.
        assert helpful(item, "condition") is (name in {"dodge", "guarding", "hidden", "invisible"})
        assert helpful(item, "condition", defensive_only=True) is (name in {"dodge", "guarding", "hidden", "invisible"})
        rule = declared_rule(name)
        assert mechanics(rule) == mechanics({key: value for key, value in rule.items() if key != "pill_tone"})
    assert tone("condition:typed.meld_set", data={"rule": {"no_actions": True}},
                source_is_ally=True) == "harmful"


def test_enemy_catch_the_eye_successful_save_protection_is_green_after_reload(tmp_path):
    """A real enemy action/save grants Advantage, then the committed table reload projects it green."""
    from tests.h1_support import sheet
    from tests.test_anchor_range_reference import _accept, _advance

    combat, table, match_id = _match(
        tmp_path, character=sheet(["BEAUTY_BASE_CATCH_THE_EYE"], dc=-100))
    _advance(table, match_id, FOE)
    _accept(combat, table, match_id,
            lambda c: c.display_name == "Catch the Eye" and c.target_ids == (ME,))
    session = combat._load_session(match_id)
    saves = [e for e in session.engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == ME]
    assert saves and saves[-1].payload["success"] is True
    cid = "condition:typed.resist_ability"
    protection = next(c for c in session.engine.state.actors[ME].conditions.values() if c.condition_id == cid)
    assert protection.source_actor_id == FOE
    assert protection.data["ability"] == "BEAUTY_BASE_CATCH_THE_EYE"
    assert protection.data["mode"] == "advantage"
    assert protection.data["label"].startswith("Advantage on saves against")
    assert _conditions_of(table.state(match_id))[cid] == "beneficial"
    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert _conditions_of(reloaded.state(match_id))[cid] == "beneficial"


@pytest.mark.parametrize("source", [ME, FOE], ids=["self", "enemy"])
def test_removed_label_classifications_use_rules_on_real_projections(tmp_path, source):
    """Audit stored shapes behind the old /^Advantage/ and /^Disadvantage/ label branches.

    Generic checks, Concentration and scoped saves carry rules; death saves carry a distinct
    death_save_mode. Return the Lesson and Drowsing Root store their mode only in their plug-ins.
    Saint-Body Frame was already covered by the removed BUFFS audit. Labels are deliberately
    replaced here: presentation must follow mechanics/metadata, never English label matching.
    """
    combat, table, match_id = _match(tmp_path)
    session = combat._load_session(match_id)
    bearer = session.engine.state.actors[ME]
    expected = {}
    for field in ("check_mode", "concentration_mode", "save_against", "death_save_mode"):
        for mode, wanted in (("ADVANTAGE", "beneficial"), ("DISADVANTAGE", "harmful")):
            value = ({"WIS": mode} if field == "check_mode" else mode if field == "concentration_mode"
                     else {"mode": mode, "first": True} if field == "death_save_mode"
                     else {"mode": mode, "against": ["charmed"], "abilities": [], "next": True})
            cid = f"condition:typed.mmx92_{field}_{mode.lower()}"
            session.engine._apply_condition(bearer, cid, "MMX92_LABEL_AUDIT", source,
                expires_on="END_OF_HOLDER_NEXT_TURN", data={"rule": {field: value}, "label": "Roll protection or penalty"})
            expected[cid] = wanted
    for name, wanted in (("resist_ability", "beneficial"), ("lesson_save", "harmful"),
                         ("drowsing_root", "harmful"), ("marked", "harmful")):
        cid = f"condition:typed.{name}"
        session.engine._apply_condition(bearer, cid, "MMX92_LABEL_AUDIT", source,
            expires_on="END_OF_HOLDER_NEXT_TURN", data={"label": "Protection or penalty"})
        expected[cid] = wanted
    actual = _conditions_of(combat.presentation(match_id, feed=False, session=session))
    assert {cid: actual.get(cid) for cid in expected} == expected


def test_label_audit_metadata_preserves_removal_and_drawback_priority():
    from types import SimpleNamespace
    from combat.condition_tone import declared_rule, tone
    from combat.condition_text import mechanics
    from combat.ext.end_effect import helpful

    for name in ("resist_ability", "lesson_save", "drowsing_root", "marked"):
        item = SimpleNamespace(condition_id=f"condition:typed.{name}", data={})
        assert not helpful(item, "condition")
        assert not helpful(item, "condition", defensive_only=True)
        rule = declared_rule(name)
        assert mechanics(rule) == mechanics({k: v for k, v in rule.items() if k != "pill_tone"})
    assert tone("condition:typed.resist_ability", data={"rule": {"no_actions": True}},
                source_is_ally=False) == "harmful"
