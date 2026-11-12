"""MMX83 - save/reload equivalence: a fight cut in half is the same game as one played straight through.

WHAT THIS PROVES
    For a seeded AI-vs-AI fight, playing it straight to the end (arm A) and playing
    it to a cut point, committing, throwing the whole engine away and reloading the
    fight from storage (arm B) must produce ONE game, not two:
      * the engine's legal choice list - every candidate id and the label the engine
        reports for it - is identical at every step of both arms, and
      * the event log, the dice rolls and the final fight state are byte-identical.

    The cut is real: at the cut point every in-memory object (engine, controller,
    policies) is dropped and the fight is reopened through ``CombatService._load_session``,
    the same call ``TabletopService`` makes for every table read after a restart. The
    reloaded fight is then played to its end with no memory of the first run.

HOW TO RUN
    pytest -p no:cacheprovider --basetemp=/var/tmp/mmx83-pytest -q tests/test_save_reload_equivalence.py
    The whole grid takes a few minutes. To run less, set MMX83_SAVE_RELOAD:

        MMX83_SAVE_RELOAD=fast    arm A for one stock control and one Factory fight,
                                  plus those two fights' cuts
        MMX83_SAVE_RELOAD=stock   the six stock controls only - no Factory character is
                                  installed and no Factory fight is built
        (unset)                   every fight

    The mode is applied where the work is: it chooses the parametrised cuts, the baseline
    fights the shared fixture plays, and which per-fight guards run, so a reduced run
    really does less work. ``test_a_reduced_run_builds_only_the_selected_fights`` holds the
    module to that. ``-k`` still deselects tests but cannot change which baselines get
    built. Either way the two comparison guards at the bottom of the module play a stock
    fight of their own, since a control they do not play would prove nothing. There is no
    marker registry in this repository, so the module follows the existing opt-in
    convention used by tests/test_log1_saved_ai_replay.py (an environment variable) rather
    than registering a marker in the shared tests/conftest.py.

THE FIGHTS
    Six stock controls on the unmodified gate4 roster - the three GATE4 seeds the
    lock rounds already capture (GATE4-TEST / GATE4-AN-1 / GATE4-LEE) plus three more
    seeds (LOCK5-A / LOCK5-B / LOCK5-C) - and two Factory-character fights, one
    that summons servants and one that lays areas on the map.

CUT POINTS
    After decision 5, after decision 20, and at the midpoint of the fight, so the
    cut lands early, mid-fight and late.

WHY BOTH ARMS ARE COMPARED AS RE-READ FROM STORAGE
    The journal's COMMIT records are the fight's real history, so the comparison
    reads the finished fight back out of storage on both arms and compares those
    bytes. Comparing a *live* engine's event objects against a *reloaded* engine's
    would manufacture a false divergence: ``enrich_committed_events`` stamps
    ``gate3_condition_after`` / ``gate3_runtime_control_after`` onto the journal copy
    as it is written, so only reloaded events carry them. ``match_id`` is normalised
    because independent saves use different storage identifiers.

WHAT THIS DOES NOT CLAIM
    "The same choices" means the engine's legal choice list: the same candidate ids and
    the same candidate labels at every step. It does not mean the table's rendered menu.
    ``TabletopService._menu`` builds that menu from each candidate's metadata plus the
    name book - action labels, target names, option labels, destinations and areas - and a
    presentation or cache regression there would not show up here. Comparing the rendered
    menu is a separate service-level property (it needs installed characters, so the stock
    roster cannot produce one) and is not claimed by this module. Manual / "ask me"
    decisions and process-global state across a real restart are out of scope too: these
    are AI-vs-AI fights inside one process.
"""

import json
import os
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.h1_support import ROOT, sheet

# ---------------------------------------------------------------- the fights

#: Stock controls: three seeds the lock rounds already capture, three more.
STOCK_SEEDS = ("LOCK5-A", "LOCK5-B", "LOCK5-C", "GATE4-TEST", "GATE4-AN-1", "GATE4-LEE")

#: A Factory character whose talents bring servants onto the battlefield.
SUMMON_MIDS = ("tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation",
               "tianxia.talent.talismans.talisman_spirit")
