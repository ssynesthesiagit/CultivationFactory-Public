"""AUTO89r1f1 -- the independent pre-merge review's findings 1-3, fixed and proved at the table.

``AUTO89r1.review.md`` charged three defects in the Court of the Crawling Fever's automation, all of which are
regressions of the ``choose_court_allies`` work rather than of the sphere automation itself:

1. **HIGH -- an enemy's turn reopened the maker's selection and overwrote the saved answer.** The printed
   "When an enemy starts its turn in the aura, it makes a Constitution saving throw" is compiled into the area's
   *own* ``:own`` start trigger (``factory_compiler.py`` gives a zone the ability's own effects), so
   ``combat/ext/disease_court.py:crawling_fever`` runs on every enemy turn start inside the aura, not only when the
   maker raises it. It re-ran the whole setup: a second copy of the start trigger was appended, and the maker was
   asked again *on the enemy's turn*, replacing the beneficiaries already stored on the aura.

2. **MEDIUM -- overlapping Courts suppressed valid benefits.** ``court_covers`` returned the *first* same-team Court
   containing the subject and then checked only that Court's stored answer, so Court A (which excluded an ally) hid
   Court B (which included it), and a second maker standing inside Court A lost its own automatic benefit. Which
   Court came first in the area list decided the answer.

3. **MEDIUM -- older saved Courts silently lost every ally benefit.** A missing ``court_allies`` field was read
   exactly like an explicit decline, so loading a fight saved before the choice existed removed its allies' Disease
   -save Advantage, resistance and token-shed eligibility without asking and without a word.

Each is proved below through the real table, and each test fails without its fix:

* ``test_the_makers_answer_survives_an_enemy_turn_and_a_reload`` -- finding 1, full table lifecycle: an enemy turn
  start neither asks again nor duplicates the trigger, the printed save still fires, and the answer is still there
  after the table's commit and reload.
* ``test_overlapping_courts_each_grant_their_own_beneficiaries`` -- finding 2, both creation orders.
* ``test_an_aura_saved_before_the_choice_existed_keeps_its_allies`` -- finding 3, an actual pre-change aura on disk
  through a real commit and reload, kept distinguishable from a maker who chose nobody.
* ``test_the_tables_own_stepping_answers_the_court_choice_for_an_ai_maker`` -- the AI-step path, which the earlier
  lane proved only through a hand-driven engine.

Every fight here is a real ``CombatService`` + ``TabletopService`` match from real compiled Factory sheets, and the
Court is raised through the table's own menu -- never by poking the engine.
"""

from __future__ import annotations

import json

import pytest

from combat.ext import disease
from combat.ext import disease_court
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_auto89f1_disease import (ALLY, CRAWLING_KEY, COURT, COURT_CHOICE, FOE, MARK, OUTSIDER, SOW,
                                         TEAMS, WARDEN, _bundle, _court_zone, _disease_bases, _end_turn, _engine,
                                         _labels, _options, _raise_court, _session, _step, _turn_of, _use)
from tests.test_auto89f1_disease import _roster as _older_module_roster

SEED = "AUTO89R1F1-COURT"
# A second Disease cultivator on the Warden's own team, so two Courts of the Crawling Fever can overlap.
SEPTIC = "actor:factory.f1-septic"
PICKED, LEFT_OUT = ALLY, OUTSIDER
# Every ally and both makers stand inside both auras, and so does the Foe, so it is tested by both Courts'
# turn-start saves. All cells are free on battlefield:factory_pillar_arena (the fixture asserts this).
PLACES = {WARDEN: {"x": 2, "y": 6}, SEPTIC: {"x": 4, "y": 6}, ALLY: {"x": 3, "y": 6},
          OUTSIDER: {"x": 5, "y": 6}, FOE: {"x": 6, "y": 6}, MARK: {"x": 6, "y": 8}}
# This file's own roster: a *copy* of the older module's TEAMS plus the second maker, never the shared dictionary
# itself. Mutating the imported one would add a sixth actor to a primary roster that this module builds six
# bundles for but test_auto89f1_disease builds only five for, which its own _start then rejects as
# C3C_DYNAMIC_ROSTER_UNKNOWN. pytest imports the two files under different module names (there is no
# tests/__init__.py), so that corruption can hide until anything imports them as one package -- see
# test_this_files_roster_does_not_touch_the_older_modules_own.
COURT_TEAMS = {**TEAMS, SEPTIC: "team:factory"}


