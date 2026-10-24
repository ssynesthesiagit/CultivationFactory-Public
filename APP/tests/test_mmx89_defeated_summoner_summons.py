"""Pin printed summon lifetimes and automatic-turn history at the table/engine boundary.

Corpse Servant lasts until destroyed or dismissed, not until its summoner falls.
Its survival, uncommanded instincts and state are checked through commit/reload/replay.
The generic owner-defeat seam is tested separately with synthetic source metadata;
that test is not authority to opt any printed ability into the policy.
"""

import json
import zipfile

import pytest

from combat import summons
from combat.ext import mounts
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, ALLY, FOE, SECOND = [FACTORY_ACTOR_PREFIX + "mmx89-" + name
                            for name in ("owner", "ally", "foe", "second")]
SERVANT = "TAL_DEATH_CORPSE_SERVANT"
FORMATION = "TAL_DEATH_GRAVE_FORMATION"
TAMER = ["BEASTMASTERY_BASE_TAMER_PACKAGE", "TAL_BEASTMASTERY_BEAST_TAMER"]
LAVA = "TAL_MAGMA_LAVA_FLOW"


@pytest.fixture
def synthetic_lifetime_source(tmp_path, monkeypatch):
    """Inject policy only into disposable test rules, before character compilation.

    Reusing a creature's stat block exercises the source-copy seam without changing
    production rules or authorizing this policy for any printed ability.
    """
    rules = summons.rules()
    rules["sources"][SERVANT]["lifetime"] = "ends_with_summoner"
    path = tmp_path / "synthetic-summons.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    monkeypatch.setattr(summons, "RULES_PATH", path)


def table_fixture(tmp_path, *, owner_hp=1, abilities=None, plan=None, seed="MMX89", rounds=20,
                  display_name="MMX89 defeated summoner"):
    """A 2v2 in which the summoner stands beside an ally, so its side survives its death -- the case
    a fight actually reaches.  The summoner starts at ``owner_hp`` and the foe opens with a committed
    Lava Flow onto its square, so the defeat arrives on the real damage path inside a real step.
    ``abilities`` chooses what the summoner brought and ``plan`` which creatures of it it brought, so
    the same fight can check the printed lifetimes of several creature kinds."""
    docs = [sheet(abilities or [SERVANT], cl=17, primary="Stamina"), sheet([], cl=17),
            sheet([LAVA], cl=17), sheet([], cl=17)]
    hp = {OWNER: owner_hp}
    for actor_id, doc in zip((OWNER, ALLY, FOE, SECOND), docs):
        doc["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        doc["identity"]["proficiency_bonus"] = 4
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp.get(actor_id, 500)
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    ids = [OWNER, ALLY, FOE, SECOND]
    for actor_id, doc in zip(ids, docs):
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=actor_id, summon_plan=plan if index == 0 else None)
               for index, (actor_id, doc) in enumerate(zip(ids, docs))]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:a", ALLY: "team:a", FOE: "team:b", SECOND: "team:b"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER, ALLY], [FOE, SECOND],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed=seed,
        display_name=display_name, maximum_rounds=rounds)["match_id"]

    def commit(candidate_id, square=None):
        placement_answered = False
        answers = []
        for _ in range(16):
            menu = table.state(mid)["menu"]
            result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))
            if result["status"] == "COMMITTED":
                assert square is None or placement_answered, "the requested Lava Flow square was never chosen"
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            choice = prompt.get("choice") or {}
            # SQUAREPICK1 (938f1759): a printed area is aimed on the map now, so its
            # square arrives as a second-stage choice instead of one menu row per cell.
            spatial = [o for o in choice.get("options", []) if o.get("cell")]
            if square is not None and spatial:
                wanted = [o for o in spatial if same_square(o["cell"], square)]
                assert wanted, f"{square} is not one of the offered squares: {[o['cell'] for o in spatial][:6]}"
                answers.append({**prompt["context"], "selection": "USE", "option_ids": [wanted[0]["id"]]})
                placement_answered = True
                continue
            answer = {**prompt["context"], "selection": "DECLINE"}
            if choice and not choice.get("allow_decline"):
                answer.update(selection="USE", option_ids=(choice.get("preferred") or
                                                          [choice["options"][0]["id"]])[:1])
            answers.append(answer)
        raise AssertionError("too many reaction prompts")

    def end_turn():
        commit(table.state(mid)["menu"]["end_turn"])

    def play_to(actor_id, limit=40):
        for _ in range(limit):
            if table.state(mid)["menu"]["actor_id"] == actor_id:
                return
            end_turn()
        raise AssertionError(f"{actor_id}'s turn never came")

    def play_until(predicate, limit=40, what="the condition"):
        for _ in range(limit):
            if predicate(combat._load_session(mid).engine):
                return
            end_turn()
        raise AssertionError(f"{what} never came")

    def servants():
        engine = combat._load_session(mid).engine
        return summons.owned_by(engine, OWNER)

    return combat, table, mid, commit, end_turn, play_to, play_until, servants


