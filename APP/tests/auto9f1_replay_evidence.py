"""Paired baseline/tip AI replay evidence for the Alchemy lane (checklist 12).

Both halves run through the **real table** (``CombatService`` + ``TabletopService``) in two different
checkouts -- the baseline commit and this one -- so both sides carry compiled plug-in ownership, saved
transitions and recorded prompts:

* ``capture(path, scenario)`` -- run in **both** checkouts with this same file, so the script is
  identical. Builds one synthetic table in a task-owned folder, plays a fixed Alchemy script
  (:data:`PILOT`) so the printed effects this lane changed are actually reached, then hands both
  creatures to the AI and plays a fixed number of ``auto_step``s. Zone destinations are pinned by
  coordinate: a zone action offers one option per legal cell and the engine builds that list in set
  order, so "the first option" made the same script drop the area in a different cell in each
  checkout (and the difference then read as a behaviour change).
* ``journal_differences(baseline, tip)`` -- the comparison, run anywhere. Lines the two fights'
  committed transactions up and reports **every** difference in *every* payload field and saved
  value, as minimal event-level edits, plus the SHA-256 of each side's whole journal so
  "byte-identical" is a fact rather than a claim. The saved numbers come from the state each
  fight's **last committed record** rebuilds to, through the loader's own read-only history
  authority -- never from the newest snapshot, which is periodic and can be an older state than
  the fight is left holding. A field is only skipped when it is named in
  :data:`VOLATILE_EVENT_FIELDS` / :data:`VOLATILE_PAYLOAD_FIELDS` / :data:`UNORDERED_PAYLOAD_LISTS`;
  everything else a behaviour change can touch is compared and must be named by the acceptance test.

The bare-engine replay harness used by ``hunt36_replay_compare`` is deliberately **not** used here: it
builds ``Gate4ControllerEngine`` straight from a recorded bundle, which never loads compiled plug-in
ownership, so ``owns_seven_flavor`` is false in it and every plug-in difference is invisible. It is a
saved-fight check, not a behaviour comparison.

Nothing here patches an engine or core function: the fight is built from ordinary compiled character
sheets and played through the real table.

Usage::

    # baseline checkout, then this one (same file in both)
    python -m tests.auto9f1_replay_evidence capture <owned-dir> alchemy|control
    # anywhere
    python -m tests.auto9f1_replay_evidence compare <baseline-match> <tip-match>

A saved history the loader will not rebuild raises :class:`UnreadableSavedHistory`: it is never reported as
"no state", because a comparison whose two halves both read as empty satisfies every assertion of a
byte-identical control (AUTO9r3 review, finding 1).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

from combat.gate3_storage import Gate3MatchStore, Gate3Persistence
from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, send

#: This checkout's APP directory, so a capture is read back with the same code that wrote it.
APP_ROOT = Path(__file__).resolve().parents[1]

#: The talent that owns the substitution, named once: it is both an ability the capture's Alchemist is
#: given and the source the saved preparation condition is applied from.
SEVEN_FLAVOR = "tianxia.talent.alchemy.seven_flavor_furnace"
#: The one printed ability whose own rules text carries the Dash clause ("If the target is standing on a
#: solid surface, it also cannot take the Dash action"), and the condition the tip settles it as. The
#: clause is only settled by a save that failed against *this* ability, so the evidence keeps each failed
#: save and each application of the clause together instead of reducing them to a fight-wide creature set.
BINDING_DREGS = "TAL_ALCHEMY_BINDING_DREGS"
DASH_CLAUSE = "condition:typed.no_dash"
#: The Alchemist this lane automated, so the capture exercises the printed effects that changed:
#: Seven-Flavor Furnace's prepared types, the Court's extra damage, World Within the Furnace's
#: chosen type, and Binding Dregs' solid-surface clause.
ALCHEMIST = [
    SEVEN_FLAVOR,
    "TAL_ALCHEMY_POISON_PILL",
    "TAL_ALCHEMY_FURNACE_VENT",
    "TAL_ALCHEMY_BINDING_DREGS",
    "tianxia.talent.alchemy.world_within_the_furnace",
    "tianxia.talent.alchemy.court_of_the_three_legged_cauldron",
]
#: Hands the Alchemist the Reagent Stock the printed potion costs need; a synthetic data-only action,
#: never a patched engine call.
STOCK = [{"type": "gain_resource", "resource_id": "resource:named.reagent_stock", "amount": 6,
          "applies_to": "self", "duration": "instant",
          "evidence": "Scenario setup: prepared Reagent Stock for the printed potion costs."}]

#: The printed abilities this lane changed, driven by hand in the recorded order, each with the square
#: its area is aimed at. An AI left to choose spends six turns walking and never reaches a potion, which
#: would make the byte comparison vacuous. The square is pinned rather than left to "the first option the
#: menu offers": a zone action offers one option per legal cell and the engine builds that list in set
#: order, so the same script put the area in a different cell in each checkout -- a difference of the
#: harness's own making that the journal then reported as a behaviour change. ``None`` means the ability
#: has no placement to choose.
PILOT = [("Furnace Vent", (4, 6)), ("Binding Dregs", None),
         ("Poison Pill: Rotting Pill", None), ("World Within the Furnace: Acid", (4, 6)),
         ("Court of the Three-Legged Cauldron", None)]
#: The starting square of the foe in ``tests.hunt36_support.fight``: the areas are aimed at it so both
#: checkouts put the same creature inside them.
FOE_SQUARE = (4, 6)

SCENARIOS = {"alchemy": dict(owned=ALCHEMIST, effects=STOCK, primary="Stamina", seed="AUTO9F1-ALCHEMY",
                             pilot=PILOT, foe_hp=20000),
             "control": dict(owned=[], primary="Qi", seed="AUTO9F1-CONTROL", pilot=None, foe_hp=1000)}


def active_turn(table, mid):
    """The creature whose turn it is, or None once the fight has ended (no open menu)."""
    return (table.state(mid).get("menu") or {}).get("actor_id")


def offered(table, mid, label):
    """Whether the creature whose turn it is may use ``label`` right now."""
    return any(group["label"] == label for group in (table.state(mid).get("menu") or {}).get("actions", []))


def centres_on(table, mid, label):
    """The squares ``label``'s area options are aimed at right now, so a pinned one can be checked."""
    return {json.dumps((option.get("area") or {}).get("center"), sort_keys=True)
            for group in (table.state(mid).get("menu") or {}).get("actions", []) if group["label"] == label
            for option in group.get("options") or []}