def _roster(*, second_maker=False, ask_maker=False, stable_concentration=False):
    warden = _bundle([*_disease_bases(), SOW, COURT], WARDEN, "Fever Warden", attack_bonus=100,
                     con_score=30 if stable_concentration else None)
    if ask_maker:  # the sheet's Reactions setting "Ask me": the player answers this character's own prompts
        warden["reaction_plan"] = {**warden["reaction_plan"], "mode": "ask", "ask": True}
    roster = [
        warden,
        _bundle([*_disease_bases(), SOW, COURT], SEPTIC, "Second Warden", attack_bonus=100) if second_maker else
        _bundle([], SEPTIC, "Second Warden", no_base=True, armor_class=2),
        _bundle([], ALLY, "Fever Ally", no_base=True, armor_class=2),
        _bundle([], OUTSIDER, "Second Ally", no_base=True, armor_class=2),
        _bundle([*_disease_bases(), SOW], FOE, "Bloat", attack_bonus=100),
        _bundle([], MARK, "Wasting Hand", no_base=True, armor_class=2),
    ]
    return [b for b in roster if b]


def _start(root, *, second_maker=False, ask_maker=False, positions=None, maker_mode="MANUAL", control_modes=None,
           stable_concentration=False):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    # Only the Warden may be handed to the table's own stepping: the manual helpers that walk the initiative
    # (``_turn_of``/``_end_turn``) need an ``end_turn`` candidate, which an AI-controlled actor's menu does not carry.
    modes = control_modes if control_modes is not None else {
        WARDEN: maker_mode, SEPTIC: "MANUAL", ALLY: "MANUAL", OUTSIDER: "MANUAL", FOE: "MANUAL", MARK: "MANUAL"}
    mid = combat._finish_factory_match(
        _roster(second_maker=second_maker, ask_maker=ask_maker, stable_concentration=stable_concentration),
        list(COURT_TEAMS), COURT_TEAMS, positions or PLACES,
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [WARDEN, SEPTIC], [FOE, MARK], control_modes=modes,
        match_seed=SEED, display_name="AUTO89r1f1 Court", maximum_rounds=20)["match_id"]
    return combat, table, mid


def _fight(root, **kw):
    return _start(root, **kw)


def test_this_files_roster_does_not_touch_the_older_modules_own():
    """This module adds a sixth Disease cultivator to its roster, and it must do that on a copy.

    ``TEAMS`` is imported from ``test_auto89f1_disease``, whose own ``_start`` builds five bundles and passes
    ``list(TEAMS)`` as its primary roster. Writing ``SEPTIC`` into the imported dictionary would leave that older
    module with a six-actor primary roster and no template for the sixth, which
    ``gate2_engine._create_match`` rejects as ``C3C_DYNAMIC_ROSTER_UNKNOWN`` -- silently breaking valid tests in
    another file. The corruption hides in an ordinary combined run because pytest imports the two files under
    different module names (there is no ``tests/__init__.py``), so each gets its own ``TEAMS``; it appears as soon as
    both are imported as one package, which is what importing them under ``tests.`` does.
    """
    import sys

    # the module object this file's TEAMS was imported from, whatever name pytest gave that module
    owner = next(mod for mod in list(sys.modules.values())
                 if getattr(mod, "TEAMS", None) is TEAMS and getattr(mod, "__name__", "").endswith("test_auto89f1_disease"))
    assert owner.__name__ != __name__, "this test must live in the module that owns the second maker"
    assert SEPTIC not in TEAMS, "this file added its second maker to the older module's roster"
    assert SEPTIC in COURT_TEAMS, "this file's own roster must carry the second maker"
    assert COURT_TEAMS is not TEAMS, "this file must extend a copy, never the shared dictionary"
    assert COURT_TEAMS[SEPTIC] == TEAMS[WARDEN], "the second maker fights on the Warden's own team"

    # the older module's own roster still matches the bundles its own _start builds for it
    assert len(_older_module_roster()) == len(TEAMS)
    assert len(_roster(second_maker=False)) == len(COURT_TEAMS)
    assert sorted(b["actor_id"] for b in _roster(second_maker=True)) == sorted(COURT_TEAMS)


def _court_questions(prompt):
    return prompt["context"]["reaction_source_id"] == COURT_CHOICE


def _start_triggers(engine, owner_id):
    """The Court's own start triggers on the aura ``owner_id`` raised."""
    zone = next((z for z in disease._zones_of(engine, CRAWLING_KEY) if z.owner_id == owner_id), None)
    if zone is None:
        return []
    return [t for t in (zone.trigger_profile or {}).get("triggers") or []
            if str(t.get("id")) == f"{COURT}:start"]


def _allies_of(engine, zone):
    return (zone.trigger_profile or {}).get(disease.COURT_ALLIES)