#: A Factory character whose talents leave burning areas on the map.
ZONE_MIDS = ("SMOKE_BASE_SMOKE_VEIL", "FIRE_BASE_CONFLAGRATION")

STOCK_ROUNDS = 3
FACTORY_ROUNDS = 6
#: Enough decisions to reach the duration limit without an unbounded fight.
STEP_CEILING = 200


def _fight_id(name):
    return FACTORY_ACTOR_PREFIX + "mmx83-" + name


def _install_factory(root, name, mids, primary):
    """Install two portable Factory characters and return their actor ids and bundles."""
    ids = [_fight_id("left"), _fight_id("right")]
    documents = [sheet(list(mids), cl=17, primary=primary), sheet([], cl=17, dc=50)]
    for actor_id, document in zip(ids, documents):
        document["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        document["identity"]["proficiency_bonus"] = 4
        stats = document["ability_scores_and_statistics"]
        stats["hit_points"]["maximum"] = 400
        stats["technique_attack_bonus"] = 100
        folder = root / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    return ids, [compile_character(document, actor_id=actor_id)
                 for actor_id, document in zip(ids, documents)]


def _start_stock(root, seed):
    """The stock control: the unmodified gate4 roster on the given seed, exactly as the
    lock-round captures (``tools/compare_anchor_ai.py``, ``tests/prompt_ui_replay.py``)
    build it, but through the persistent session so the fight is really saved."""
    session = Gate4Persistence(ROOT, root).create_match(match_seed=seed, maximum_rounds=STOCK_ROUNDS)
    return session, session.match_id


def _start_summons(root):
    ids, bundles = _install_factory(root, "summons", SUMMON_MIDS, "Stamina")
    return _start_factory(root, "summons", ids, bundles)


def _start_zones(root):
    ids, bundles = _install_factory(root, "zones", ZONE_MIDS, "Qi")
    return _start_factory(root, "zones", ids, bundles)


def _start_factory(root, name, ids, bundles):
    combat = CombatService(ROOT, root)
    left, right = ids
    match = combat._finish_factory_match(
        bundles, ids, {left: "team:a", right: "team:b"},
        {left: {"x": 3, "y": 6}, right: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [left], [right],
        control_modes={actor_id: "LOCAL_AUTO" for actor_id in ids},
        match_seed="MMX83-" + name.upper(), display_name="MMX83 " + name,
        maximum_rounds=FACTORY_ROUNDS)["match_id"]
    return combat._load_session(match), match


FIGHTS = {
    "stock-LOCK5-A": (lambda root: _start_stock(root, "LOCK5-A"), 5),
    "stock-LOCK5-B": (lambda root: _start_stock(root, "LOCK5-B"), 5),
    "stock-LOCK5-C": (lambda root: _start_stock(root, "LOCK5-C"), 5),
    "stock-GATE4-TEST": (lambda root: _start_stock(root, "GATE4-TEST"), 5),
    "stock-GATE4-AN-1": (lambda root: _start_stock(root, "GATE4-AN-1"), 5),
    "stock-GATE4-LEE": (lambda root: _start_stock(root, "GATE4-LEE"), 5),
    "factory-summons": (_start_summons, 2),
    "factory-zones": (_start_zones, 7),
}

#: Always run, whatever MMX83_SAVE_RELOAD says: one stock control and one Factory fight.
FAST = ("stock-LOCK5-A", "factory-summons")
#: The stock controls on their own, for a run that installs no Factory character.
STOCK = tuple(name for name in FIGHTS if name.startswith("stock-"))

#: What each documented mode builds. Anything unrecognised builds every fight.
MODES = {"fast": FAST, "stock": STOCK}


def _selected(mode=None):
    """The fights this run builds, chosen by MMX83_SAVE_RELOAD.

    Read afresh each time rather than frozen at import, so the shared fixture and the
    parametrised cuts always agree about the same run, and so the selection itself can be
    tested (test_the_mode_picks_the_fights_to_build).
    """
    if mode is None:
        mode = os.environ.get("MMX83_SAVE_RELOAD", "")
    return MODES.get(mode, tuple(FIGHTS))


# ---------------------------------------------------------------- the two arms


def _choice_list(engine):
    """The engine's legal choice list: every candidate id and the label the engine reports."""
    return [[candidate.candidate_id, candidate.display_name] for candidate in engine.legal_candidates()]


def _play(root, start, cut=None):
    """Play one arm of a fight to its end, optionally cutting at ``cut`` decisions.

    ``start(root)`` returns the opening session and its match id. At the cut point the
    session, the engine, the controller and the policies are all dropped and the fight
    is reopened from storage through the service the table itself uses.
    """
    session, match_id = start(root)
    controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)

    def react(request):
        """AI reactions are decided by the same deterministic controller as its actions."""
        policy, _ = policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(session.engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    choices, steps, reloaded_at = [], 0, None
    while not session.engine.state.terminal_result and steps < STEP_CEILING:
        if cut is not None and steps == cut:
            del session, controller, policies  # the engine really goes away here
            session = CombatService(ROOT, root)._load_session(match_id)
            controller, policies = LocalDeterministicController(), PolicyLibrary(ROOT)
            reloaded_at = steps
        steps += 1
        choices.append(_choice_list(session.engine))
        policy, _ = policies.for_actor(session.engine.state.current_actor_id)
        choice = controller.choose_primary_action(build_decision_context(session.engine, policy, for_ai=True))
        session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=react)

    assert session.engine.state.terminal_result, f"the {match_id} fight never reached an end"
    assert reloaded_at is None or reloaded_at == cut
    # Read the finished fight back out of storage, so both arms are compared as a
    # restart sees them rather than as a still-running engine sees them.
    stored = CombatService(ROOT, root)._load_session(match_id)
    assert stored.verify()["status"] == stored.mechanical.replay()["status"] == "PASS"
    rows = [json.loads(line) for line in (stored.store.match_dir / "Journal.ndjson").read_text().splitlines()]
    commits = [row for row in rows if row["record_type"] == "COMMIT"]
    state = stored.engine.state.model_dump(mode="json")
    state["match_id"] = None  # Independent saves use different storage identifiers.
    return {
        "choices": choices,
        "events": [row["events"] for row in commits],
        "rolls": [row["rolls"] for row in commits],
        "state": state,
        "steps": steps,
        "reloaded_at": reloaded_at,
        "summons": sum(1 for actor in stored.engine.state.actors.values() if actor.summon),
        "zones": len(stored.engine.state.zones),
    }


def _bytes_of(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _first_difference(left, right, path=""):
    """The first differing JSON path, or None. Byte comparison with a locating report."""
    if type(left) is not type(right):
        return {"path": path, "straight_through": left, "cut_and_reloaded": right}
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            difference = _first_difference(left.get(key), right.get(key), f"{path}/{key}")
            if difference is not None:
                return difference
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return {"path": f"{path} (length)", "straight_through": len(left), "cut_and_reloaded": len(right)}
        for index, (one, other) in enumerate(zip(left, right)):
            difference = _first_difference(one, other, f"{path}/{index}")
            if difference is not None:
                return difference
        return None
    return None if left == right else {"path": path, "straight_through": left, "cut_and_reloaded": right}


# ---------------------------------------------------------------- the tests


def _cut_points(steps):
    """After decision 5, after decision 20 and the midpoint, as far as the fight runs."""
    points = {5, 20, steps // 2}
    return sorted(point for point in points if 0 < point < steps)


def _play_arm_a(root, name):
    """Arm A for one named fight: the same game played straight through, in its own root."""
    return _play(root, FIGHTS[name][0])


def _guard_specials(played):
    """Each Factory baseline is only worth building if it did its own special thing.

    Guarded by presence, so a reduced run is not made to fail over a fight it skipped.
    """
    if "factory-summons" in played:
        assert played["factory-summons"]["summons"] >= 1, "the summons fight must actually summon"
    if "factory-zones" in played:
        assert played["factory-zones"]["zones"] >= 1, "the zones fight must actually lay an area"


def _build_arm_a(tmp_path_factory, names):
    """Play arm A once for each named fight, in its own root, and check it is a real fight.

    Separate from the fixture so the selection contract can be checked without playing
    eight fights: test_a_reduced_run_builds_only_the_selected_fights calls this through the
    fixture with a stand-in for _play_arm_a.
    """
    played = {}
    for name in names:
        root = tmp_path_factory.mktemp("armA-" + name)
        arm = _play_arm_a(root, name)
        played[name] = arm
        assert arm["choices"] and all(arm["choices"]), f"{name} offered no legal choices at some step"
        assert arm["events"] and arm["rolls"], f"{name} recorded no committed history"
    _guard_specials(played)
    return played


@pytest.fixture(scope="module")
def straight_through(tmp_path_factory):
    """Arm A for the fights this run selected, played once and kept, since it is the same
    run for every cut."""
    return _build_arm_a(tmp_path_factory, _selected())


#: ``MMX83_SAVE_RELOAD`` picks the parametrised cuts; the fixture above picks the baselines.
SELECTED = _selected()


@pytest.mark.parametrize("name", SELECTED, ids=SELECTED)
def test_a_fight_reloaded_midway_is_the_same_game(straight_through, name, tmp_path):
    """A fight cut in half and reloaded from storage is the same game, choice for choice."""
    arm_a = straight_through[name]
    for cut in _cut_points(arm_a["steps"]):
        root = tmp_path / f"{name}-cut{cut}"
        root.mkdir()
        arm_b = _play(root, FIGHTS[name][0], cut=cut)

        assert arm_b["reloaded_at"] == cut, f"{name}: the fight was not reloaded at the cut"
        assert arm_b["steps"] == arm_a["steps"], (
            f"{name} cut {cut}: {arm_a['steps']} decisions played straight through, "
            f"{arm_b['steps']} after reloading")

        # The legal choice list, id and label, at every step of both arms.
        for step, (before, after) in enumerate(zip(arm_a["choices"], arm_b["choices"])):
            difference = _first_difference(before, after, f"step {step}")
            assert difference is None, (
                f"{name} cut {cut}: the legal choices differ after reloading\n{difference}")

        # The fight's own history, read back out of storage.
        difference = _first_difference(arm_a["events"], arm_b["events"], "events")
        assert difference is None, f"{name} cut {cut}: the event log differs\n{difference}"
        difference = _first_difference(arm_a["rolls"], arm_b["rolls"], "rolls")
        assert difference is None, f"{name} cut {cut}: the rolls differ\n{difference}"
        difference = _first_difference(arm_a["state"], arm_b["state"], "state")
        assert difference is None, f"{name} cut {cut}: the final state differs\n{difference}"

        # Byte-identical, not merely equal field by field.
        for label in ("events", "rolls", "state"):
            from tests.replay_assertions import assert_replay_equal
            assert_replay_equal(_bytes_of(arm_a[label]), _bytes_of(arm_b[label]), f"{name} cut {cut}: {label} bytes differ")


def test_a_reload_on_its_own_changes_nothing(straight_through, tmp_path):
    """Dropping the engine and reopening the fight at the very first decision is the
    baseline the equivalence rests on: no reload may be the control for itself."""
    name = FAST[0]
    arm_a = straight_through[name]
    root = tmp_path / "cut-at-zero"
    root.mkdir()
    arm_b = _play(root, FIGHTS[name][0], cut=0)
    assert arm_b["reloaded_at"] == 0
    assert arm_b["steps"] == arm_a["steps"]
    for label in ("events", "rolls", "state"):
        from tests.replay_assertions import assert_replay_equal
        assert_replay_equal(_bytes_of(arm_a[label]), _bytes_of(arm_b[label]), f"{label} bytes differ")


def test_every_fight_is_a_real_fight_that_survives_a_restart(straight_through, tmp_path):
    """The property is only worth something if the fights are real: each one must run to a
    decided end, commit real history, and reopen from storage with verify and replay PASS.
    Every fight this run selected is checked - a reduced run checks fewer, which is what it
    asked for."""
    for name, arm in straight_through.items():
        assert arm["steps"] > 10, f"{name} was too short to be a real fight"
        assert len(arm["events"]) > 10, f"{name} committed too little history"
        assert all(arm["choices"]), f"{name} offered no legal choices at some step"
    _guard_specials(straight_through)


def test_the_comparison_can_tell_two_different_fights_apart(straight_through, tmp_path):
    """A guard on the guard: the byte comparison has to be able to report a difference, or
    the equivalence proved above would be worth nothing. Two seeds of the same stock roster
    are two different games, and must not compare equal."""
    here = straight_through[FAST[0]]
    other = tmp_path / "other"
    other.mkdir()
    elsewhere = _play(other, FIGHTS["stock-LOCK5-B"][0])
    assert here["steps"] > 0 and elsewhere["steps"] > 0
    for label in ("events", "rolls", "state"):
        assert _first_difference(here[label], elsewhere[label], label) is not None, (
            f"two different fights compared equal on {label}: the comparison is blind")
        assert _bytes_of(here[label]) != _bytes_of(elsewhere[label])


def test_the_mode_picks_the_fights_to_build():
    """MMX83f1: each documented mode names the fights it builds, and an unset or
    unrecognised mode builds all of them."""
    assert _selected("fast") == FAST
    assert _selected("stock") == STOCK
    assert _selected("") == tuple(FIGHTS)
    assert _selected("nonsense") == tuple(FIGHTS)
    assert set(FAST) < set(FIGHTS), "the fast set must be a strict subset of the grid"
    assert set(STOCK) < set(FIGHTS), "the stock set must be a strict subset of the grid"
    assert [name for name in FAST if not name.startswith("stock-")] == ["factory-summons"], (
        "the fast set keeps one stock control and one Factory fight")
    assert tuple(name.removeprefix("stock-") for name in STOCK) == STOCK_SEEDS, (
        "the stock set must be exactly the six seeded stock controls")


#: A stand-in arm, for the selection test only: the shape _build_arm_a checks, not a played
#: fight. It lets the selection be tested without playing eight fights.
_STAND_IN = {
    name: {"choices": [["candidate-0", "Attack"]], "events": [[{}]], "rolls": [[{}]], "state": {},
           "steps": 30, "reloaded_at": None, "summons": 1, "zones": 1}
    for name in FIGHTS
}


def test_a_reduced_run_builds_only_the_selected_fights(monkeypatch, tmp_path_factory):
    """MMX83f1: a reduced run must not pay for the fights it skipped.

    The shared fixture used to walk every fight whatever MMX83_SAVE_RELOAD said, so `fast`
    still built all eight baselines and the per-fight guards still demanded the Factory
    fights: the documented quick check was not quick. This calls the shipped fixture with a
    stand-in for _play_arm_a - a test double inside this module, no product code is touched -
    and checks it builds exactly the selected fights in every documented mode.
    """
    built = []

    def stand_in(root, name):
        built.append(name)
        return _STAND_IN[name]

    fixture_function = getattr(straight_through, "__wrapped__", straight_through)
    monkeypatch.setattr(f"{__name__}._play_arm_a", stand_in)
    for mode, expected in (("fast", FAST), ("stock", STOCK), ("", tuple(FIGHTS))):
        monkeypatch.setenv("MMX83_SAVE_RELOAD", mode)
        built.clear()
        played = fixture_function(tmp_path_factory)
        assert tuple(played) == tuple(expected), (
            f"MMX83_SAVE_RELOAD={mode or '<unset>'} built {tuple(played)}, expected {tuple(expected)}")
        assert built == list(expected), f"the fixtures asked to play {built}"


def test_an_arm_leaves_only_the_saved_fight_behind(tmp_path):
    """Every arm works inside pytest's own tmp_path and saves the fight and nothing else,
    so the harness leaves no scratch files behind on disk."""
    root = tmp_path / "throwaway"
    root.mkdir()
    _play(root, FIGHTS[FAST[0]][0], cut=1)
    assert sorted(p.name for p in root.iterdir()) == ["Combat"]