def act_at(combat, table, mid, label, at):
    """Use ``label`` aimed at square ``at``: the placement *is* the primary candidate, so the square has
    to be chosen here rather than among the answers.

    ``tests.hunt36_support.act`` takes the first option the menu lists, and a zone action lists one option
    per legal cell in set order -- so the same script aimed the same area at a different square in each
    checkout, and the journal then reported that as a behaviour change. Named square, same fight.
    """
    menu = table.state(mid)["menu"]
    square = {"x": at[0], "y": at[1]}
    cid = next((option["candidate_id"] for group in menu["actions"] if group["label"] == label
                for option in group["options"] if (option.get("area") or {}).get("center") == square), None)
    assert cid is not None, \
        f"{label} is not offered at {at}; offered: {sorted(centres_on(table, mid, label))}"
    return send(combat, table, mid, cid)


def act_when_offered(combat, table, mid, label, at=None, tries: int = 2) -> bool:
    """Use ``label`` as soon as it is offered, ending turns until it is (a Court is a Bonus Action).

    ``at`` pins the square an area is aimed at, and is asserted to be offered rather than defaulted to.

    False when the fight ended or the ability was never offered, so a printed ability this scenario could
    not reach is reported in ``played``'s absence rather than silently skipped.
    """
    for _ in range(tries):
        if active_turn(table, mid) is None:
            return False
        if offered(table, mid, label):
            act_at(combat, table, mid, label, at) if at is not None else act(combat, table, mid, label)
            return True
        act(combat, table, mid, "end")
        for _ in range(3):
            if active_turn(table, mid) == LEFT:
                break
            if active_turn(table, mid) is None:
                return False
            act(combat, table, mid, "end")
    return False


