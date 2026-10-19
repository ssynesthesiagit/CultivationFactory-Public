"""MMX74 (AUDIT6b Part 2 findings 1-3): player-facing text a newcomer can act on.

Finding 1+2: ``static/tabletop/error-text.js`` let the bare ``status === 409`` fallback answer two
codes that are not stale-state refreshes. A saved-fight check is not something waiting resolves, and
a retired fighter is a setup choice rather than a changed turn, so the fallback's advice was
unsatisfiable and described an interface that is not on screen.

The two saved-fight codes are separate cases, not one case. ``COMBAT_COMPATIBILITY_REQUIRED`` is
the recoverable offer -- the tabletop answers it by opening its "Reopen saved fight" dialog, which
compares the recorded fight with the current rules and reopens a copy
(``tabletop.js`` -> ``saved_fight_compat.js``). ``COMBAT_COMPATIBILITY_BLOCKED`` is that very check
or continuation failing, so telling the player the fight "cannot be reopened" makes them abandon a
fight that is still saved. The code and status are taken from the real service here and the advice
is checked where the bug showed: on the API that raises it and on the dialog that toasts it.

Finding 3: the Candlemaker "Last Wick Extinguishes" GM rider used "Restricted" and "Source-CL"
as if they were known categories. Neither is defined on any player-reachable surface, so the line
now explains both in plain words. Restricted is a classification its own source rules carry, not
something a GM judges by how dangerous an effect looks (``rules_text.json`` subpath tables:
"Controlled military, medical, sect, weapon, technical, political, inherited, or hazardous
instruction"; for Spirit Awakening, "Requires a hidden teacher, guarded manual, shrine, sect,
spirit pact, haunted location, initiation, profession, or controlled institution").

The error mapping is checked through the module's real entry point with node, the compatibility
failure through the real service, the dialog through the real frontend modules, and the rider where
the bug showed: on a compiled Candlemaker run through the engine, reading the GM_RIDER event the
fight feed renders.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
ERROR_TEXT = APP / "static" / "tabletop" / "error-text.js"
DIALOG_HARNESS = APP / "tests" / "saved_fight_compat_blocked.test.mjs"

# The exact-code branches sit above the 409 fallback, so a code with its own branch must never
# fall through to it. This is the text the fallback returns; nothing below may equal it.
STALE_REFRESH = "The fight or its choices have changed."


def _player_error(cases: list[dict]) -> list[str]:
    """Call the real ``playerError`` in node and return one message per case."""
    program = (
        f'import {{playerError}} from {json.dumps(str(ERROR_TEXT))};\n'
        f'const cases = {json.dumps(cases)};\n'
        'process.stdout.write(JSON.stringify(cases.map(c => playerError(c))));\n'
    )
    out = subprocess.run(["node", "--input-type=module", "-e", program], check=True,
                         capture_output=True, text=True, cwd=APP)
    return json.loads(out.stdout)


# ============================================================================================ 1+2 error mapping
def test_a_recoverable_saved_fight_is_offered_the_reopen_check():
    """COMBAT_COMPATIBILITY_REQUIRED is the offer the table acts on: it opens the dialog that
    compares the recorded fight with the current rules and reopens a copy. Telling the player the
    fight "cannot be reopened" makes them abandon a fight that can be recovered."""
    message, = _player_error([{"code": "COMBAT_COMPATIBILITY_REQUIRED", "status": 409}])
    assert STALE_REFRESH not in message, "still answers with the 409 fallback"
    assert "cannot be reopened" not in message, "a recoverable fight is called unreopenable"
    assert "reopen a copy" in message, "does not offer the reopen the dialog actually performs"
    assert "original fight is kept exactly as it was" in message, "does not say the saved fight is kept"
    # It is a rules-version offer, which is the one cause the service checks before raising it.
    assert "different version of the rules" in message, "does not say why it will not open directly"


def test_a_failed_saved_fight_check_says_the_check_failed_and_keeps_the_fight():
    """COMBAT_COMPATIBILITY_BLOCKED is raised by the check or the continuation failing -- an
    unreadable save, a changed save, or an inspection token that went stale. It must not claim a
    version mismatch it never observed, and must not tell the player to give up."""
    message, = _player_error([{"code": "COMBAT_COMPATIBILITY_BLOCKED", "status": 409}])
    assert STALE_REFRESH not in message, "still answers with the 409 fallback"
    assert "cannot be reopened" not in message, "a failed check is called a permanently lost fight"
    assert "did not finish" in message, "does not say the check or continuation is what failed"
    assert "different version of the rules" not in message, \
        "invents a version mismatch the service never reported"
    assert "original fight is kept exactly as it was" in message, "does not say the saved fight is kept"
    assert "Try opening it again" in message and "ask the GM for help" in message, \
        "gives the player no way forward"


def test_the_two_saved_fight_codes_are_not_answered_with_the_same_words():
    """They are opposite situations. One message for both is the defect this lane found."""
    required, blocked = _player_error([{"code": "COMBAT_COMPATIBILITY_REQUIRED", "status": 409},
                                       {"code": "COMBAT_COMPATIBILITY_BLOCKED", "status": 409}])
    assert required != blocked, "a recoverable offer and a failed check share one message"


# ----------------------------------------------------------------- the code the service really raises
def _end_turn(session):
    from combat.gate2_runtime_models import ActionIntent
    candidate = next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN")
    session.submit_intent(ActionIntent(intent_id=f"mmx74:{session.engine.state.state_version}",
                                       decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=candidate.actor_id,
                                       target_ids=candidate.target_ids, destination=candidate.destination,
                                       option_ids=candidate.option_ids),
                         primary_decision_record=None, reaction_provider=None)


@pytest.fixture
def prior_engine_save(tmp_path):
    """A real fight saved under a changed source binding: the one case the table offers to reopen."""
    from combat.gate4_persistence import Gate4Persistence
    from combat.saved_fight_compat import record_engine_version

    source = tmp_path / "prior-source"
    source.mkdir()
    for path in APP.iterdir():
        if path.name != "combat":
            (source / path.name).symlink_to(path, target_is_directory=path.is_dir())
    (source / "combat").mkdir()
    for path in (APP / "combat").iterdir():
        if path.name != "gate2_engine.py":
            (source / "combat" / path.name).symlink_to(path, target_is_directory=path.is_dir())
    (source / "combat/gate2_engine.py").write_bytes(
        (APP / "combat" / "gate2_engine.py").read_bytes() + b"\n# prior engine revision\n")
    data = tmp_path / "data"
    old = Gate4Persistence(source, data).create_match(match_seed="mmx74-compat", maximum_rounds=10)
    record_engine_version(old.store)
    _end_turn(old)
    old.mechanical.explicit_snapshot()
    return old, Gate4Persistence(APP, data)


def test_a_blocked_continuation_reaches_the_mapper_with_recovery_advice(prior_engine_save):
    """The token the dialog holds stops matching once the save or the rules change, and the service
    answers COMBAT_COMPATIBILITY_BLOCKED. That is the code a player meets at the moment they chose
    to continue, so the advice is checked from the real API through the real mapper -- a
    mapper-only assertion cannot show which code the player is actually given."""
    from combat.gate5_service import CombatService, CombatServiceError
    from combat.saved_fight_compat import inventory

    old, current = prior_engine_save
    service = CombatService(APP, current.userdata_root)
    report = service.saved_fight_compatibility(old.match_id)
    assert report["source_engine"] != report["current_engine"], "the fixture is not a prior-engine save"
    before = inventory(old.store.match_dir)

    with pytest.raises(CombatServiceError) as refused:
        service.continue_saved_fight(old.match_id, token="a-token-from-an-older-inspection",
                                     mode=report["mode"])
    assert refused.value.diagnostic.code == "COMBAT_COMPATIBILITY_BLOCKED"
    assert refused.value.status_code == 409
    # The dialog and the toast are the player's only route back, and the backend promises the
    # original survives: a player told the fight is gone must not be right.
    assert "inspect the fight again before continuing" in str(refused.value)
    assert inventory(old.store.match_dir) == before, "a refused continuation touched the original"
    assert not (Path(current.userdata_root) / "compatibility_backups").exists()

    message, = _player_error([{"code": refused.value.diagnostic.code,
                               "status": refused.value.status_code}])
    assert "did not finish" in message, "the player is not told the check is what failed"
    assert "original fight is kept exactly as it was" in message, "the player is not told it is kept"
    assert "cannot be reopened" not in message, "a recoverable fight is called unreopenable"


def test_a_blocked_continuation_shows_that_advice_in_the_dialog(tmp_path):
    """The table toasts whatever the dialog rejects with, so the dialog is where a player meets the
    message. Driven through the real modules with a stubbed fetch, not a re-implementation."""
    out = subprocess.run(["node", "--test", str(DIALOG_HARNESS)], capture_output=True, text=True, cwd=APP)
    assert out.returncode == 0, f"the dialog harness failed:\n{out.stdout}\n{out.stderr}"


def test_retired_fighter_is_not_described_as_a_stale_state_refresh():
    """COMBAT_FIGHTER_RETIRED is raised at setup time, so the fallback's "choose from the current
    turn's buttons" describes a screen that does not exist when it fires."""
    message, = _player_error([{"code": "COMBAT_FIGHTER_RETIRED", "status": 409}])
    assert STALE_REFRESH not in message, "a retired fighter is still answered as a stale-state refresh"
    assert "Wait for the table to refresh" not in message, "still tells the player to wait for a refresh"
    assert "retired" in message.lower()
    assert "Pick a different character" in message, "does not tell the player to choose another fighter"
    # The backend's message promises saved fights survive retirement; the toast must not imply otherwise.
    assert "still be opened" in message, "does not say the fights already saved with it survive"