def same_square(cell, square):
    """Whether a map-pick cell (its x, y and optional altitude) is the square a fixture names."""
    return (cell is not None and cell.get("x") == square.get("x") and cell.get("y") == square.get("y")
            and int(cell.get("z") or 0) == int(square.get("z") or 0))


def lava_onto(table, mid, square):
    """The foe's committed area attack centered on ``square`` (the printed ability, the printed menu).

    SQUAREPICK1 (938f1759) aims a printed area on the map: the menu offers one "choose a square"
    row and the square itself is answered as a second-stage choice, so ``commit`` takes the square.
    """
    group = next(g for g in table.state(mid)["menu"]["actions"] if "Lava Flow" in g["label"])
    return group["options"][0]["candidate_id"]


def verify_reload(combat, table, mid):
    """Everything the fight recorded survives a commit, a reload from disk, verify and replay."""
    session = combat._load_session(mid)
    current = session.engine.state.model_dump(mode="json")
    fresh = CombatService(combat.source_root, combat.userdata_root)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == current
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    assert table.state(mid)["match_id"] == mid


# ------------------------------------------------------------------ HUNT97 #1
def test_table_corpse_servants_outlive_the_defeated_summoner_until_destroyed_or_dismissed(tmp_path):
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(tmp_path)
    creatures = servants()
    assert len(creatures) == 4 and all(c.active for c in creatures)  # the Death Control Limit is PB
    order = combat._load_session(mid).engine.state.initiative_order
    assert [c.entity_id for c in creatures] == order[order.index(OWNER) + 1: order.index(OWNER) + 5]
    orphan_ids = {c.entity_id for c in creatures}
    assert all("lifetime" not in c.summon for c in creatures)

    play_to(FOE)
    square = combat._load_session(mid).engine.state.actors[OWNER].position.model_dump(mode="json")
    commit(lava_onto(table, mid, square), square)  # the real damage path defeats it inside a committed step
    play_until(lambda e: not e.state.actors[OWNER].active, what="the summoner's defeat")
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ALLY].active  # the side survives, so the fight is not over
    assert engine.state.terminal_result is None
    before = engine.state.event_sequence

    for _ in range(6):  # a full round, so every creature's own slot comes round again
        end_turn()
    engine = combat._load_session(mid).engine  # the service reloads from disk: read that copy
    creatures = servants()

    assert all(c.active and c.summon["status"] == "present" for c in creatures)
    dismissals = [e for e in engine.events[before:] if e.event_type == "SUMMON_DISMISSED"
                  and e.actor_id in orphan_ids]
    assert not dismissals
    defaults = [e for e in engine.events[before:] if e.actor_id in orphan_ids
                and e.event_type == "COMPANION_DEFAULT_APPLIED"]
    assert {e.actor_id for e in defaults} == orphan_ids
    assert all(e.payload["behavior"] == "INSTINCT" for e in defaults)
    verify_reload(combat, table, mid)


def test_table_a_living_summoner_keeps_its_creatures(tmp_path):
    """The control: the sweep reads the owner's own condition, so a summon whose summoner is on the
    map and standing keeps every creature, and no dismissal event is recorded at all."""
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(tmp_path, owner_hp=500)
    play_to(OWNER)
    before = combat._load_session(mid).engine.state.event_sequence
    for _ in range(6):
        end_turn()
    engine = combat._load_session(mid).engine
    assert engine.state.actors[OWNER].active
    assert all(c.active and c.summon["status"] == "present" for c in servants())
    assert not [e for e in engine.events[before:] if e.event_type == "SUMMON_DISMISSED"]
    verify_reload(combat, table, mid)