def capture(path: Path, scenario: str, steps: int = 6) -> dict:
    """Play a fixed Alchemy script, then hand both creatures to the AI, and report the journal PREPARE sequences."""
    settings = dict(SCENARIOS[scenario])
    seed = settings.pop("seed")
    pilot = settings.pop("pilot")
    combat, table, mid = fight(path, owned=settings["owned"], primary=settings["primary"],
                               effects=settings.get("effects"), seed=seed, foe_hp=settings["foe_hp"], foe_ac=12)
    if settings.get("effects"):
        act(combat, table, mid, "Test setup")
        act(combat, table, mid, "end")
    match = next(path.rglob("GenesisState.json")).parent
    rows = lambda: list(map(json.loads, (match / "Journal.ndjson").read_text().splitlines()))
    before = max((row["record_sequence"] for row in rows()), default=0)
    played = []
    if pilot:
        for label, at in pilot:
            if act_when_offered(combat, table, mid, label, at=at):
                played.append(label)
                reload(combat, mid)
    ai_turns = 0
    if active_turn(table, mid) is not None:
        for actor in (LEFT, RIGHT):
            combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
        for _ in range(steps):
            state = table.state(mid)
            result = table.auto_step(mid, state["last_sequence"])
            assert result["status"] == "COMMITTED", result
            ai_turns += 1
            reload(combat, mid)
    prepares = [row["record_sequence"] for row in rows()
                if row["record_sequence"] > before and row["record_type"] == "PREPARE"]
    assert prepares, "nothing was played after the setup"
    return {"scenario": scenario, "match": str(match), "played": played, "ai_turns": ai_turns,
            "prepares": prepares}


#: Journal fields that record *where* in the fight something happened rather than *what* happened, and so
#: move whenever an earlier event is added or removed: the event sequence, the state version, the
#: transaction and intent that produced it. Dropped by name so they cannot read as a behaviour change.
VOLATILE_EVENT_FIELDS = frozenset({"sequence", "state_version", "transaction_id", "trigger_or_intent_id"})
#: Payload fields of the same kind: ids that embed an event sequence or a hash of the candidate that
#: produced them, the roll counter's running value, the ``gate3_*_after`` snapshots, which are the whole
#: control state and land on whichever event last changed it, and the two sequence numbers a saved
#: condition carries. Everything else in a payload is compared -- a damage amount, a resource's
#: remainder, a condition's data, a zone's cells.
VOLATILE_PAYLOAD_FIELDS = re.compile(
    r"^(?:gate3_\w+_after|instance_id|modifier_id|roll_id|zone_id|candidate_id|counter_start|counter_end|"
    r"started_sequence|applied_sequence)$")
#: Payload lists the engine builds as sets, so their order is not behaviour. Named one by one rather than
#: sorted everywhere: ``dice`` and ``path`` are ordered too, and sorting those would hide a real change.
UNORDERED_PAYLOAD_LISTS = frozenset({"affected_cells", "target_ids"})


def _payload(value, key=""):
    """A payload with the named volatile fields dropped and the named set-built lists order-normalised."""
    if isinstance(value, dict):
        return {name: _payload(item, name) for name, item in sorted(value.items())
                if not VOLATILE_PAYLOAD_FIELDS.match(name)}
    if isinstance(value, list):
        items = [_payload(item, key) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True)) if key in UNORDERED_PAYLOAD_LISTS \
            else items
    return value


def _event(event: dict) -> dict:
    """One journal event, reduced to what happened rather than where it was recorded."""
    return {name: value for name, value in sorted(event.items()) if name not in VOLATILE_EVENT_FIELDS
            } | {"payload": _payload(event.get("payload") or {})}


def _event_key(event: dict) -> str:
    return json.dumps(event, sort_keys=True, ensure_ascii=False)