def test_a_genuine_409_still_gets_the_stale_state_refresh_advice():
    """The fix adds two branches; it must not take over the 409 fallback it was meant to sit above."""
    for code in ("COMBAT_STATE_VERSION_MISMATCH", "COMBAT_DECISION_STALE", "COMBAT_CONFLICT"):
        message, = _player_error([{"code": code, "status": 409}])
        assert STALE_REFRESH in message, f"{code} lost its 409 advice"
    # A bare 409 with no code at all must still reach the fallback too.
    message, = _player_error([{"code": "", "status": 409}])
    assert STALE_REFRESH in message, "a bare 409 lost the fallback advice"


def test_the_new_branches_do_not_shadow_the_older_exact_code_branches():
    """Both new branches are regexes; ordering against the existing exact-code branches matters."""
    still_mapped, = _player_error([{"code": "COMBAT_MATCH_NOT_FOUND", "status": 404}])
    assert "no longer available" in still_mapped
    not_ready, = _player_error([{"code": "COMBAT_CONTENT_NOT_READY", "status": 409}])
    assert "still being saved" in not_ready
    # A retired fighter is a 409, so the compatibility branch above it must not capture it.
    retired, = _player_error([{"code": "COMBAT_FIGHTER_RETIRED", "status": 409}])
    assert "cannot be reopened" not in retired
    assert "did not finish" not in retired, "a setup-time retirement is answered as a failed check"