def _saved(engine):
    """Every ZONE_CREATED republication of an aura, in order, with the answer each one stored."""
    return [(e.payload or {}).get("zone", {}).get("trigger_profile", {}).get(disease.COURT_ALLIES)
            for e in engine.events if e.event_type == "ZONE_CREATED"
            and COURT in str((e.payload or {}).get("zone", {}).get("source_definition_id", ""))]


# ----------------------------------------------------------------------------------------- finding 1: the table lifecycle
def test_the_makers_answer_survives_an_enemy_turn_and_a_reload(tmp_path):
    """The whole printed lifecycle, end to end: the maker answers once when it raises the Court, an enemy then starts
    its turn inside the aura, and that turn neither asks the maker a second time nor disturbs the answer.

    Before the fix the enemy's turn start re-ran ``crawling_fever``: ``zones._run`` executes the area's own ``:own``
    start trigger with the Court's action, ``zone_made_now`` finds the aura already standing, and the maker was
    asked again on the enemy's turn -- the question landed in a *reactor* slot the enemy could not answer, and the
    answer already stored on the aura was replaced by the empty one that came back.
    """
    combat, table, mid = _fight(tmp_path)
    asked = _raise_court(table, mid, state=_walk_to(table, combat, mid, WARDEN),
                         choose=lambda options: [o for o in options if o == PICKED])
    assert len(asked) == 1, asked
    engine = _engine(combat, mid)
    assert _allies_of(engine, _court_zone(engine)) == [PICKED]
    published = _saved(engine)

    # An enemy starts its turn inside the aura. Every question the table asks across that turn start is collected.
    during_enemy_turn: list[dict] = []
    for _ in range(14):
        state = table.state(mid)
        if state["menu"]["actor_id"] == FOE:
            break
        during_enemy_turn.extend(_end_turn(table, mid, state, lambda prompt: during_enemy_turn.append(prompt) and None))
    else:
        raise AssertionError("the Foe never came up")

    assert not [_options(p) for p in during_enemy_turn if _court_questions(p)], \
        "the maker was asked again during an enemy's turn: " + json.dumps([p for p in during_enemy_turn if _court_questions(p)])
    engine = _engine(combat, mid)
    assert _allies_of(engine, _court_zone(engine)) == [PICKED], "an enemy's turn start overwrote the saved answer"
    assert _start_triggers(engine, WARDEN) != [], "the Court's own start trigger went missing"
    assert len(_start_triggers(engine, WARDEN)) == 1, \
        f"the Court gained a second start trigger: {_start_triggers(engine, WARDEN)}"
    assert _saved(engine) == published, "an enemy's turn start republished the aura"

    # the printed save still works: the enemy is still tested by the aura when it starts its turn inside it
    assert any(e.event_type == "PASSIVE_TRIGGERED" and COURT in str(e.source_definition_id) and FOE in e.target_ids
               for e in engine.events), "the Foe standing its turn inside the Court was never tested by it"

    # and the beneficiaries are still the chosen ones after the table's own commit and reload
    reloaded = _engine(combat, mid)
    assert _allies_of(reloaded, _court_zone(reloaded)) == [PICKED]
    assert disease.court_covers(reloaded, reloaded.state.actors[PICKED]) is True
    assert disease.court_covers(reloaded, reloaded.state.actors[LEFT_OUT]) is False
    assert _session(combat, mid).verify()["status"] == "PASS"


def test_the_guard_is_per_aura_not_per_ability(tmp_path):
    """The guard reads the aura, not "was this ability used before": an aura that carries neither of the two markers
    is a fresh one and is set up and asked, while an aura carrying either is already standing and is left alone.
    This is what stops the guard from going too far and swallowing a maker's *second* Court."""
    combat, table, mid = _fight(tmp_path)
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: [o for o in options if o == PICKED])
    standing = _court_zone(_engine(combat, mid))
    assert disease_court._already_standing(standing) is True

    fresh = standing.model_copy(deep=True)
    fresh.zone_id = standing.zone_id + ":2"
    fresh.trigger_profile = {k: v for k, v in (standing.trigger_profile or {}).items()
                             if k != disease.COURT_ALLIES and k != "triggers"}  # a new aura, before it is set up
    assert disease_court._already_standing(fresh) is False
    # either marker on its own is enough to say the aura is standing
    marked_answer = fresh.model_copy(deep=True)
    marked_answer.trigger_profile = {**fresh.trigger_profile, disease.COURT_ALLIES: []}
    assert disease_court._already_standing(marked_answer) is True
    marked_trigger = fresh.model_copy(deep=True)
    marked_trigger.trigger_profile = {**fresh.trigger_profile, "triggers": [{"id": f"{COURT}:start"}]}
    assert disease_court._already_standing(marked_trigger) is True