def commits(match: Path) -> list[dict]:
    """Each committed transaction of a journal, every event reduced by :func:`_event`.

    The whole event is kept, not a hand-picked list of fields: a payload field nobody thought to list
    (a damage amount, a resource's remainder, a condition's data) must still show up as a difference, or
    acceptance could wave a state change through by leaving it unnamed.
    """
    rows = [json.loads(line) for line in (match / "Journal.ndjson").read_text().splitlines()]
    return [{"sequence": row["record_sequence"], "events": [_event(event) for event in row["events"]]}
            for row in rows if row["record_type"] == "COMMIT"]


#: A compiled action's journal source id carries a per-character prefix and an option suffix
#: (``action:typed.ecf05feaca.TAL_ALCHEMY_POISON_PILL#opt2``); both are stripped so the id reads as the
#: printed mechanic it is. One implementation, shared by everything here that has to name a mechanic.
_TYPED_SOURCE = re.compile(r"^(?:action:typed\.[^.]+\.)?(?P<mechanic>[^#]+?)(?:#opt\d+)?$")


def mechanic(source_definition_id) -> str:
    """The printed mechanic a journal source id names, per-character prefix and option suffix removed."""
    found = _TYPED_SOURCE.match(str(source_definition_id or ""))
    return found.group("mechanic") if found else ""


def is_failed_save(event: dict, source: str) -> bool:
    """Whether one event is a save the fight rolled as **failed** against one printed ability.

    Reported rather than assumed by whoever needs it: a printed clause that only settles when a save
    fails can only be checked against the fight's own rolled saves, and the creature that rolled is the
    affected one while the source is the ability whose printed text the save was made against.
    """
    return event["event_type"] == "SAVE_ROLLED" and (event["payload"] or {}).get("success") is False \
        and mechanic(event.get("source_definition_id")) == mechanic(source)


def save_failures(side: list[dict]) -> list[dict]:
    """Every save ``side``'s journal records as **failed**, with where in the fight it was rolled.

    Reported as ``{actor_id, source_definition_id, transaction, event_index}``. The transaction is kept
    because a printed clause is settled by the save that resolves with it, not by any failed save the
    fight happened to roll earlier: reducing this to a creature set could not tell the clause a real
    failure settled from an extra application during a *successful* later cast on the same creature, and
    it could not tell a real application from an extra expiration with no application behind it.
    """
    return [{"actor_id": event.get("actor_id"), "source_definition_id": event.get("source_definition_id"),
             "transaction": commit["sequence"], "event_index": index}
            for commit in side for index, event in enumerate(commit["events"])
            if event["event_type"] == "SAVE_ROLLED" and (event["payload"] or {}).get("success") is False]