def test_the_new_branches_contain_no_jargon_or_internal_ids():
    """Change standard 13: a player who knows only basic D&D must be able to act on this."""
    messages = _player_error([{"code": "COMBAT_COMPATIBILITY_REQUIRED", "status": 409},
                              {"code": "COMBAT_COMPATIBILITY_BLOCKED", "status": 409},
                              {"code": "COMBAT_FIGHTER_RETIRED", "status": 409}])
    for message in messages:
        for term in ("COMBAT_", "409", "engine version", "recommended_action", "gate5"):
            assert term not in message, f"{term!r} is not plain words: {message}"
        for term in ("compatibility", "COMPATIBILITY", "token", "integrity", "schema"):
            assert term not in message.lower(), f"{term!r} is system jargon: {message}"


# ============================================================================================ 3 Candlemaker GM rider
# Mirrors the Candlemaker harness in tests/test_riders_c8.py: a real Spirit Awakening character
# owning the Candlemaker features, run through the engine. dc=40 makes the target's Wisdom save
# fail, which is the branch that emits this rider.
CM = "tianxia.tradition.spirit.candlemaker.feature."
CM_ALL = [CM + k for k in ("wick_of_the_self", "candle_against_the_dark", "funeral_light",
                           "last_flame", "thousand_year_lantern")]
ME = "actor:factory.mmx74"
FOE = "an_eui_early_book1_cl5"  # the Gate 2 sparring partner, as tests/test_riders_c8.py uses


