"""Paired baseline/tip replay evidence for the AUTO17f1/AUTO17r1f1 review fixes (checklist 12).

Both halves run through the **real table** (``CombatService`` + ``TabletopService``) in two different checkouts --
the baseline commit under review and this one -- so both carry compiled plug-in ownership, saved transitions and
recorded prompts:

* ``capture(path, scenario)`` -- run in each checkout. Builds one synthetic table in a task-owned folder and plays a
  fixed number of ``auto_step``s from a fixed seed, reloading the fight from disk after every step.
* ``journal_differences(baseline, tip)`` -- the whole-journal comparison, run anywhere: every committed
  transaction's event types, conditions, damage, spending and rider text, plus the SHA-256 of each side's journal.
* ``full_differences(baseline, tip, expected=...)`` -- the comparison a test asserts on: **every** stored value of
  both fights (every journal record with every field, ``GenesisState.json``, and every other artefact either side
  wrote), reported one differing path at a time, with the caller naming the only paths it allows. Anything else
  comes back under ``unexpected``, so a change nobody named cannot hide in a key the summary never read.

Two scenarios:

``control``  a fighter fight with a Brute/Sabers pair and a real weapon -- nothing this lane or the Blacksmith
             plug-in touches. Expected byte-identical, with no allowed difference at all.
``smith``    the Blacksmith these rounds changed, so its differences are named explicitly rather than waved through.

Every stored condition is addressed by its own identity rather than by where it happened to sit, so an allowance that
names the Forge Mark's row cannot cover another condition's row -- including the condition a committed transaction
recorded inside its own journal record (:func:`canonical_capture`).

Nothing here patches an engine or core function: the fight is built from ordinary compiled character sheets and
played through the real table. ``hunt36_support.reload`` additionally asserts the saved fight verifies and that its
recorded events replay to the same status, which is the saved-fight compatibility check.

Usage::

    # baseline checkout, then this one
    python -m tests.auto17f1_replay_evidence capture <owned-dir> control|smith
    # anywhere
    python -m tests.auto17f1_replay_evidence compare <baseline-match> <tip-match> [expected-prefix ...]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from tests.hunt36_support import LEFT, RIGHT, fight, reload

#: The Blacksmith records AUTO17 automated, so the smith scenario reaches the chassis and the Forge Responses.
SMITH = [
    "BLACKSMITH_BASE_HAMMER_THE_MARK",
    "BLACKSMITH_BASE_SET_THE_WORKPIECE",
    "tianxia.talent.blacksmith.tempering_sequence",
    "tianxia.talent.blacksmith.field_repair",
    "tianxia.talent.blacksmith.quench_in_breath",
    "tianxia.talent.blacksmith.seven_hammer_revision",
]
#: A fighter this lane does not touch: a different sphere, so the control is a real fight and not an empty table.
CONTROL = ["TAL_BRUTE_MOUNTAIN_MOVING_PALM", "tianxia.talent.sabers.forward_cut"]
KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}]}}

SCENARIOS = {
    "control": dict(owned=CONTROL, seed="AUTO17F1-CONTROL"),
    "smith": dict(owned=SMITH, seed="AUTO17F1-SMITH"),
}

#: The ONLY differences a pair of captures is allowed to have. Anything else is a bug in the change, which is what
#: finding 4 of the review was about: the earlier comparison summarised four fields per transaction, so a difference
#: hiding in any other stored value could not show. These are full paths into the saved data, and every one of them
#: is either the wall clock of the run or a value derived from another entry on this list.
#:
#: Two runs of one fight cannot agree on the time of day, so these are unavoidable and are not about behaviour:
VOLATILE_PATHS = (
    # the wall clock stamped on each recorded choice and on the fight's own files
    "DaoIChingChoiceAudit.ndjson[].recorded_at",
    "FactoryIntegration.json.created_at",
    "FactoryIntegration.json.updated_at",
    "Manifest.json.display_updated_at",
    "MatchLock.json.created_at_display",
    # and the digests taken over files that contain one
    "Manifest.json.file_identities.MatchLock.json",
)

#: The control scenario is a fighter fight nothing in this lane touches, so its declaration is the wall clock alone:
CONTROL_PATHS = VOLATILE_PATHS

#: The smith scenario is the Blacksmith these rounds changed. Every line below names one value this round changed on
#: purpose, at the path that value actually lives at, and nothing else.
#:
#: :func:`canonical_capture` re-keys both captures by identity first, so a list that merely gained an entry no longer
#: drags every later entry along with it: the compiled catalogue is keyed by action id, an actor's offered buttons by
#: action id, and its stored conditions by condition id (the instance id carries an event sequence number, which is
#: noise). After that, the only differences these paths can cover are the values themselves.
#:
#: (1) the smith's compiled catalogue gained the button that ends the personal-work declaration, so exactly one new
#:     action id appears -- here, in the template's list, and in the actor's own list in the genesis state and in every
#:     snapshot. The declaration's own wording changed too, and only the one field that carries it.
NEW_BUTTON = "action:typed.ecf05feaca.seven_hammer.personal_work.end"
DECLARATION_BUTTON = "action:typed.ecf05feaca.seven_hammer.personal_work"
#: The one field of the existing declaration this round rewrote (the reset is now "your last Forge Mark", across every
#: holder). Its effects, costs, targeting and economy are NOT allowed to differ, and the negative regression in
#: tests/test_auto17f1_replay.py proves that.
DECLARATION_FIELD = "parameters.setting_description"
#: The mark condition whose row this round changed, and the fields of that row it changed. As saved, the row is keyed
#: by an instance id that carries an event sequence number, so :func:`canonical_capture` re-keys every stored condition
#: -- in the genesis state, in a snapshot, and inside a committed transaction alike -- by the row's own identity: its
#: condition id and the smith who placed it. The allowance is then named against the identity each capture really
#: holds, never a wildcard that would also cover another condition's row.
#:
#: ``data.deadlines`` is the per-mark clock (one entry per mark instead of one for the count) and ``data.undated`` is
#: how many of the count are marks carried over from a save this module cannot date, kept apart so a mark placed now
#: gets its own printed minute even when it shares a row with them.
MARK_CONDITION = "condition:typed.mark.forge_mark"
MARK_ROW_FIELDS = ("data.deadlines", "data.undated")

#: The event field a committed transaction records the condition it applied under. It is re-keyed by that condition's
#: identity for the same reason a stored condition map is (:func:`canonical_capture`), so a difference inside one
#: record's data is addressed by WHICH condition it belongs to.
EVENT_CONDITION = "gate3_condition_after"


def _is_mark(identity: str) -> bool:
    """Whether a stored condition identity is a Forge Mark of some smith, in either of the shapes the table files."""
    text = str(identity)
    return text == MARK_CONDITION or text.startswith(MARK_CONDITION + ".") or text.startswith(MARK_CONDITION + "[")


def _condition_identity(row: dict[str, Any]) -> str:
    """One stored condition addressed by what it is: its condition id and the creature that placed it. Used for a
    stored condition map, a snapshot's copy of one, and the condition record inside a committed transaction alike."""
    return f"{row.get('condition_id')}[{row.get('source_actor_id')}]"