# ----------------------------------------------------------------------------------------- finding 2: overlapping Courts
@pytest.mark.parametrize("first_maker", [WARDEN, SEPTIC])
def test_overlapping_courts_each_grant_their_own_beneficiaries(tmp_path, first_maker):
    """Two Disease cultivators on one team, two overlapping Courts, and each keeps what its own maker gave it.

    Before the fix ``court_covers`` returned the first same-team Court containing the subject and read only that
    Court's stored answer, so whichever Court was created first hid the other: the Second Warden's own maker --
    standing inside a Court whose answer did not name it -- lost the printed benefits it grants itself, and an ally
    the second Court had chosen lost them whenever it also stood inside the first Court's aura.
    """
    combat, table, mid = _fight(tmp_path / first_maker, second_maker=True)
    second = SEPTIC if first_maker == WARDEN else WARDEN

    def raise_for(maker):
        _raise_court(table, mid, state=_turn_of(table, mid, maker),
                     choose=lambda options: [o for o in options if o == PICKED])

    raise_for(first_maker)
    raise_for(second)
    engine = _engine(combat, mid)
    wards = [z for z in disease._zones_of(engine, CRAWLING_KEY) if z.owner_id in (WARDEN, SEPTIC)]
    assert len(wards) == 2, wards
    for zone in wards:
        assert disease._inside(zone, engine.state.actors[PICKED]), "the fixture must put the ally inside both auras"
        assert disease._inside(zone, engine.state.actors[second]), "the fixture must put both makers inside both auras"
    assert _allies_of(engine, next(z for z in wards if z.owner_id == WARDEN)) == [PICKED]
    assert _allies_of(engine, next(z for z in wards if z.owner_id == SEPTIC)) == [PICKED]

    # each maker keeps its own printed "You ... gain", whichever Court it is standing inside
    for maker in (WARDEN, SEPTIC):
        assert disease.court_covers(engine, engine.state.actors[maker]) is True, maker
        assert disease._sheltered(engine, engine.state.actors[maker]) is True, maker
    # the ally both makers chose keeps the benefits of both, whichever Court comes first in the area list
    assert disease.court_covers(engine, engine.state.actors[PICKED]) is True
    assert disease._sheltered(engine, engine.state.actors[PICKED]) is True

    # an ally neither maker chose gains nothing, even though it stands inside two auras
    combat2, table2, mid2 = _fight(tmp_path / f"{first_maker}-none", second_maker=True)
    _raise_court(table2, mid2, state=_turn_of(table2, mid2, WARDEN), choose=lambda options: None)
    _raise_court(table2, mid2, state=_turn_of(table2, mid2, SEPTIC), choose=lambda options: None)
    engine2 = _engine(combat2, mid2)
    assert disease.court_covers(engine2, engine2.state.actors[LEFT_OUT]) is False
    assert disease._sheltered(engine2, engine2.state.actors[LEFT_OUT]) is False
    # a maker still keeps its own, with no ally named by anybody
    for maker in (WARDEN, SEPTIC):
        assert disease.court_covers(engine2, engine2.state.actors[maker]) is True, maker

    # and the overlap survives the table's commit and reload
    assert _allies_of(_engine(combat, mid), _court_zone(_engine(combat, mid))) is not None
    assert _session(combat, mid).verify()["status"] == "PASS"
    assert _session(combat2, mid2).verify()["status"] == "PASS"


def test_a_maker_named_by_one_court_keeps_its_benefit_from_a_second_court_whose_maker_left_it_out(tmp_path):
    """The overlap case the review named: the ally Court B chose is still inside Court A, which never named it."""
    combat, table, mid = _fight(tmp_path / "split", second_maker=True)
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: None)  # nobody
    _raise_court(table, mid, state=_turn_of(table, mid, SEPTIC), choose=lambda options: [o for o in options if o == PICKED])
    engine = _engine(combat, mid)
    assert _allies_of(engine, next(z for z in disease._zones_of(engine, CRAWLING_KEY) if z.owner_id == WARDEN)) == []
    assert _allies_of(engine, next(z for z in disease._zones_of(engine, CRAWLING_KEY) if z.owner_id == SEPTIC)) == [PICKED]
    assert disease.court_covers(engine, engine.state.actors[PICKED]) is True   # Court B names it
    assert disease.court_covers(engine, engine.state.actors[LEFT_OUT]) is False  # neither Court names it
    # the printed resistance follows the chosen ally through both auras
    from combat import typed_reactions

    sow = next(a for a in engine.state.actors[SEPTIC].action_ids if a.endswith(SOW))
    assert typed_reactions.defend(engine, engine.state.actors[PICKED], 12, "NECROTIC", sow, SEPTIC) == 6
    assert typed_reactions.defend(engine, engine.state.actors[LEFT_OUT], 12, "NECROTIC", sow, SEPTIC) == 12