def settled_clauses(side: list[dict], condition_id: str, source: str) -> dict:
    """Ordered Dash lifetimes, with JSON-compatible, deterministic evidence coordinates.

    Applications require a preceding failed save in the same transaction. A removal consumes the
    active lifetime even if malformed, so neither a premature removal nor a duplicate can borrow it.
    Only the turn-start housekeeping block before the source's first subsequent TURN_STARTED is the
    printed start-of-source-next-turn boundary. ``removed`` includes the event index: two otherwise
    identical removals in one transaction must not both be accepted by the classifier.
    """
    events = [(commit["sequence"], index, event)
              for commit in side for index, event in enumerate(commit["events"])]
    # _expire_typed_for_checkpoint expires conditions, then posture.stand_up removes STAND_UP
    # conditions and emits STOOD_UP before TURN_STARTED. Allow those documented system events,
    # never arbitrary events with a checkpoint label, actions, other actors, or transactions.
    boundaries = {}
    for position, (transaction, _, event) in enumerate(events):
        if event["event_type"] != "TURN_STARTED":
            continue
        actor = event.get("actor_id")
        start = position
        while start:
            previous_transaction, _, previous = events[start - 1]
            payload = previous.get("payload") or {}
            expiration = previous.get("source_definition_id") == "system:combat.expiration" \
                and payload.get("checkpoint") == "START_OF_TURN"
            standing = previous.get("source_definition_id") == "system:combat.stand_up" \
                and previous.get("target_ids") == [actor] \
                and (previous["event_type"] == "STOOD_UP" or (
                    previous["event_type"] == "CONDITION_REMOVED" and payload.get("checkpoint") == "STAND_UP"))
            if previous_transaction != transaction or previous.get("actor_id") != actor \
                    or not (expiration or standing):
                break
            start -= 1
        boundaries[position] = (actor, start)

    failed, settled, removed = set(), set(), []
    saves, active = {}, {}
    for position, (transaction, index, event) in enumerate(events):
        if event["event_type"] == "SAVE_ROLLED" \
                and mechanic(event.get("source_definition_id")) == mechanic(source):
            saves.pop(str(event.get("actor_id")), None)
        if is_failed_save(event, source):
            target = str(event.get("actor_id"))
            failed.add(target)
            saves[target] = transaction
        payload = event.get("payload") or {}
        if payload.get("condition_id") == condition_id:
            if event["event_type"] == "CONDITION_APPLIED":
                for target in map(str, event.get("target_ids") or []):
                    # An unqualified application replaces provenance too; it cannot inherit a prior
                    # lifetime. The acceptance test separately rejects that application.
                    active.pop(target, None)
                    if mechanic(event.get("source_definition_id")) != mechanic(source) \
                            or saves.get(target) != transaction \
                            or payload.get("expires_on") != "START_OF_SOURCE_NEXT_TURN":
                        continue
                    settled.add((transaction, target))
                    owner = event.get("actor_id")
                    boundary = next((turn for turn, (actor, _) in boundaries.items()
                                     if turn > position and actor == owner), None)
                    active[target] = (owner, boundary)
            elif event["event_type"] == "CONDITION_REMOVED":
                for target in map(str, event.get("target_ids") or []):
                    lifetime = active.pop(target, None)
                    if lifetime is None:
                        continue
                    owner, boundary = lifetime
                    if boundary is not None and boundaries[boundary][1] <= position < boundary \
                            and event.get("actor_id") == owner \
                            and event.get("source_definition_id") == "system:combat.expiration" \
                            and payload.get("checkpoint") == "START_OF_TURN":
                        removed.append([transaction, target, index])
        if event["event_type"] == "TURN_STARTED":
            active = {target: life for target, life in active.items() if life[1] != position}
    return {"failed": sorted(failed), "settled": [list(pair) for pair in sorted(settled)],
            "removed": removed}