def _mark_condition_keys(captures: tuple[dict[str, Any], ...], artefact: str) -> list[str]:
    """The Forge Mark condition identities stored under ``artefact``, exactly as each capture holds them."""
    found: list[str] = []
    for capture in captures:
        for key in _walk_conditions(canonical_capture(capture.get(artefact))):
            if _is_mark(key) and key not in found:
                found.append(key)
    return sorted(found)


def _mark_event_identities(captures: tuple[dict[str, Any], ...]) -> list[str]:
    """The Forge Mark identities the committed transactions recorded, read from the events themselves.

    A journal record's condition is addressed by its own identity rather than by position, so a difference inside one
    record's data can only be allowed for the condition that record actually applied (:func:`canonical_capture`).
    """
    found: list[str] = []
    for capture in captures:
        for identity in _walk_event_conditions(capture.get("Journal.ndjson")):
            if _is_mark(identity) and identity not in found:
                found.append(identity)
    return sorted(found)


def _walk_conditions(node: Any) -> Iterable[str]:
    """Every stored condition key anywhere in a document, whoever holds it."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "conditions" and isinstance(value, dict):
                yield from value
            yield from _walk_conditions(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_conditions(item)


def _walk_event_conditions(node: Any) -> Iterable[str]:
    """The identity of every condition a committed event recorded, read from the events as they were saved."""
    if isinstance(node, dict):
        record = node.get(EVENT_CONDITION)
        if isinstance(record, dict) and isinstance(record.get("condition_id"), str):
            yield _condition_identity(record)
        for value in node.values():
            yield from _walk_event_conditions(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_event_conditions(item)


def smith_paths(*captures: dict[str, Any]) -> tuple[str, ...]:
    """The only differences the smith pair may show, as full paths.

    Each capture passed in is one side's whole stored data, so an allowance can name a file, an actor or a condition
    identity that actually exists rather than a folder or a pattern: a snapshot is compared whole like everything
    else, and only the named values inside it may differ. A snapshot that exists on one side only, or a resource,
    turn, position or effect value inside one that differs, comes back under ``unexpected``.
    """
    artefacts = sorted(set().union(*(set(capture) for capture in captures)) if captures else set())
    paths = [
        f"Typed_Character_Bundles.json[].action_catalog.{NEW_BUTTON}",
        f"Typed_Character_Bundles.json[].action_catalog.{DECLARATION_BUTTON}.{DECLARATION_FIELD}",
        f"Typed_Character_Bundles.json[].actor_template.action_ids.{NEW_BUTTON}",
        f"GenesisState.json.state.actors.{{actor}}.action_ids.{NEW_BUTTON}",
        *(f"GenesisState.json.state.actors.{{actor}}.conditions.{mark}.{field}"
          for mark in _mark_condition_keys(captures, "GenesisState.json") for field in MARK_ROW_FIELDS),
        *(f"Journal.ndjson[].events[].payload.{EVENT_CONDITION}.{mark}.{field}"
          for mark in _mark_event_identities(captures) for field in MARK_ROW_FIELDS),
    ]
    for name in sorted(artefacts):
        if name.startswith("Snapshots/") and name.endswith(".json"):
            paths.append(f"{name}.state.actors.{{actor}}.action_ids.{NEW_BUTTON}")
            paths.extend(f"{name}.state.actors.{{actor}}.conditions.{mark}.{field}"
                         for mark in _mark_condition_keys(captures, name) for field in MARK_ROW_FIELDS)
            # a snapshot records its own digests, which are taken over the very state and journal compared above
            for digest in SNAPSHOT_DIGESTS:
                paths.append(f"{name}.{digest}")
    return tuple(paths)


#: The digests a snapshot file records about itself, named one by one for the same reason as SMITH_DIGESTS.
SNAPSHOT_DIGESTS = ("canonical_state_sha256", "last_journal_record_sha256", "snapshot_sha256")

#: The digests written over the values above. Named one by one rather than as "any sha256", so a digest that changes
#: because of something else still fails.
SMITH_DIGESTS = (
    "Typed_Character_Bundles.json[].bundle_sha256",
    "FactoryIntegration.json.factory_match.bundles[].bundle_sha256",
    "Journal.ndjson[].pre_state_sha256",
    "Journal.ndjson[].post_state_sha256",
    "Journal.ndjson[].record_sha256",
    "Journal.ndjson[].previous_record_sha256",
    "GenesisState.json.canonical_state_sha256",
    "Manifest.json.file_identities.GenesisState.json",
    "Manifest.json.file_identities.Journal.ndjson",
    "Manifest.json.last_journal_record_sha256",
    "MatchLock.json.deterministic_payload_sha256",
    "MatchLock.json.genesis_payload_sha256",
    "MatchLock.json.genesis_state_sha256",
)

SMITH_PATHS = VOLATILE_PATHS + SMITH_DIGESTS

#: What each scenario is allowed to differ by. A scenario not named here allows nothing at all. The smith's own
#: differences are per-scenario (they name the snapshot files that exist), so the smith's allowance is asked for with
#: :func:`smith_paths`; this is the floor every one of them shares.
DECLARED = {"control": CONTROL_PATHS}


def canonical_capture(data: Any) -> Any:
    """Re-key a capture's stored data by identity instead of position, so only real value differences can show.

    A list of actions gaining one entry shifts every later entry along, a stored condition is keyed by an instance id
    that carries an event sequence number, and a committed transaction records the condition it applied as one value.
    Compared as saved, all three look like a rewrite of the whole list; compared as keyed here, they are one new key
    and the same values everywhere else -- and a difference inside one record's data is addressed by WHICH condition
    the record is about, so an allowance naming one condition cannot cover another's. Nothing is dropped or rewritten
    -- every value is still compared, it is only addressed by what it *is* rather than where it happened to sit.
    """
    if isinstance(data, list):
        return [canonical_capture(item) for item in data]
    if not isinstance(data, dict):
        return data
    out = {key: canonical_capture(value) for key, value in data.items()}
    catalogue = out.get("action_catalog")
    if isinstance(catalogue, list):
        out["action_catalog"] = _keyed(catalogue, lambda row: row.get("source_definition_id"))
    for key in ("action_ids", "learned_talent_record_ids"):
        listed = out.get(key)
        if isinstance(listed, list) and all(isinstance(item, str) for item in listed):
            out[key] = {item: None for item in listed}
    conditions = out.get("conditions")
    if isinstance(conditions, dict) and all(isinstance(row, dict) and "condition_id" in row
                                           for row in conditions.values()):
        out["conditions"] = _keyed(list(conditions.values()), _condition_identity)
    recorded = out.get(EVENT_CONDITION)
    if isinstance(recorded, dict) and isinstance(recorded.get("condition_id"), str):
        out[EVENT_CONDITION] = _keyed([recorded], _condition_identity)
    return out


def _keyed(rows: list[Any], key) -> dict[str, Any]:
    """A list as ``{identity: row}``, which is what a difference path is compared on. Two rows sharing an identity
    keep both, under a numbered second key, because a duplicate is itself a difference worth seeing."""
    out: dict[str, Any] = {}
    for row in rows:
        name = str(key(row))
        if name in out:
            name = f"{name}#{sum(1 for other in out if other.split('#')[0] == name)}"
        out[name] = canonical_capture(row)
    return out


def capture(path: Path, scenario: str, steps: int = 10) -> dict:
    """Play one scenario's fight through the real table from a fixed seed and report where its journal landed."""
    settings = SCENARIOS[scenario]
    combat, table, mid = fight(path, owned=settings["owned"], seed=settings["seed"], kit=KIT, cl=15)
    for actor in (LEFT, RIGHT):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    played = 0
    for _ in range(steps):
        state = table.state(mid)
        if (state.get("menu") or {}) == {}:
            break
        result = table.auto_step(mid, state["last_sequence"])
        assert result["status"] == "COMMITTED", result
        played += 1
        reload(combat, mid)
    match = next(path.rglob("GenesisState.json")).parent
    assert commits(match), "the scenario played no committed transaction"
    return {"scenario": scenario, "match": str(match), "ai_steps": played}