# ----------------------------------------------------------------------------------------- finding 3: a save written before the choice
def _retire_the_stored_answer(combat, mid):
    """Rewrite this fight on disk into one saved *before* the Court maker was ever asked, and return nothing.

    A real legacy save, not a detached engine patched in memory: the recorded ``ZONE_CREATED`` event loses its
    ``court_allies`` answer, and the journal is then re-chained and its committed post-state hashes recomputed
    through the store's own reducer, so the file set is exactly what an older engine would have written and the
    service loads it with all of its own integrity checks passing.
    """
    from combat.canonical import canonical_bytes
    from combat.gate3_models import Gate3CommitPayload
    from combat.gate3_reducer import canonical_state_sha256
    from combat.gate3_storage import Gate3MatchStore, _record_hash, _typed_record_payload
    from combat.gate4_persistence import Gate4Persistence

    persistence = Gate4Persistence(combat.source_root, combat.userdata_root)
    store = Gate3MatchStore(combat.userdata_root, mid)
    _, genesis = persistence._load_lock_genesis(store)
    path = store.journal_path
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    retired = 0
    for record in records:
        for event in record.get("events") or []:
            if event.get("event_type") != "ZONE_CREATED":
                continue
            profile = ((event.get("payload") or {}).get("zone") or {}).get("trigger_profile")
            if isinstance(profile, dict) and disease.COURT_ALLIES in profile:
                profile.pop(disease.COURT_ALLIES)  # the answer did not exist yet, so it is not in this save
                retired += 1
    assert retired, "this fight has no stored Court answer to retire"

    # replay the rewritten events through the real reducer so every committed post-state hash still matches
    state = genesis.state.model_copy(deep=True)
    for record in records:
        if record.get("record_type") != "COMMIT":
            continue
        payload = Gate3CommitPayload.model_validate(_typed_record_payload(record, Gate3CommitPayload))
        state = persistence.reducer.apply_events(state, payload.events)
        state.state_version = payload.post_state_version
        state.roll_counter = payload.roll_counter_end
        if payload.terminal_result is not None:
            state.terminal_result = payload.terminal_result
        record["post_state_sha256"] = canonical_state_sha256(state)

    lines, previous = [], None
    for record in records:
        record.pop("record_sha256", None)
        if previous is not None:
            record["previous_record_sha256"] = previous
        record["record_sha256"] = _record_hash(record)  # the journal is a hash chain: relink it in order
        previous = record["record_sha256"]
        lines.append(canonical_bytes(record).decode())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_legacy_court_survives_a_real_enemy_turn_a_commit_and_a_reload(tmp_path):
    """A fight saved before the choice existed, opened and played on through the table.

    An aura with no stored ``court_allies`` at all is a fight saved before the maker was ever asked, so every ally
    standing in it was a beneficiary when it was raised. Reading that as an empty answer silently took the printed
    Disease-save Advantage, the Poison/Necrotic resistance and the token-shed away from every one of them, with no
    question asked and nothing said.

    The save is genuinely on disk here: the answer is retired from the recorded events and the journal re-chained,
    so ``table.state`` and every table action below read a legacy fight the service really loads. An enemy then
    starts its turn inside the aura, which is where a legacy turn-trigger regression would hide -- the printed save
    must still fire, the legacy beneficiaries must survive, and the missing answer must not become a new question.
    """
    combat, table, mid = _fight(tmp_path / "legacy")
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: [o for o in options if o == PICKED])
    _retire_the_stored_answer(combat, mid)

    # the service opens the rewritten save through its own integrity checks
    engine = _engine(combat, mid)
    legacy = _court_zone(engine)
    assert disease.COURT_ALLIES not in (legacy.trigger_profile or {}), "this save still carries an answer"
    for ally in (WARDEN, PICKED, LEFT_OUT):  # every ally in it, chosen or not, kept what it had
        assert disease.court_covers(engine, engine.state.actors[ally]) is True, ally
        assert disease._sheltered(engine, engine.state.actors[ally]) is True, ally
    from combat import typed_reactions

    sow = next(a for a in engine.state.actors[WARDEN].action_ids if a.endswith(SOW))
    for ally in (PICKED, LEFT_OUT):  # the printed Poison/Necrotic resistance, for both
        assert typed_reactions.defend(engine, engine.state.actors[ally], 12, "NECROTIC", sow, WARDEN) == 6, ally
    assert typed_reactions.defend(engine, engine.state.actors[FOE], 12, "NECROTIC", sow, WARDEN) == 12  # an enemy is not an ally
    published = _saved(engine)

    # an enemy starts its turn inside the legacy aura, through the table's own actions on the legacy save
    asked: list[dict] = []
    for _ in range(14):
        state = table.state(mid)
        if state["menu"]["actor_id"] == FOE:
            break
        _end_turn(table, mid, state, lambda prompt: asked.append(prompt) and None)
    else:
        raise AssertionError("the Foe never came up")

    assert not [_options(p) for p in asked if _court_questions(p)], \
        "the legacy aura put a new Court question to its maker: " + json.dumps([p for p in asked if _court_questions(p)])

    # the printed save still fires on that enemy turn start, and the aura was not republished or re-set-up
    engine = _engine(combat, mid)
    assert any(e.event_type == "PASSIVE_TRIGGERED" and COURT in str(e.source_definition_id) and FOE in e.target_ids
               for e in engine.events), "the legacy Court never tested the enemy starting its turn inside it"
    assert disease.COURT_ALLIES not in (_court_zone(engine).trigger_profile or {}), \
        "an enemy turn start wrote an answer into a legacy aura"
    assert len(_start_triggers(engine, WARDEN)) == 1, f"the legacy Court gained a second start trigger: {_start_triggers(engine, WARDEN)}"
    assert _saved(engine) == published, "an enemy turn start republished the legacy aura"

    # and every legacy benefit is still there after the table's commit and reload
    reloaded = _engine(combat, mid)
    assert disease.COURT_ALLIES not in (_court_zone(reloaded).trigger_profile or {})
    for ally in (WARDEN, PICKED, LEFT_OUT):
        assert disease.court_covers(reloaded, reloaded.state.actors[ally]) is True, ally
        assert disease._sheltered(reloaded, reloaded.state.actors[ally]) is True, ally
    assert _session(combat, mid).verify()["status"] == "PASS"


