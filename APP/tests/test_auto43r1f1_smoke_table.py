"""AUTO43r1: the Smoke Veil's printed lines through the real table -- preview, commit, disk reload, replay.

Checklist item 7 asks for a *table commit and reload*, not a serialisation of the model in a test's own hands: a
fight's stored state has to come back from disk through the real service, verify, and replay. Checklist item 9 asks
who is asked a decision -- a player at the table, or an AI acting for itself -- and that is the service's boundary,
so it is driven here through ``TabletopService`` and ``CombatService`` with real control modes. Checklist item 13 asks
for player-facing words, so the prompts are read as the table renders them rather than as the plug-in wrote them.

The abilities used here are the ones the review named: the Second Veil's placement question (a map choice, with labels a
player who knows only basic D&D can act on) and Blacken the Flame (a Reaction to Fire damage that names the action which
caused it, the creature it caught, and both costs).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from combat.ext import smoke_veil
from combat.ext.fight_ownership import block_rows
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark
from tests.h1_support import ROOT, sheet

OWNER = FACTORY_ACTOR_PREFIX + "r1f1-owner"
FOE = FACTORY_ACTOR_PREFIX + "r1f1-foe"
VEIL, SECOND, BLACKEN = "SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_SECOND_VEIL", "TAL_SMOKE_BLACKEN_THE_FLAME"
BASES = ["SMOKE_BASE_SMOKE_RESPONSES", "SMOKE_BASE_SMOKE_TRACE"]
BURN_THROUGH = "FIRE_TAL_BURN_THROUGH"


def _fight(tmp_path, talents, *, seed="R1F1-TABLE", cl=11, secondary=FACTORY_ACTOR_PREFIX + "r1f1-second",
           positions=None, arena=None):
    """A real table match: three real fighters, portable characters on disk, the owner's turn opened."""
    ids = [OWNER, FOE, secondary]
    documents = [sheet([VEIL, *BASES, *talents], cl=cl, dc=50, primary="Stamina"),
                 sheet([], cl=cl, primary="Stamina"), sheet([], cl=cl, primary="Stamina")]
    for actor_id, document in zip(ids, documents):
        document["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 300
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        import zipfile

        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", __import__("json").dumps(document))
    bundles = [compile_character(document, actor_id=actor_id, reaction_plan={"ask": True} if actor_id == OWNER else None)
               for actor_id, document in zip(ids, documents)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:a", FOE: "team:b", secondary: "team:b"},
        positions or {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, secondary: {"x": 5, "y": 6}},
        arena or combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [FOE, secondary],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed=seed,
        display_name="AUTO43r1f1 table regression", maximum_rounds=8)["match_id"]
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            break
        assert _commit(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    return combat, table, mid


def _answer(prompt, *, take=False, first=True):
    if take:
        options = prompt["choice"]["options"]
        answer = {**prompt["context"], "selection": "USE",
                  "option_ids": ([options[0]["id"]] if first else [options[-1]["id"]])}
    else:
        answer = {**prompt["context"], "selection": "DECLINE"}
    return answer


def _commit(table, mid, candidate_id, *, take=False, first=True, limit=12):
    """Commit one action through the real table, answering whatever it asks the way a player would."""
    for _ in range(limit):
        state = table.state(mid)
        result = table.act(mid, candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"])
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        result = table.act(mid, candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"], [_answer(result["reaction"], take=take, first=first)])
        if result["status"] == "COMMITTED":
            return result
    raise AssertionError("the table never committed")


def _veil_candidate(table, mid, *, at=None):
    # The service now lazily offers one square picker. These fixture setups
    # submit an exact native aim (still revalidated by table.act) so the
    # subsequent Second Veil/reaction assertions retain their original scope.
    engine = table.combat._load_session(mid).engine
    aim = at or {"x": 4, "y": 6}
    for option in engine.legal_candidates():
        if ("Smoke Veil" in option.display_name and option.destination is not None
                and option.destination.x == aim["x"] and option.destination.y == aim["y"]):
            return option.candidate_id
    raise AssertionError(f"Smoke Veil is not on the table{f' aimed at {at}' if at else ''}")


def _asked_for(table, mid, candidate_id, *, take=False, first=True):
    """Commit, and return the choice prompts the table put to the player on the way."""
    seen = []
    for _ in range(12):
        state = table.state(mid)
        result = table.act(mid, candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"])
        if result["status"] == "COMMITTED":
            return seen
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        if prompt.get("choice"):
            seen.append(prompt)
        result = table.act(mid, candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"], [_answer(prompt, take=take, first=first)])
        if result["status"] == "COMMITTED":
            return seen
    raise AssertionError("the table never committed")


def test_the_second_veil_survives_a_table_commit_and_a_reload_from_disk(tmp_path):
    """Checklist item 7: what the area stores is read back off disk through the real service, verifies, and replays.

    The block count, the run's direction, the second veil's own squares and the density all come back, and the fight
    still passes the engine's own verification and its mechanical replay -- the checks a saved fight has to pass."""
    combat, table, mid = _fight(tmp_path, [SECOND], cl=11)
    _commit(table, mid, _veil_candidate(table, mid), take=True, first=False)
    live = {zone_id: (zone.center.model_dump(), tuple(sorted((c.x, c.y) for c in zone.affected_cells)),
                      zone.trigger_profile.get("size_ft"), zone.trigger_profile.get("blocks"),
                      zone.trigger_profile.get("obscured"), bool(zone.trigger_profile.get("second_veil")))
            for zone_id, zone in combat._load_session(mid).engine.state.zones.items()}
    assert live, "the veil was not created"
    assert any(size for *_, size, blocks, _, second in live.values() if second), \
        "a CL 11 second veil is a 10-foot cube: " + repr(live)

    fresh = CombatService(ROOT, tmp_path)._load_session(mid)  # a new service, reading the fight from disk
    reloaded = {zone_id: (zone.center.model_dump(), tuple(sorted((c.x, c.y) for c in zone.affected_cells)),
                          zone.trigger_profile.get("size_ft"), zone.trigger_profile.get("blocks"),
                          zone.trigger_profile.get("obscured"), bool(zone.trigger_profile.get("second_veil")))
                for zone_id, zone in fresh.engine.state.zones.items() if zone_id in live}
    assert reloaded == live, f"a reloaded fight covers different squares: {live} != {reloaded}"
    assert fresh.verify()["status"] == "PASS", fresh.verify()
    assert fresh.mechanical.replay()["status"] == "PASS", fresh.mechanical.replay()


def test_the_second_veils_question_arrives_as_a_map_a_player_can_point_at(tmp_path):
    """Checklist items 9 and 13: the owner is asked, in words a player who knows only basic D&D can act on.

    The prompt says what the cube is, how far it may go, what it costs (its Concentration, shared with the first
    veil) and how to decline; the options are the table's own point-to-place squares, each named in compass words
    rather than map numbers."""
    combat, table, mid = _fight(tmp_path, [SECOND], cl=11)
    asked = _asked_for(table, mid, _veil_candidate(table, mid), take=True, first=False)
    assert asked, "the table never put the placement question to its player"
    prompt = next(p for p in asked if p.get("choice") and p["choice"].get("options"))
    said = str(prompt.get("moment") or "")
    assert "Second Veil" in said, said
    assert "30 feet" in said, f"the printed reach must be stated: {said}"
    assert "10 feet on a side" in said, f"the printed size must be stated: {said}"
    assert "Concentration" in said, f"what it costs must be stated: {said}"
    assert "Decline" in said, f"how to decline must be stated: {said}"
    choices = prompt["choice"]
    assert choices.get("space_map"), "the table must offer the map, not a bare list"
    assert all(option.get("cell") for option in choices["options"]), "every option must carry its square"
    named = [str(option.get("label") or "") for option in choices["options"]]
    assert named and all(word in " ".join(named) for word in ("east", "west", "north", "south")), \
        f"the squares must be described in compass words: {sorted(named)[:4]}"
    assert not any(any(character.isdigit() and "," in name for character in name) for name in named), \
        f"map coordinates are an internal id a player cannot use: {sorted(named)[:4]}"
    assert len(set(named)) == len(named), f"two squares are offered under one description: {sorted(named)[:4]}"


# ==================================================================== checklist item 9: who the table asks
# A three-fighter fixture in which every step is the shipped one: the owner's veil and its Smoke Trace are committed
# through the table, and the Fire comes from a *submitted typed Fire ability* the AI fighter owns
# (FIRE_TAL_BURN_THROUGH), not from a hand-made damage packet. The positions put both other fighters inside the veil
# the owner aims at 4,6, and the fixed seed settles initiative as owner -> attacker -> victim, so the AI's fire lands
# in the same round the veil was made in.
ATTACKER = FACTORY_ACTOR_PREFIX + "r2f1-attacker"
VICTIM = FACTORY_ACTOR_PREFIX + "r2f1-victim"
ATTACK_SEED = "AUTO43r2f1"  # a fixed seed, so initiative is owner -> attacker -> victim every run (asserted below)
VEIL_AIM = {"x": 4, "y": 6}
POSITIONS = {OWNER: {"x": 3, "y": 6}, VICTIM: {"x": 4, "y": 6}, ATTACKER: {"x": 5, "y": 6}}


def _portable_character(tmp_path, actor_id, document):
    """The same portable character on disk the other cases in this file build, so a reloaded fight is a real one."""
    folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True, exist_ok=True)
    import zipfile

    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))


def _fire_fight(tmp_path, *, owner_mode="MANUAL", owner_ask=True, self_target=False):
    """The owner's Smoke Veil over the AI's target, with a Smoke Trace on one of them: the printed Blacken the Flame
    trigger, on the table, in whichever control modes the case under test needs.

    ``owner_mode`` "MANUAL" is a player at the table and "LOCAL_AUTO" a fighter the computer acts for. ``owner_ask`` is
    the owner's own Ask me switch for *reactions* (combat/typed_reactions.py ``_asking``); Blacken the Flame is a
    choice rather than a typed reaction, so whether it is asked is decided on its own account -- which is exactly what
    the no-Ask-me half of the case below is about.
    """
    ids = [OWNER, VICTIM, ATTACKER]
    documents = [sheet([VEIL, *BASES, BLACKEN], cl=11, dc=50, primary="Stamina"),
                 sheet([], cl=11, primary="Stamina"), sheet([BURN_THROUGH], cl=11, primary="Stamina")]
    for actor_id, document in zip(ids, documents):
        document["identity"]["display_name"] = actor_id.removeprefix(FACTORY_ACTOR_PREFIX).rsplit("-", 1)[-1].title()
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 300
        _portable_character(tmp_path, actor_id, document)
    bundles = [compile_character(document, actor_id=actor_id,
                                 reaction_plan={"ask": True} if (actor_id == OWNER and owner_ask) else None)
               for actor_id, document in zip(ids, documents)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:a", VICTIM: "team:a", ATTACKER: "team:b"},
        ({**POSITIONS, OWNER: POSITIONS[VICTIM], VICTIM: {"x": 5, "y": 7}} if self_target else POSITIONS),
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER, VICTIM], [ATTACKER],
        control_modes={OWNER: owner_mode, VICTIM: "MANUAL", ATTACKER: "LOCAL_AUTO"},
        match_seed=ATTACK_SEED, display_name="AUTO43r2f1 decision routing", maximum_rounds=8)["match_id"]
    order = combat._load_session(mid).engine.state.initiative_order
    assert order == [OWNER, ATTACKER, VICTIM], f"this fixture needs the owner's turn before the AI attacks: {order}"
    return combat, table, mid


def _candidate(table, mid, label):
    for group in table.state(mid)["menu"]["actions"]:
        for option in group["options"]:
            if label in str(option.get("label") or ""):
                return option["candidate_id"]
    raise AssertionError(f"{label!r} is not on the table")


def _veil_and_trace(table, mid):
    """The owner's printed setup, committed through the table: the Smoke Veil over both other fighters, then one Smoke
    Trace, then the end of the owner's turn so the AI acts. ``Place Smoke Trace`` is combat/ext/ironclad_smoke.py's own
    free action for the printed trace placement, so nothing here writes the fight's state by hand.

    Returns which creature carries the trace: the printed cost is "Spend one Smoke Trace on the source, target, or
    affected space", so either of them is a legal bearer and the table's target order is not part of the rules.
    """
    state = table.state(mid)
    assert state["menu"]["actor_id"] == OWNER, f"the owner must act first: {state['menu']}"
    _commit(table, mid, _veil_candidate(table, mid, at=VEIL_AIM))
    _commit(table, mid, _candidate(table, mid, "Place Smoke Trace"), take=True)
    engine = table.combat._load_session(mid).engine
    veil = next(iter(smoke_veil.veils(engine, engine.state.actors[OWNER])), None)
    assert veil is not None, "the printed Smoke Veil was not created"
    covered = {(cell.x, cell.y) for cell in veil.affected_cells}
    for who in (VICTIM, ATTACKER):
        creature = engine.state.actors[who]
        assert (creature.position.x, creature.position.y) in covered, \
            f"{who} must stand inside the veil for the printed trigger: {sorted(covered)}"
    bearer = next((who for who in (ATTACKER, VICTIM)
                   if bears_mark(engine.state.actors[who], OWNER, "Smoke Trace")), None)
    assert bearer, "'Spend one Smoke Trace on the source, target, or affected space' -- none of them carries one"
    _commit(table, mid, table.state(mid)["menu"]["end_turn"])  # the owner's turn ends; the AI acts next
    assert table.state(mid)["menu"]["actor_id"] == ATTACKER, f"the AI must be the one acting: {table.state(mid)['menu']}"
    return bearer


def _ai_fire(combat, table, mid, monkeypatch, *, target=VICTIM):
    """One AI step in which the AI fighter uses its own compiled Fire ability on the victim.

    Everything is the shipped path -- ``TabletopService.auto_step`` -> ``CombatService.local_step`` -> the real
    controller -- except which action the AI picks: the generic policy scores a reposition above an attack in this
    fixture, which would test a walking AI instead of the decision being asked about.
    tests/test_critical_damage_reactions.py steers it the same way for the same reason.
    """
    original = combat.controller.choose_primary_action

    def choose(context):
        choice = original(context)
        picked = [c for c in context.legal_candidates if c.actor_id == ATTACKER
                  and "Burn Through" in c.display_name and target in (c.target_ids or ())]
        if not picked:
            return choice
        want = picked[0]
        return choice.model_copy(update={
            "intent": choice.intent.model_copy(update={"candidate_id": want.candidate_id, "target_ids": want.target_ids,
                                                       "option_ids": want.option_ids, "destination": want.destination}),
            "record": choice.record.model_copy(update={"selected_candidate_id": want.candidate_id,
                                                       "selected_option_ids": want.option_ids})})

    monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
    state = table.state(mid)
    assert state["menu"]["control_mode"] == "LOCAL_AUTO", state["menu"]
    return table.auto_step(mid, state["last_sequence"])


def _soot_prompt(result):
    """The Blacken the Flame question as the table puts it on the page, or None."""
    prompt = result.get("reaction") or {}
    return prompt if "Blacken the Flame" in str(prompt.get("moment") or "") else None


def _use(prompt):
    return {**prompt["context"], "selection": "USE", "option_ids": [prompt["choice"]["options"][0]["id"]]}


def _controller_reactions(combat, mid):
    """Every reaction decision this fight's own controller journal recorded, read back off disk."""
    path = Path(combat._load_session(mid).controller_journal_path)
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return [record for row in rows for record in (row.get("reaction_decision_records") or [])]


@pytest.mark.parametrize("owner_ask", [True, False], ids=["ask_me", "auto_reactions"])
def test_the_table_asks_a_manual_owner_to_blacken_fire_the_ai_deals(tmp_path, monkeypatch, owner_ask):
    """Checklist item 9: a player's decision is asked, including on somebody else's turn.

    The AI fighter's own typed Fire ability catches the victim inside the owner's Smoke Veil. On an AI turn the service
    resolves the action somewhere else -- it runs the action on a throwaway copy first, to discover player-owned
    prompts -- so this is the case where a player-owned choice is easiest to lose: nothing may be committed, the fight
    must wait, and the table must put the question to its player. ``owner_ask`` is the owner's Ask me switch for
    *reactions*; Blacken the Flame is a choice, so it is asked either way (the second half is the point).
    """
    combat, table, mid = _fire_fight(tmp_path, owner_ask=owner_ask)
    bearer = _veil_and_trace(table, mid)
    before = combat._load_session(mid).engine.state.actors[VICTIM].current_hp

    result = _ai_fire(combat, table, mid, monkeypatch)
    assert result["status"] == "REACTION_REQUIRED", \
        f"a player-owned decision must be asked, not answered on the player's behalf (ask_me={owner_ask}): {result['status']}"
    prompt = _soot_prompt(result)
    assert prompt, f"the table must put Blacken the Flame to its player: {result.get('reaction')}"
    said = str(prompt["moment"])
    assert "Blacken the Flame" in said, said
    assert "Burn Through" in said, f"the prompt must name the action that dealt the fire: {said}"
    assert "Victim" in said, f"the prompt must name the creature that caught the fire: {said}"
    assert "Fire" in said, said
    assert "3d6 + 2" in said, f"the prompt must state the reduction this CL 11 owner gives: {said}"
    assert "Reaction" in said and "Smoke Trace" in said, f"the prompt must state both costs it pays: {said}"
    assert "Decline" in said, f"the prompt must state how to decline: {said}"
    assert [option["id"] for option in prompt["choice"]["options"]] == ["blacken"], prompt["choice"]

    # Nothing is committed while the question is open: the attack is parked, not lost.
    parked = combat._load_session(mid).engine
    assert parked.state.actors[VICTIM].current_hp == before, "the damage must not land before the player answers"
    assert bears_mark(parked.state.actors[bearer], OWNER, "Smoke Trace"), "nor may the Smoke Trace be spent"
    assert parked.state.actors[OWNER].reaction_available, "nor may the owner's Reaction be spent"

    resumed = table.auto_step(mid, table.state(mid)["last_sequence"], [_use(prompt)])
    assert resumed["status"] == "COMMITTED", resumed["status"]
    after = combat._load_session(mid).engine
    cuts = [roll for roll in after.rolls if roll.reason == "DAMAGE_REDUCED"]
    assert cuts and len(cuts[0].dice) == 3 and cuts[0].modifier == 2, \
        f"CL 11 with a +2 key ability modifier reduces by the printed 3d6 + 2: {cuts}"
    assert after.state.actors[VICTIM].current_hp < before
    assert not bears_mark(after.state.actors[bearer], OWNER, "Smoke Trace"), \
        "'Spend one Smoke Trace on the source, target, or affected space'"
    assert not after.state.actors[OWNER].reaction_available, "Blacken the Flame is a Reaction, so it spends one"
    assert any("smoke_blacken_the_flame" in json.dumps(row, default=str) for row in _controller_reactions(combat, mid)), \
        "the player's answer must be recorded in the fight's own controller journal"


def test_an_ai_owner_answers_blacken_for_itself_and_never_waits_for_a_player(tmp_path, monkeypatch):
    """Checklist item 9, the other half: an AI fighter decides for itself, and the fight never waits for a player.

    The same fight, with the owner switched to Local Auto through the service's own control-mode call. Its setup is
    committed first while it is still a manual fighter, so the only thing under test is who answers the question when
    the action belongs to somebody else: the AI controller, in the fight's own journal, spending nothing on a decline.
    """
    combat, table, mid = _fire_fight(tmp_path)
    bearer = _veil_and_trace(table, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    assert OWNER not in combat._load_session(mid).engine.typed_ask_reactors, \
        "an auto fighter must never be enrolled as a player to ask, or an AI step would stall on a human"

    result = _ai_fire(combat, table, mid, monkeypatch)
    assert result["status"] == "COMMITTED", f"an AI's step must not wait for a player: {result['status']}"
    after = combat._load_session(mid).engine
    assert not [roll for roll in after.rolls if roll.reason == "DAMAGE_REDUCED"], \
        "the shipped controller declines an automatic choice (combat/gate4_controller.py choose_reaction)"
    assert bears_mark(after.state.actors[bearer], OWNER, "Smoke Trace"), "a declined answer spends no Smoke Trace"
    assert after.state.actors[OWNER].reaction_available, "a declined answer spends no Reaction"
    recorded = [row for row in _controller_reactions(combat, mid)
                if "smoke_blacken_the_flame" in json.dumps(row, default=str)]
    assert recorded, "the AI must answer the question itself, not leave it to nobody answering"
    assert all("manual" not in str(row.get("controller_id") or "") for row in recorded), \
        f"an AI owner is answered by the AI controller: {[row.get('controller_id') for row in recorded]}"
    assert all(not row.get("selected_option_ids") for row in recorded), \
        f"and it declined, so no option was taken: {[row.get('selected_option_ids') for row in recorded]}"


# ==================================================================== a saved fight from before the hook, loaded cold
def _rewind_to_a_pre_number_save(combat, mid):
    """Rewind this fight's saved compiled bundles to how a fight saved before the ``compile_block`` hook stored Blacken
    the Flame: the row keeps its ownership and nothing else, with no ``dice`` and no ``key_mod``.

    This edits the one file a saved fight's compiled characters live in (gate3_storage ``TYPED_BUNDLES_FILE``, which
    every load reads back) and not the journal, so the recorded setup -- veil, trace, whose turn it is -- is replayed
    from disk exactly as it was. Nothing else in the tree is touched, so a loader that only worked because the plug-in
    still had the numbers in hand fails the assertions that follow.

    The save is then re-sealed, because that is what a genuine older save already is: the immutable identity its
    ``MatchLock.json`` records is the hash of the bundle bytes it stores. Editing the file and leaving the old identity
    in place would describe a *changed* saved input, which the loader must refuse (``MATCH_CONTENT_VERSION_MISMATCH``);
    re-sealing keeps the scenario -- a fight whose compiled characters predate the hook -- while leaving the saved-bundle
    integrity check strict.
    """
    import hashlib

    from combat.gate3_storage import TYPED_BUNDLES_FILE, _match_lock_deterministic_hash

    folder = Path(combat._match_dir(mid))
    path = folder / TYPED_BUNDLES_FILE
    bundles = json.loads(path.read_text(encoding="utf-8"))
    rewound = 0
    for bundle in bundles:
        for row in bundle.get("typed_passives") or []:
            if row.get("block") == smoke_veil.BLACKEN_BLOCK and (row.get("dice") or row.get("key_mod")):
                row.pop("dice", None)
                row.pop("key_mod", None)
                rewound += 1
    assert rewound == 1, f"exactly the owner's Blacken the Flame row is rewound: {rewound}"
    path.write_bytes(json.dumps(bundles, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")

    lock_path = folder / "MatchLock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for row in lock["content_identities"]:
        if row["relative_path"] == TYPED_BUNDLES_FILE:
            row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    lock["deterministic_payload_sha256"] = _match_lock_deterministic_hash(lock)
    lock_path.write_text(json.dumps(lock, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def test_a_legacy_blacken_save_reloaded_from_disk_keeps_its_printed_reduction(tmp_path, monkeypatch):
    """The saved-fight compatibility path, at the service boundary, answering real damage.

    A fight compiled before the hook existed carries a Blacken the Flame row with no dice and no key modifier, and
    cannot be recompiled: the numbers it is playing with are the ones in its own saved bundles. So the row is rewound on
    disk, the fight is loaded cold through a *new* ``CombatService`` and a *new* ``TabletopService``, and the AI's real
    Fire ability is then resolved against it. The reduction must still be the printed one -- 3d6 + 2 at CL 11 with a +2
    key ability modifier -- and both printed costs must still be paid. A loader that lost either the row or the fight's
    compiled numbers would quietly reduce by 1d6 + 0, a sixth of what the owner bought.
    """
    combat, table, mid = _fire_fight(tmp_path)
    bearer = _veil_and_trace(table, mid)
    _rewind_to_a_pre_number_save(combat, mid)

    fresh = CombatService(ROOT, tmp_path)           # a new service: nothing is carried over in memory
    reloaded = TabletopService(fresh, tmp_path)
    session = fresh._load_session(mid)              # the fight as it comes back off disk
    engine = session.engine
    row = next(iter(block_rows(engine, engine.state.actors[OWNER], smoke_veil.BLACKEN_BLOCK)), None)
    assert row is not None, "a saved fight keeps its Blacken the Flame ownership row"
    assert not row.get("dice") and row.get("key_mod") is None, f"this save predates the hook's own numbers: {row}"
    numbers = smoke_veil._compiled_numbers(engine, engine.state.actors[OWNER])
    assert (numbers.get("cl"), numbers.get("key_mod")) == (11, 2), \
        f"the fight's own compiled numbers are the other half of the compatibility reader: {numbers}"
    assert session.verify()["status"] == "PASS", session.verify()
    assert session.mechanical.replay()["status"] == "PASS", session.mechanical.replay()
    assert bears_mark(engine.state.actors[bearer], OWNER, "Smoke Trace"), "the saved Smoke Trace comes back too"

    before = engine.state.actors[VICTIM].current_hp
    result = _ai_fire(fresh, reloaded, mid, monkeypatch)
    assert result["status"] == "REACTION_REQUIRED", f"the reloaded fight must still ask its player: {result['status']}"
    prompt = _soot_prompt(result)
    assert prompt, f"and the question is still Blacken the Flame: {result.get('reaction')}"
    assert "3d6 + 2" in str(prompt["moment"]), \
        f"the saved fight must offer the reduction it was already playing: {prompt['moment']}"
    resumed = reloaded.auto_step(mid, reloaded.state(mid)["last_sequence"], [_use(prompt)])
    assert resumed["status"] == "COMMITTED", resumed["status"]

    after = fresh._load_session(mid).engine
    cuts = [roll for roll in after.rolls if roll.reason == "DAMAGE_REDUCED"]
    assert cuts, "Blacken the Flame must still answer damage in a fight saved before its numbers were stored"
    assert len(cuts[0].dice) == 3 and cuts[0].modifier == 2, \
        f"a pre-number CL 11 save still rolls the printed 3d6 + 2, not the 1d6 + 0 default: {cuts}"
    assert after.state.actors[VICTIM].current_hp < before
    assert not bears_mark(after.state.actors[bearer], OWNER, "Smoke Trace"), "the saved Smoke Trace is still spent"
    assert not after.state.actors[OWNER].reaction_available, "the saved Reaction is still spent"
    assert fresh._load_session(mid).verify()["status"] == "PASS", "and the fight it leaves behind still verifies"