def _edits(before: dict, after: dict) -> list[dict]:
    """Minimal event-level differences between two transactions, each carrying its own sequence.

    Inserting one event shifts every later index, so comparing the two lists position by position
    reports one change as a dozen. A diff over the events themselves reports each real edit once.

    The two record sequences ride beside the events so a claimed condition can be checked against the
    failed save that settled it in *its own* transaction rather than against the whole fight. They are
    the records' own sequences, not positions in either list, so nothing here depends on how many events
    one side happened to record.
    """
    edits = []
    matcher = difflib.SequenceMatcher(a=[_event_key(event) for event in before["events"]],
                                      b=[_event_key(event) for event in after["events"]], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        edits.append({"kind": tag, "baseline": before["events"][i1:i2], "tip": after["events"][j1:j2],
                      "baseline_transaction": before["sequence"], "tip_transaction": after["sequence"],
                      "baseline_event_indices": list(range(i1, i2)), "tip_event_indices": list(range(j1, j2))})
    return edits


class UnreadableSavedHistory(RuntimeError):
    """A saved fight the loader will not rebuild, so its state cannot be compared with anything.

    Raised, never swallowed. Reporting the failure as an empty state made two unreadable captures compare as
    "both sides have no actors, no areas, no round and nobody acting", which satisfies a byte-identical
    control's assertions -- so a broken saved fight could pass the saved-fight check (AUTO9r3 review,
    finding 1). The name and the reason are in the message, so a failure reads as the fight it is rather
    than as a harness problem.
    """


def final_committed_state(match: Path) -> tuple[dict, dict]:
    """The state this fight's **last committed record** rebuilds to, and which record that was.

    Read through ``Gate3Persistence.history_boundaries``, the loader's own read-only history
    authority (``combat/gate3_storage.py``): it replays every COMMIT from genesis and raises rather
    than guess when the reducer cannot reproduce a committed hash. It is deliberately **not** the
    newest snapshot. Snapshots are periodic -- every tenth commit and on every round change
    (``combat/gate3_storage.py``, ``should_snapshot``) -- while the loader takes the newest valid
    snapshot and replays every later commit on top of it, so a fight that continued past one keeps
    *older* hit points, pools and conditions in that file than the fight is actually left holding.
    Reading the snapshot here would compare a checkpoint rather than the saved fight.

    ``source["kind"]`` is always ``final_committed_record``; the record's own sequence and hash ride
    beside it and are reported rather than classified. A fight that cannot be rebuilt raises
    :class:`UnreadableSavedHistory` instead of returning an empty state.
    """
    try:
        # The folder name is the encoded form of the fight's own id (``encode_match_directory_name``),
        # so the id is read from the lock the folder holds and the store resolves the pair back.
        logical = json.loads((match / "MatchLock.json").read_text(encoding="utf-8"))["match_id"]
        store = Gate3MatchStore(match.parents[2], logical)
        assert store.match_dir == match.resolve(), f"{match} is not the stored directory of {logical}"
        history = Gate3Persistence(APP_ROOT, match.parents[2]).history_boundaries(store.match_id)
        boundary = history["boundaries"][-1]
    except Exception as exc:  # the loader refused this fight; say so instead of comparing nothing
        raise UnreadableSavedHistory(
            f"{match}: the saved history cannot be rebuilt, so its state cannot be compared: "
            f"{type(exc).__name__}: {exc}"[:600]) from exc
    return boundary["state"], {"kind": "final_committed_record",
                               "record_sequence": boundary["record_sequence"],
                               "canonical_state_sha256": boundary["canonical_state_sha256"]}


def state_facts(match: Path) -> dict:
    """The saved fight's own numbers, as the final committed record reconstructs them.

    The journal says what was announced; this says what the fight is left holding, so a change that nets
    out in the log (a pool one point off, a condition with no label, an area on the wrong square) is still
    a difference somebody has to name. Raises :class:`UnreadableSavedHistory` when the fight cannot be
    rebuilt -- ``source`` therefore only ever reads ``final_committed_record``.
    """
    state, source = final_committed_state(match)
    actors = {}
    for actor_id, actor in sorted((state.get("actors") or {}).items()):
        actors[actor_id] = {
            "current_hp": actor.get("current_hp"), "temporary_hp": actor.get("temporary_hp"),
            "position": actor.get("position"), "resources": dict(sorted((actor.get("resources") or {}).items())),
            "conditions": {_instance_free(condition_id): {key: _payload(condition.get(key))
                                                         for key in ("expires_on", "data")}
                           for condition_id, condition in sorted((actor.get("conditions") or {}).items())},
        }
    zones = {_instance_free(zone_id): {"center": zone.get("center"), "radius_cells": zone.get("radius_cells"),
                                       "shape": (zone.get("trigger_profile") or {}).get("shape"),
                                       "damage_types": _zone_damage_types(zone.get("trigger_profile") or {})}
             for zone_id, zone in sorted((state.get("zones") or {}).items())}
    return {"source": source["kind"], "head": source, "round_number": state.get("round_number"),
            "current_actor_id": state.get("current_actor_id"), "actors": actors, "zones": zones}


#: A saved instance id ends in the event sequence that created it ("...:41"), so it shifts whenever an
#: earlier event is added. The identity is everything before that number.
_INSTANCE_SEQUENCE = re.compile(r":\d+$")


def _instance_free(identifier: str) -> str:
    return _INSTANCE_SEQUENCE.sub("", str(identifier))


def _zone_damage_types(profile: dict, depth: int = 0) -> list[str]:
    """Every damage type an area's own rows carry, in row order: the type its creator chose is kept.

    Walked by depth rather than by a fixed shape -- a zone nests typed > zone_spec > triggers > effects >
    save > on_fail > damage, and one more row of nesting would otherwise read as "no damage type".
    """
    if depth > 12:
        return []
    if isinstance(profile, dict):
        if profile.get("type") == "damage":
            return [str(kind).lower() for kind in profile.get("damage_types") or []]
        return [kind for value in profile.values() for kind in _zone_damage_types(value, depth + 1)]
    if isinstance(profile, list):
        return [kind for value in profile for kind in _zone_damage_types(value, depth + 1)]
    return []


def journal_sha256(match: Path) -> str:
    """SHA-256 over the whole journal, so "byte-identical" is checkable rather than asserted."""
    return hashlib.sha256((match / "Journal.ndjson").read_bytes()).hexdigest()


def journal_differences(baseline: Path, tip: Path) -> dict:
    """Line two paired captures up transaction by transaction and report **every** difference.

    The fights are played from the same seed with the same script, so the transaction count and order are
    expected to line up; a different count is itself reported rather than silently truncated. Each
    transaction's events are diffed as a whole, and the saved fight's own numbers are reported beside
    them, so nothing a change could touch is left for the acceptance test not to look at.

    Raises :class:`UnreadableSavedHistory` if either side's saved history cannot be rebuilt, so no caller
    can go on to compare two empty states and call them equal.
    """
    old, new = commits(baseline), commits(tip)
    differences = []
    for index, (before, after) in enumerate(zip(old, new)):
        edits = _edits(before, after)
        if edits:
            differences.append({"transaction": index, "baseline_sequence": before["sequence"],
                                "tip_sequence": after["sequence"], "edits": edits})
    old_state, new_state = state_facts(baseline), state_facts(tip)
    state = {key: {"baseline": old_state[key], "tip": new_state[key]}
             for key in ("source", "round_number", "current_actor_id", "actors", "zones")
             if old_state[key] != new_state[key]}
    # Which committed record each side's saved state was rebuilt from, reported and not classified:
    # the two halves reach their final state through their own last commit, so the record's own
    # identity always differs and says nothing about behaviour.
    state_head = {"baseline": old_state["head"], "tip": new_state["head"]}
    # Whole-fight totals as well: a creature that Dodies one turn later is the AI choosing differently,
    # not a rule changing, and only the totals separate that from a condition the fight never had.
    totals = {}
    for key, event_type, field in (("conditions", "CONDITION_APPLIED", "condition_id"),
                                   ("damage", "DAMAGE_COMMITTED", "damage_type"),
                                   ("riders", "GM_RIDER", "rider"),
                                   ("spent", "RESOURCE_SPENT", "resource_id")):
        def values(side):
            return sorted(str(event["payload"].get(field)) for commit in side for event in commit["events"]
                          if event["event_type"] == event_type)
        before, after = values(old), values(new)
        totals[key] = {"baseline": before, "tip": after,
                       "gained": sorted(set(after) - set(before)), "lost": sorted(set(before) - set(after))}
    return {
        "baseline_journal_sha256": journal_sha256(baseline),
        "tip_journal_sha256": journal_sha256(tip),
        "byte_identical": journal_sha256(baseline) == journal_sha256(tip),
        "baseline_transactions": len(old),
        "tip_transactions": len(new),
        "transaction_counts_match": len(old) == len(new),
        "totals": totals,
        "save_failures": {"baseline": save_failures(old), "tip": save_failures(new)},
        # Binding Dregs' settled Dash clause on each side: which creature lost the save the clause needs,
        # and the transaction each qualifying application of the clause happened in. Reported rather than
        # reduced to a creature set, so the acceptance test can bind every application and every removal
        # to the failed save that actually settled it.
        "dash_lifecycles": {side: settled_clauses(clips, DASH_CLAUSE, BINDING_DREGS)
                            for side, clips in (("baseline", old), ("tip", new))},
        "state": state,
        "state_head": state_head,
        "differences": differences,
    }


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        print(json.dumps(capture(Path(sys.argv[2]).resolve(), sys.argv[3])))
    else:
        try:
            print(json.dumps(journal_differences(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()), indent=2))
        except UnreadableSavedHistory as exc:  # a capture the loader will not rebuild, not a tooling failure
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