def test_a_maker_who_stored_an_empty_answer_keeps_it_through_a_reload(tmp_path):
    """The negative control for the legacy reading: a maker who *did* answer "nobody" stored an empty list, which
    is a value rather than a missing key, so it keeps excluding every ally and survives the commit and reload."""
    combat, table, mid = _fight(tmp_path / "declined")
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: None)
    engine = _engine(combat, mid)
    assert _allies_of(engine, _court_zone(engine)) == []
    assert disease.court_covers(engine, engine.state.actors[PICKED]) is False
    assert disease.court_covers(engine, engine.state.actors[WARDEN]) is True
    assert _allies_of(_engine(combat, mid), _court_zone(_engine(combat, mid))) == [], \
        "a reload turned a stored 'nobody' into the legacy 'no answer stored'"


def test_an_enemy_starting_its_turn_in_a_legacy_aura_does_not_start_asking(tmp_path):
    """The legacy aura carries no answer, and that must not make the maker's turn a question: a Court raised before
    the choice existed is already standing, so its turn trigger must leave it exactly as it found it."""
    combat, table, mid = _fight(tmp_path / "legacy-turn")
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: [o for o in options if o == PICKED])
    _retire_the_stored_answer(combat, mid)
    engine = _engine(combat, mid)
    assert disease.COURT_ALLIES not in (_court_zone(engine).trigger_profile or {}), "this save still carries an answer"
    published = _saved(engine)

    asked: list[dict] = []
    for _ in range(14):
        state = table.state(mid)
        if state["menu"]["actor_id"] == FOE:
            break
        _end_turn(table, mid, state, lambda prompt: asked.append(prompt) and None)
    else:
        raise AssertionError("the Foe never came up")
    assert not [p for p in asked if _court_questions(p)], "a legacy aura started asking its maker for an answer"
    engine = _engine(combat, mid)
    assert _saved(engine) == published, "a legacy aura was republished by an enemy turn start"
    assert len(_start_triggers(engine, WARDEN)) == 1, _start_triggers(engine, WARDEN)


# ----------------------------------------------------------------------------------------- the AI-step path
AI_MODES = {actor: "LOCAL_AUTO" for actor in COURT_TEAMS}
# The Warden is the one actor a test drives by hand; every other fighter is handed to the table's own stepping. A
# stepping test that leaves anybody on MANUAL proves nothing: ``CombatService.auto_step`` returns
# ``AWAITING_NON_AUTO_CONTROL`` for that actor and commits no intent at all, so no turn ever comes round.
STEPPED_MODES = {**AI_MODES, WARDEN: "MANUAL"}


def _walk_to(table, combat, mid, actor, *, answer=lambda prompt: None, limit=40):
    """Advance the fight to ``actor``'s turn, whichever way each fighter is controlled.

    A hand-played fighter's menu carries an ``end_turn`` entry and is advanced through the table; an AI-controlled
    one has no such entry (``table.state`` returns an empty menu for it), so it is advanced by
    ``CombatService.auto_step`` -- which is what the table itself uses to step a fight.
    """
    for _ in range(limit):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor:
            return state
        if "end_turn" in state["menu"]:
            _end_turn(table, mid, state, answer)
        elif combat.auto_step(mid).get("status") != "COMMITTED":
            return None
    return None