def _candlemaker_rider():
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_engine import Gate4ControllerEngine

    authority = json.loads((APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    mods = {"STR": 1, "DEX": 2, "CON": 2, "INT": 1, "WIS": 4, "CHA": 1}

    def sheet(ids):
        return {
            "identity": {"proficiency_bonus": 6, "cultivation_level": 18, "path": "Spirit Awakening", "key_ability": "WIS"},
            "ability_scores_and_statistics": {
                "abilities": [{"ability": a, "score": 10 + 2 * m, "modifier": m} for a, m in mods.items()],
                "primary_resource": {"name": "Resonance", "maximum": 60}, "armor_class": {"base_value": 14},
                "hit_points": {"maximum": 90}, "speed": {"walking_ft": 30}, "technique_save_dc": 40,
                "technique_attack_bonus": 9},
            "path_and_subpath": {"path_feature_record_ids": list(ids)},
        }

    engine = Gate4ControllerEngine(
        APP, match_seed="MMX74",
        typed_bundles=(compile_character(sheet(CM_ALL), actor_id=ME, typed_authority=authority),),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}})

    def turn():
        engine.state.current_slot_index = engine.state.initiative_order.index(ME)
        engine.state.current_actor_id = ME
        engine._system_start_turn()
        actor = engine.state.actors[ME]
        actor.action_available = actor.bonus_action_available = actor.reaction_available = True

    def use(name, target=None):
        matches = [c for c in engine.legal_candidates()
                   if c.display_name == name and (target is None or target in (c.target_ids or ()))]
        assert matches, f"{name!r} is not legal; legal: {sorted(c.display_name for c in engine.legal_candidates())}"
        candidate = matches[0]
        before = len(engine.events)
        engine.execute_intent(ActionIntent(
            intent_id=f"mmx74-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
            state_version=candidate.state_version, actor_id=ME,
            target_ids=(target,) if target else (candidate.target_ids or ()),
            destination=candidate.destination))
        return engine.events[before:]

    turn()
    use("Thousand-Year Lantern")
    for _ in range(3):
        turn()
        use("Wick of the Self", FOE)
    foe = engine.state.actors[FOE]
    foe.maximum_hp = foe.current_hp = 500  # it survives the 10d10 so the rider branch is reached
    events = use("Last Wick Extinguishes (Fire)", FOE)
    return [(getattr(e, "payload", None) or {}).get("rider", "")
            for e in events if e.event_type == "GM_RIDER"]


@pytest.fixture(scope="module")
def rider_text():
    riders = [text for text in _candlemaker_rider() if text]
    assert riders, "the failed-save branch emitted no GM_RIDER for Last Wick Extinguishes"
    return "\n".join(riders)


def test_candlemaker_rider_defines_source_cl_in_plain_words(rider_text):
    """Source CL is the cultivation level of the ability that created the effect."""
    assert "Source CL" in rider_text, "the rider no longer names Source CL at all"
    assert "the cultivation level of the ability that created the effect" in rider_text, \
        "Source CL is used without saying what it is"


def test_candlemaker_rider_says_restricted_comes_from_the_effect_own_rules(rider_text):
    """The printed rule chooses a tier the ability's own rules carry, so the GM must look it up
    rather than judge the effect. A danger-based gloss lets a GM suppress an ordinary dangerous
    effect, or end a Restricted one that looks harmless."""
    assert "Restricted" in rider_text, "the rider no longer names the Restricted tier"
    assert "its own printed rules list as Restricted" in rider_text, \
        "Restricted is not tied to the classification the source rules already made"
    assert "not by how dangerous it looks" in rider_text, \
        "the rider invites a danger-based judgment the rules do not use"
    assert "a controlled or dangerous effect rather than an ordinary one" not in rider_text, \
        "the old danger-based gloss is still there"


def test_candlemaker_rider_explains_restricted_as_controlled_guarded_access(rider_text):
    """The subpath tables define Restricted Scripture/Lineage by who may learn the teaching --
    "Controlled military, medical, sect, weapon, technical, political, inherited, or hazardous
    instruction" and, for Spirit Awakening, "Requires a hidden teacher, guarded manual, shrine,
    sect, spirit pact, haunted location, initiation, profession, or controlled institution"."""
    assert "controlled or guarded" in rider_text, "Restricted is not explained as controlled access"
    for holder in ("sect", "guild", "school", "shrine", "lineage"):
        assert holder in rider_text, f"the controlled-access classification never mentions {holder!r}"
    assert "limits who may learn it" in rider_text, "Restricted is not explained as restricted access"
    assert "rather than open to anyone" in rider_text, "Restricted is not contrasted with open teaching"


def test_candlemaker_rider_keeps_the_printed_outcomes_it_is_choosing_between(rider_text):
    """The reword explains the terms; it must not drop or alter what the GM applies."""
    assert "ends" in rider_text, "the lower-Source-CL outcome is gone"
    assert "suppressed for the scene" in rider_text, "the suppressed outcome is gone"
    assert "two successful end-of-turn saves restore it" in rider_text, "the restore rule is gone"
    assert "one printed benefit" in rider_text, "the higher-Source-CL outcome is gone"
    assert "Cultivation Check" in rider_text, "the Cultivation Check is gone"
    assert "the GM applies it" in rider_text, "the rider no longer says the GM applies it"


def test_candlemaker_rider_carries_no_bare_source_cl_hyphen_jargon(rider_text):
    """The old line wrote "lower-Source-CL"/"equal-Source-CL" as compound jargon."""
    for fragment in ("lower-Source-CL", "equal-Source-CL", "higher-Source-CL"):
        assert fragment not in rider_text, f"{fragment} is the old undefined compound form"