def commits(match: Path) -> list[dict]:
    """Each committed transaction of a journal, reduced to what the readable summary reports."""
    rows = [json.loads(line) for line in (match / "Journal.ndjson").read_text().splitlines()]
    out = []
    for row in rows:
        if row["record_type"] != "COMMIT":
            continue
        events = row["events"]
        out.append({
            "sequence": row["record_sequence"],
            "events": [event["event_type"] for event in events],
            "conditions": [str(event["payload"].get("condition_id")) for event in events
                           if event["event_type"] == "CONDITION_APPLIED"],
            "damage": [str(event["payload"].get("damage_type")) for event in events
                       if event["event_type"] == "DAMAGE_COMMITTED"],
            "spent": [str(event["payload"].get("resource_id")) for event in events
                      if event["event_type"] == "RESOURCE_SPENT"],
            "riders": [str(event["payload"]["rider"]) for event in events
                       if event["event_type"] == "GM_RIDER" and event["payload"].get("rider")],
        })
    return out


def journal_sha256(match: Path) -> str:
    """SHA-256 over the whole journal, so "byte-identical" is checkable rather than asserted."""
    return hashlib.sha256((match / "Journal.ndjson").read_bytes()).hexdigest()


def journal_differences(baseline: Path, tip: Path) -> dict:
    """Line two paired captures up transaction by transaction and report every difference in the readable summary."""
    old, new = commits(baseline), commits(tip)
    differences = []
    for index, (before, after) in enumerate(zip(old, new)):
        changed = {key: [before[key], after[key]] for key in after if before[key] != after[key]}
        if changed:
            differences.append({"transaction": index, "baseline_sequence": before["sequence"],
                                "tip_sequence": after["sequence"], "changed": changed})
    totals = {}
    for key in ("conditions", "damage", "riders", "spent"):
        before = sorted(item for commit in old for item in commit[key])
        after = sorted(item for commit in new for item in commit[key])
        totals[key] = {"gained": sorted(set(after) - set(before)), "lost": sorted(set(before) - set(after))}
    return {
        "baseline_journal_sha256": journal_sha256(baseline),
        "tip_journal_sha256": journal_sha256(tip),
        "byte_identical": journal_sha256(baseline) == journal_sha256(tip),
        "baseline_transactions": len(old),
        "tip_transactions": len(new),
        "transaction_counts_match": len(old) == len(new),
        "totals": totals,
        "differences": differences,
    }