def _step_until_actor(combat, mid, actor, *, limit=40):
    """Real Local Auto steps until ``actor`` is the one whose turn it is."""
    for _ in range(limit):
        if _engine(combat, mid).state.current_actor_id == actor:
            return True
        if combat.auto_step(mid).get("status") != "COMMITTED":
            return False
    return False


def _answers_on_the_aura(engine):
    """Every answer the aura was ever republished with, ignoring the first creation before it was answered."""
    return [tuple(row) for row in _saved(engine) if row is not None]


def test_the_table_steps_a_fight_and_never_reopens_a_court_makers_answer(tmp_path):
    """The AI-step path, with the fight actually moving.

    ``choice_reactors`` enrols a player playing a Court maker as the table's business even when the table steps the
    fight itself, and ``CombatService.auto_step`` is how the table steps it. The maker raises its Court on its own
    turn through the table's own menu; every other fighter is under Local AI, so the steps below commit real intents
    and turns really come round -- including an enemy starting its turn inside the Court, which is the trigger that
    used to re-enter setup. Checked against committed state after every step: the stored answer never changes, the
    aura never gains a second start trigger, and no Court question is ever put to anybody again.
    """
    combat, table, mid = _fight(tmp_path / "auto-once", control_modes=STEPPED_MODES)
    assert disease.court_choice_reactors(combat._load_session(mid).engine) == (), "no Court is standing yet"
    _raise_court(table, mid, state=_walk_to(table, combat, mid, WARDEN),
                 choose=lambda options: [o for o in options if o == PICKED])
    engine = _engine(combat, mid)
    answer = _allies_of(engine, _court_zone(engine))
    assert answer == [PICKED], answer
    assert WARDEN in disease.court_choice_reactors(engine), "the service does not enrol the Court's maker at all"

    committed, asked = 0, []
    for _ in range(30):
        state = table.state(mid)
        if state["menu"]["actor_id"] == WARDEN:
            _end_turn(table, mid, state, lambda prompt: asked.append(prompt) and None)
            continue
        result = combat.auto_step(mid)  # everyone else: the table steps it
        assert result.get("status") != "AWAITING_REACTION" or \
            (result.get("reaction_context") or {}).get("reaction_source_id") != COURT_CHOICE, result
        committed += 1 if result.get("status") == "COMMITTED" else 0
        engine = _engine(combat, mid)
        if not any(z.owner_id == WARDEN for z in disease._zones_of(engine, CRAWLING_KEY)):
            break  # the maker let its Court go; there is nothing left to protect
        assert _allies_of(engine, _court_zone(engine)) == answer, "stepping the fight overwrote the maker's answer"
        assert len(_start_triggers(engine, WARDEN)) == 1, f"the Court gained a second start trigger: {_start_triggers(engine, WARDEN)}"

    assert committed, "no Local Auto step committed anything: the fighters were not under AI control"
    assert not [p for p in asked if _court_questions(p)], "the maker was asked its Court choice again"
    engine = _engine(combat, mid)
    # the aura only ever carries the maker's one answer, however often it was republished as its maker moved
    assert set(_answers_on_the_aura(engine)) == {tuple(answer)}, _answers_on_the_aura(engine)
    # an enemy really did start a turn inside the Court while the table was stepping it
    assert any(e.event_type == "PASSIVE_TRIGGERED" and COURT in str(e.source_definition_id) and FOE in e.target_ids
               for e in engine.events), "stepping never reached an enemy turn start inside the Court"
    assert _session(combat, mid).verify()["status"] == "PASS"