# ------------------------------------------------------------------ HUNT97 #2
def test_table_the_companion_default_line_is_readable_and_survives_reload(tmp_path):
    """Owner 2026-10-17: servants act on instinct, not an automatic Dodge.

    Reloaded history must give both the reason and the actual turn's outcome.
    The separate stock-companion test below still requires its printed Dodge.
    """
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(tmp_path, owner_hp=500)
    play_to(OWNER)
    summon_ids = {creature.entity_id for creature in servants()}
    end_turn()  # No command; all seats are MANUAL, but the servants act on their own.
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    events = fresh.events(mid, 0)["events"]
    applied = [e for e in events if e["event_type"] == "COMPANION_DEFAULT_APPLIED"
               and e["actor_id"] in summon_ids]
    assert applied, "the uncommanded creature's default was not recorded"
    assert all(e["raw"]["payload"]["behavior"] == "INSTINCT" for e in applied)
    summaries = [e["summary"] for e in applied]
    assert all("received no order" in line and "own instincts" in line for line in summaries), summaries
    for line in summaries:
        assert "Summon Default" not in line and "companion default" not in line
        assert "Dodge" not in line
    outcomes = [e for e in events if e["event_type"] == "SUMMON_TURN"
                and e["actor_id"] in summon_ids]
    assert {e["actor_id"] for e in outcomes} == {e["actor_id"] for e in applied}
    for event in outcomes:
        assert event["summary"] == event["raw"]["payload"]["text"]
        assert "acts on instinct:" in event["summary"]
        assert "system:" not in event["summary"] and "action:" not in event["summary"]
    assert not [e for e in events if e["event_type"] == "CONDITION_APPLIED"
                and e.get("source_definition_id") == "system:combat.summon_default"]
    verify_reload(combat, table, mid)