# --------------------------------------------------------------------------- the whole saved data, one path at a time
def stored_data(match: Path) -> dict[str, Any]:
    """Every value the fight wrote to disk, parsed: each journal line as its own record, each JSON file whole.

    Reading everything (rather than the handful of fields :func:`commits` summarises) is the point: a difference in
    a field nobody thought to check is still a difference.
    """
    out: dict[str, Any] = {}
    for path in sorted(match.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        name = path.relative_to(match).as_posix()
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".ndjson":
            out[name] = [json.loads(line) for line in text.splitlines() if line.strip()]
        elif path.suffix == ".json":
            out[name] = json.loads(text)
        else:
            out[name] = text
    return out


def value_differences(before: Any, after: Any, path: str = "",
                      out: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """Every differing stored value between two parsed documents, as ``(path, description)`` pairs.

    A dict compares key by key, a list position by position (and reports a length change), and anything else is
    compared whole. Keys present on one side only are reported too, so nothing is skipped by not existing.

    The path is kept separate from the description on purpose: :func:`full_differences` matches an allowed path
    against the *path*, so a declaration cannot be satisfied by a value that merely starts with the same text.
    """
    out = [] if out is None else out
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            where = f"{path}.{key}" if path else str(key)
            if key not in before:
                out.append((where, f"only in tip = {_short(after[key])}"))
            elif key not in after:
                out.append((where, f"only in baseline = {_short(before[key])}"))
            else:
                value_differences(before[key], after[key], where, out)
    elif isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            out.append((path, f"length {len(before)} -> {len(after)}"))
        for index, (one, other) in enumerate(zip(before, after)):
            value_differences(one, other, f"{path}[{index}]", out)
    elif before != after:
        out.append((path, f"{_short(before)} -> {_short(after)}"))
    return out


def render(pairs: Iterable[tuple[str, str]]) -> list[str]:
    """The ``path: description`` lines a person reads."""
    return [f"{path}: {detail}" for path, detail in pairs]


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def normalise_path(path: str) -> str:
    """A difference path with every list position written as ``[]``.

    Two captures of the same fight store the same records in the same order, so a position is noise in a *declaration*
    -- "the per-mark deadlines differ, in whichever transaction stored them" is the claim worth making, and it does
    not silently widen as a fight gets longer. Field names are untouched, so a different field still fails.
    """
    return re.sub(r"\[\d+\]", "[]", path)


def full_differences(baseline: Path, tip: Path, *, expected: Iterable[str] = ()) -> dict:
    """Compare the two fights' whole saved data and split the differences into allowed and unexpected.

    ``expected`` names the only differences the caller allows, as path prefixes (an exact path, or anything under
    it). A difference nobody named is returned under ``unexpected``, which is what a test asserts is empty; the
    comparison itself is deliberately wide, so a caller cannot pass it by summarising less.

    ``expected`` is also checked against what actually differed, and an allowance that matched nothing is reported
    under ``unused`` -- otherwise a declaration could rot into naming a difference the fix no longer makes, or one
    that never existed, and still read as a pass.
    """
    left = {name: canonical_capture(value) for name, value in stored_data(baseline).items()}
    right = {name: canonical_capture(value) for name, value in stored_data(tip).items()}
    report = document_differences(left, right, expected=expected)
    report["baseline_artefacts"] = sorted(left)
    report["compared_artefacts"] = sorted(set(left) & set(right))
    return report


def document_differences(left: dict[str, Any], right: dict[str, Any], *, expected: Iterable[str] = ()) -> dict:
    """Split two already-parsed stored-data mappings into allowed and unexpected differences.

    :func:`full_differences` reads two capture folders and calls this; it is public on its own so a regression can
    hand it two made-up documents and prove what it rejects, without needing a pair of captures on disk.
    """
    found: list[tuple[str, str]] = []
    for name in sorted(set(left) | set(right)):
        if name not in left:
            found.append((name, "only in tip"))
        elif name not in right:
            found.append((name, "only in baseline"))
        else:
            value_differences(left[name], right[name], name, found)
    allowed = [pair for pair in found if any(_covers(prefix, pair[0]) for prefix in expected)]
    return {
        "allowed_prefixes": list(expected),
        "differences": render(found),
        "allowed": render(allowed),
        "unexpected": render([pair for pair in found if pair not in allowed]),
        "unused": [prefix for prefix in expected
                   if not any(_covers(prefix, path) for path, _detail in found)],
    }


def _covers(prefix: str, path: str) -> bool:
    """Whether an allowed path prefix covers this difference's path.

    Exact, or a parent of it, ignoring list positions. A ``{actor}`` or ``{owner}`` placeholder in a prefix matches
    exactly one key at that position -- lazily up to the next separator when bare, or up to the bracket when inside one
    -- which is how an allowance names "the fighter's own saved state" without hard-coding the entity id the table
    happened to mint, and still cannot swallow a whole subtree the way a bare folder name could. It matches ONE key:
    an identity that means something (a condition, an actor) is named by name, read out of the captures, because a
    wildcard there would cover every other condition's row as well.
    """
    prefix = normalise_path(prefix).rstrip(".")
    path = normalise_path(path)
    if not _PLACEHOLDER.search(prefix):
        return (path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "[")
                or path.startswith(prefix + "/"))

    def one_key(match: re.Match) -> str:
        return r"[^\]]+" if prefix[match.end():].startswith("]") else r"[^/\[]+?"

    out, last = "", 0
    for piece, found in zip(_PLACEHOLDER.split(prefix), _PLACEHOLDER.finditer(prefix)):
        out += re.escape(prefix[last:found.start()]) + one_key(found)
        last = found.end()
    out += re.escape(prefix[last:])
    return re.fullmatch(out + r"(?:\.|\[|/)?.*", path) is not None


#: One key's worth of "whatever identity is there": the actor or the mark owner a capture's own table minted.
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        print(json.dumps(capture(Path(sys.argv[2]).resolve(), sys.argv[3])))
    elif sys.argv[1] == "compare":
        print(json.dumps(full_differences(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve(),
                                          expected=sys.argv[4:]), indent=2))
    else:
        print(json.dumps(journal_differences(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()), indent=2))