def test_an_ai_maker_answers_its_court_choice_itself_and_keeps_it_while_the_table_steps(tmp_path):
    """Automatic selection on the AI-step path.

    Every fighter is under Local AI, so the fight really is being stepped by the table. When the maker's turn comes
    round, raising the Court answers "you and allies you choose" with no player present -- ``rider_choices.pick``
    answers it for the AI and stores every ally standing in the aura -- and the whole thing is committed through the
    service's own intent path and reloaded. Stepping then continues, and the answer the AI gave is never disturbed.

    The raise itself is submitted as the intent the maker's own legal candidates offer rather than left to the Local
    AI policy, because that policy does not select the Court in this fixture (measured: 90 committed steps, never
    raised). The choice routing, the storage and the commit are the production path either way.
    """
    from combat.gate2_runtime_models import ActionIntent

    # This checks a standing Court's stored choice, so compile a Constitution
    # modifier that passes the fixture's damage checks. A separate regression
    # retains the ordinary maker and checks that a failed save ends the Court.
    combat, table, mid = _fight(tmp_path / "ai-maker", control_modes=AI_MODES, stable_concentration=True)
    assert _step_until_actor(combat, mid, WARDEN), "the maker's own turn never came up under Local AI"

    session = combat._load_session(mid)
    assert WARDEN not in session.engine.typed_ask_reactors, "an AI maker must not be enrolled as a player to ask"
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == "Court of the Crawling Fever" and c.actor_id == WARDEN)
    session.submit_intent(ActionIntent(intent_id="auto89r2f1-court", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination),
                          primary_decision_record=None, reaction_provider=None)

    engine = _engine(combat, mid)
    zone = _court_zone(engine)
    stored = _allies_of(engine, zone)
    inside = [a.entity_id for a in engine.state.actors.values()
              if a is not engine.state.actors[WARDEN] and a.team_id == engine.state.actors[WARDEN].team_id
              and a.active and disease._inside(zone, a)]
    assert inside, "the fixture must put at least one ally inside the Court"
    assert sorted(stored) == sorted(inside), (stored, inside)
    for ally in inside:  # each one really keeps the printed benefits through a commit and reload
        assert disease.court_covers(_engine(combat, mid), _engine(combat, mid).state.actors[ally]) is True, ally
    assert disease.court_covers(engine, engine.state.actors[FOE]) is False  # an enemy is not an ally

    committed = 0
    for _ in range(12):
        if combat.auto_step(mid).get("status") == "COMMITTED":
            committed += 1
    assert committed, "stepping stopped after the AI answered its Court"
    engine = _engine(combat, mid)
    assert _allies_of(engine, _court_zone(engine)) == stored, "stepping the fight overwrote the AI maker's answer"
    assert engine.state.actors[WARDEN].concentration is not None
    assert len(_start_triggers(engine, WARDEN)) == 1, f"the Court gained a second start trigger: {_start_triggers(engine, WARDEN)}"
    assert set(_answers_on_the_aura(engine)) == {tuple(stored)}, _answers_on_the_aura(engine)
    assert _session(combat, mid).verify()["status"] == "PASS"


def test_an_ask_me_court_maker_stays_a_player_decision_while_the_table_steps_the_fight(tmp_path):
    """The player-owned decision stays the player's, and the AI never answers it.

    A maker whose sheet says "Ask me" is a player playing it, so the service enrols it as somebody to ask
    (``_ask_reactors``, which only enrols a fighter a player actually submits for) and asks it on its own turn --
    that is the same actor the AI-step probe consults. The Court is then standing while the table steps every other
    fighter: those AI steps must not raise the Court question again, must not answer it, and must not disturb the
    answer the player gave.
    """
    combat, table, mid = _fight(tmp_path / "ask-me-step", ask_maker=True, control_modes=STEPPED_MODES)
    asked = _raise_court(table, mid, state=_walk_to(table, combat, mid, WARDEN),
                         choose=lambda options: [o for o in options if o == PICKED])
    assert len(asked) == 1, asked
    assert asked[0]["reaction"] == "Court of the Crawling Fever", asked[0]
    engine = _engine(combat, mid)
    assert _allies_of(engine, _court_zone(engine)) == [PICKED]
    # the player playing the maker is enrolled as somebody the table must ask, even while it steps the fight
    assert WARDEN in combat._ask_reactors(combat._read_metadata(mid), combat._load_session(mid)), \
        "the Ask me maker is not enrolled as a player to ask"

    committed, during = 0, []
    for _ in range(24):
        state = table.state(mid)
        if state["menu"]["actor_id"] == WARDEN:
            _end_turn(table, mid, state, lambda prompt: during.append(prompt) and None)
            continue
        result = combat.auto_step(mid)
        committed += 1 if result.get("status") == "COMMITTED" else 0
        during.extend([result["reaction"]] if result.get("status") == "AWAITING_REACTION" else [])

    assert committed, "no Local Auto step committed anything: the fighters were not under AI control"
    assert not [p for p in during if (p.get("context") or {}).get("reaction_source_id") == COURT_CHOICE], \
        "the table put a fresh Court question to an Ask me player on an AI turn"
    engine = _engine(combat, mid)
    assert _allies_of(engine, _court_zone(engine)) == [PICKED], "stepping the fight overwrote the player's answer"
    assert len(_start_triggers(engine, WARDEN)) == 1, f"the Court gained a second start trigger: {_start_triggers(engine, WARDEN)}"
    assert _session(combat, mid).verify()["status"] == "PASS"