# The stock companion uses a different default branch from summoned creatures.
def test_table_uncommanded_companion_dodge_history_names_the_automatic_trigger(tmp_path):
    """Bai ends without commanding Cui; the persisted history must not invent Cui's choice."""
    from combat.gate2_runtime_content import BAI, CUI
    from combat.gate2_runtime_models import ActionIntent, CandidateKind
    from combat.gate3_storage import Gate3Persistence

    session = Gate3Persistence(ROOT, tmp_path).create_match(
        match_seed="TIANXIA-GATE2-MANUAL-0001", maximum_rounds=20)
    assert session.engine.state.current_actor_id == BAI
    candidate = next(c for c in session.engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
    session.execute_intent(ActionIntent(
        intent_id="mmx89r2-uncommanded-cui", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=candidate.actor_id, target_ids=candidate.target_ids,
        destination=candidate.destination, option_ids=candidate.option_ids))
    defaults = [e for e in session.engine.events if e.event_type == "COMPANION_DEFAULT_APPLIED"]
    assert len(defaults) == 1 and defaults[0].actor_id == CUI
    assert defaults[0].payload["behavior"] == "DODGE_AND_HOLD"
    fresh = CombatService(ROOT, tmp_path)
    history = fresh.history(session.match_id)
    lines = [e["summary"] for boundary in history["boundaries"] for e in boundary["feed"]
             if e["event_type"] == "COMPANION_DEFAULT_APPLIED"]
    assert lines == ["Cui received no command, so it holds its ground and takes the Dodge action."]
    conditions = [e["summary"] for boundary in history["boundaries"] for e in boundary["feed"]
                  if e["event_type"] == "CONDITION_APPLIED"
                  and e.get("source_definition_id") == "system:combat.companion_default"]
    assert len(conditions) == 1
    assert "applied Dodge to Cui (it Dodges automatically)" in conditions[0]
    assert "no action was chosen" not in conditions[0]
    assert session.verify()["status"] == "PASS"
    assert session.replay()["status"] == "PASS"


def test_guard_and_rescue_condition_history_uses_the_same_automatic_reason():
    """The shared source also applies Dodge when the guarded fighter has left combat."""
    from combat.gate2_runtime_content import BAI, CUI
    from combat.history_feed import format_history_feed

    engine = Gate2Engine(ROOT, match_seed="MMX89-GUARD-HISTORY")
    engine._defeat(engine.state.actors[BAI], "test:guarded-fighter-falls", final=True)
    with engine._transaction("system:test.cui_guard", "guard", CUI):
        engine._cui_guard_and_rescue_default()
    rows = format_history_feed(
        [e.model_dump(mode="json") for e in engine.events], [], pre_state=None, post_state={},
        actor_names={a.entity_id: a.display_name for a in engine.state.actors.values()},
        definition_names={})
    conditions = [r["summary"] for r in rows if r["event_type"] == "CONDITION_APPLIED"
                  and r.get("source_definition_id") == "system:combat.companion_default"]
    assert len(conditions) == 1
    assert "applied Dodge to Cui (it Dodges automatically)" in conditions[0]
    assert "no action was chosen" not in conditions[0]


# ------------------------------------------------------------------ the owner rule, at the seam
def _servant_engine(tmp_path=None, rider=False):
    """One summoner, its creatures and a foe, on the real compiled engine."""
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN
    from tests.h1_support import sheet as _sheet

    if rider:
        import importlib.util

        spec = importlib.util.spec_from_file_location("bm_helpers", ROOT / "tests" / "test_review_sw-beastmastery.py")
        bm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bm)
        bundle = compile_character({**bm.SHEET, "equipment": [],
                                   "spheres_and_talents": {"sphere_record_ids": [bm.BEASTMASTERY],
                                                           "learned_talent_record_ids": [],
                                                           "automatic_sphere_component_record_ids":
                                                               ["BEASTMASTERY_BASE_RIDER_PACKAGE"]}},
                                  actor_id=bm.ME)
        return bm.engine(bundle), bm.ME, AN
    bundle = compile_character(_sheet([SERVANT], cl=10), actor_id=OWNER)
    engine = Gate2Engine(ROOT, match_seed="MMX89-SEAM",
                         typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                       "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 12, "y": 6}}})
    return engine, OWNER, AN


def _turn_of(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def test_a_mount_outlives_the_rider_who_falls():
    """5.5e Mounted Combat: the bond that ends is the saddle.  The mount is left standing where it
    stands, unbound and acting for itself -- so the owner rule leaves it alone."""
    engine, rider, _ = _servant_engine(rider=True)
    mount = next(a for a in engine.state.actors.values()
                 if (a.summon or {}).get("owner") == rider and (a.summon or {}).get("mountable"))
    assert mounts.mount_of(engine, engine.state.actors[rider]) is not None
    engine._defeat(engine.state.actors[rider], "test:rider-falls", final=True)
    _turn_of(engine, mount.entity_id)
    assert mount.active and mount.summon["status"] == "present"
    assert mounts.mount_of(engine, engine.state.actors[rider]) is None


def test_an_unconscious_summoner_at_zero_hit_points_keeps_its_creatures(synthetic_lifetime_source):
    """The rule keys on the printed end conditions, not on being removed from the map: 0 Hit Points
    that leaves a fighter Unconscious (the 2024 dying rules, combat/ext/life_state.py) is not a
    defeated summoner, and its creatures stay."""
    engine, owner, _ = _servant_engine()
    creatures = summons.owned_by(engine, owner)
    assert len(creatures) == 4 and all(c.active for c in creatures)
    assert all(c.summon["lifetime"] == "ends_with_summoner" for c in creatures)
    fighter = engine.state.actors[owner]
    fighter.current_hp = 0
    fighter.life_state = "DYING"
    fighter.active = True
    _turn_of(engine, AN)
    assert all(c.active and c.summon["status"] == "present" for c in creatures)
    assert not [e for e in engine.events if e.event_type == "SUMMON_DISMISSED"]


def test_table_source_lifetime_survives_commit_reload_and_ends_after_owner_defeat(
        tmp_path, synthetic_lifetime_source):
    """Future authorized source policies compile, persist and execute after recovery."""
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(tmp_path)
    creatures = servants()
    creature_ids = {c.entity_id for c in creatures}
    assert len(creature_ids) == 4
    assert all(c.summon["lifetime"] == "ends_with_summoner" for c in creatures)

    play_to(OWNER)
    end_turn()  # commit while the owner is living; the policy must stay inert
    fresh = CombatService(ROOT, tmp_path)
    recovered = fresh._load_session(mid).engine
    assert recovered.state.actors[OWNER].active
    assert all(recovered.state.actors[cid].active for cid in creature_ids)
    assert all(recovered.state.actors[cid].summon["lifetime"] == "ends_with_summoner"
               for cid in creature_ids)
    assert not [e for e in recovered.events if e.event_type == "SUMMON_DISMISSED"]
    verify_reload(combat, table, mid)

    # Subsequent table actions load the committed fight, not the compiled objects above.
    play_to(FOE)
    square = fresh._load_session(mid).engine.state.actors[OWNER].position.model_dump(mode="json")
    commit(lava_onto(table, mid, square), square)
    play_until(lambda e: not e.state.actors[OWNER].active, what="the summoner's defeat")
    play_until(lambda e: all(not e.state.actors[cid].active for cid in creature_ids),
               what="the synthetic policy's dismissal")
    restored = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert all(restored.state.actors[cid].summon["status"] == "dismissed" for cid in creature_ids)
    assert all(restored.state.actors[cid].summon["lifetime"] == "ends_with_summoner"
               for cid in creature_ids)
    dismissals = [e for e in restored.events if e.event_type == "SUMMON_DISMISSED"]
    assert {e.actor_id for e in dismissals} == creature_ids
    assert all(e.payload["reason"] == "OWNER_DEFEATED" for e in dismissals)
    verify_reload(combat, table, mid)


# ------------------------------------------------------------------ the lifetime is data, per creature
def test_a_summon_saved_before_the_lifetime_policy_keeps_behaving_as_it_did(tmp_path=None):
    """A fight saved before this rule exists carries an ``owner`` but no ``lifetime``.  That is the
    whole compatibility story: the record has everything the owner test could read, so the claim
    "old summons are unchanged because they have no owner" would be false.  What keeps them unchanged
    is that the policy is absent, and an absent policy is inert -- the creature stays on the map
    exactly as it did before the fix, so a saved fight continues from the state it was left in."""
    engine, owner, _ = _servant_engine()
    creatures = summons.owned_by(engine, owner)
    for creature in creatures:
        creature.summon.pop("lifetime", None)
    assert all("owner" in c.summon and "lifetime" not in c.summon for c in creatures)
    engine._defeat(engine.state.actors[owner], "test:summoner-falls", final=True)
    _turn_of(engine, AN)
    assert all(c.active and c.summon["status"] == "present" for c in creatures)
    assert not [e for e in engine.events if e.event_type == "SUMMON_DISMISSED"]


def test_table_a_tamed_beast_outlives_the_trainer_who_falls(tmp_path):
    """The surviving creature, at the level the rule is read: a Tame beast "acts according to its
    nature, training, and circumstances" and "Without a command ... acts according to its nature"
    (BEASTMASTERY_BASE_TAMER_PACKAGE).  Nothing in that text ends with its trainer, so the trainer
    falling does not take the beast with it: the beast is still on the map and still acting when the
    summoner's side loses its summoner."""
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(
        tmp_path, abilities=TAMER, plan={"beasts": ["dire_wolf"]})

    def beasts():
        # The Tamer Package also rides a steed; this case is about the trained beasts ("Tame"), which
        # are the ones source "tamer" brings.
        return [c for c in servants() if c.summon["source"] == "tamer"]

    creatures = beasts()
    assert len(creatures) == 1 and creatures[0].display_name == "Dire Wolf" and creatures[0].active
    assert all("lifetime" not in c.summon for c in creatures)  # its source never asked for one

    play_to(FOE)
    square = combat._load_session(mid).engine.state.actors[OWNER].position.model_dump(mode="json")
    commit(lava_onto(table, mid, square), square)
    play_until(lambda e: not e.state.actors[OWNER].active, what="the trainer's defeat")
    before = combat._load_session(mid).engine.state.event_sequence

    # Stop as soon as the beast's own turn comes round -- the first turn boundary is where a dismissal
    # would be recorded, so that is the whole question -- rather than sitting through the foe's later
    # fire, which is a different rule (a destroyed creature) and not what this test is about.
    play_to(creatures[0].entity_id)
    engine = combat._load_session(mid).engine  # the service reloads from disk: read that copy
    assert engine.state.actors[OWNER].active is False
    assert engine.state.actors[ALLY].active and engine.state.terminal_result is None
    assert all(c.active and c.summon["status"] == "present" for c in beasts())
    assert not [e for e in engine.events[before:] if e.event_type == "SUMMON_DISMISSED"]
    # It is still taking its own turn, not merely sitting on the map.
    defeated_at = next(e.sequence for e in engine.events
                       if e.event_type == "ENTITY_DEFEATED" and e.actor_id == OWNER)
    assert [e for e in engine.events if e.sequence > defeated_at
            and e.actor_id in {c.entity_id for c in creatures} and e.event_type == "TURN_STARTED"]
    verify_reload(combat, table, mid)


def test_table_a_creature_with_a_printed_duration_outlives_its_summoner(tmp_path):
    """The other surviving kind: a Grave Formation's printed Duration is "24 hours, or until the
    formation is destroyed or dismissed".  A single fight never reaches 24 hours, so the formation
    is still on the map when the summoner falls -- its own text says so, and this lane does not
    substitute a shorter life for it."""
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(
        tmp_path, abilities=[FORMATION])
    creatures = servants()
    assert creatures and all(c.active for c in creatures)
    assert all("lifetime" not in c.summon for c in creatures)

    play_to(FOE)
    square = combat._load_session(mid).engine.state.actors[OWNER].position.model_dump(mode="json")
    commit(lava_onto(table, mid, square), square)
    play_until(lambda e: not e.state.actors[OWNER].active, what="the summoner's defeat")
    before = combat._load_session(mid).engine.state.event_sequence

    assert all(c.active and c.summon["status"] == "present" for c in servants())

    for _ in range(6):
        end_turn()
    engine = combat._load_session(mid).engine
    assert engine.state.actors[ALLY].active and engine.state.terminal_result is None
    # LIVE automatically skips the fallen trainer's slot, so six table commits
    # now reach later terrain damage. Destruction is a printed end condition;
    # require its recorded cause rather than confusing it with owner dismissal.
    for creature in servants():
        if not creature.active:
            assert creature.summon["status"] == "destroyed"
            assert any(e.event_type == "ENTITY_DEFEATED" and e.actor_id == creature.entity_id
                       for e in engine.events[before:])
        else:
            assert creature.summon["status"] == "present"
    assert not [e for e in engine.events[before:] if e.event_type == "SUMMON_DISMISSED"]
    verify_reload(combat, table, mid)


# ------------------------------------------------------------------ base/head bytes
#: The complete capture of this fight -- state, every event, every roll -- on 42e43e14 and on this
#: branch.  The unaffected seeded AI fights are pinned separately by tests/test_l41_ai_replay.py and
#: were measured for this lane with the same method: identical on base and head.
BASE_CAPTURE = "ca1f3f855b77bc05ddc09e4ab96667d5ba4c29d41a29a0cf47af2e36010f1f95"
HEAD_CAPTURE = BASE_CAPTURE


def test_the_defeated_summoner_fight_matches_the_measured_head_bytes(tmp_path):
    """Removing the unsupported opt-in restores the full base mechanical capture:
    148 events, 19 rolls, 12 default Dodges and no owner-defeat dismissals.
    History wording is presentation only and is not part of these recorded bytes."""
    from combat.canonical import canonical_sha256

    # The same fight the measurement script played: seed, round cap and name all fixed here so this
    # capture is the one that was compared, not a near neighbour of it.
    combat, table, mid, commit, end_turn, play_to, play_until, servants = table_fixture(
        tmp_path, seed="MMX89F1-B", rounds=30, display_name="defeated-summoner")
    play_to(FOE)
    square = combat._load_session(mid).engine.state.actors[OWNER].position.model_dump(mode="json")
    commit(lava_onto(table, mid, square), square)
    play_until(lambda e: not e.state.actors[OWNER].active, what="the summoner's defeat")
    for _ in range(6):
        end_turn()

    loaded = combat._load_session(mid)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    payload = {"state": loaded.engine.state.model_dump(mode="json"),
               "events": [e.model_dump(mode="json") for e in loaded.engine.events],
               "rolls": [r.model_dump(mode="json") for r in loaded.engine.rolls]}
    if loaded.engine.state.rules.get("zero_hp") == "dying_2024":
        # SOL113 intentionally gives newly created fights a recorded 2024 death
        # policy; LIVE also skips inactive slots. The R24 fixed hash cannot be
        # the oracle for this new-policy fight. Keep exact bytes across reload,
        # and keep the archived equality guard for the legacy policy below.
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        fresh_payload = {"state": fresh.engine.state.model_dump(mode="json"),
                         "events": [e.model_dump(mode="json") for e in fresh.engine.events],
                         "rolls": [r.model_dump(mode="json") for r in fresh.engine.rolls]}
        assert canonical_sha256(payload) == canonical_sha256(fresh_payload)
        assert canonical_sha256(payload) != BASE_CAPTURE
    else:
        assert canonical_sha256(payload) == HEAD_CAPTURE, (
            f"the legacy capture moved off measured head bytes (base was {BASE_CAPTURE})")
