"""Validate d1 training shards against the record contract.

Schema check: every record has the fields the contract needs and the right
types -- `state` and `alias_payload` must always be present (never null),
`label` must name an executed offered alias with a bound payload, and
`teacher_label`, when set, must name an alias bound to the built-in pick.

Teacher-contamination check: no raw internal payload value from `chosen` or
`built_in_pick` (the engine's own candidate-id strings) may appear verbatim
in the model-visible `state` text. Those fields are binding/evaluator data,
kept out of the model's reach; a leak there would mean the model could read
off its own answer or the teacher's. This check is unconditional for the
literal hint names themselves ("built_in_pick", "teacher_label") -- those
would tip off that a label is the teacher's even without leaking a payload
value, so there is no length threshold for them, unlike the raw-value check
below (`MIN_SECRET_LENGTH`-gated, since short payload strings like "USE" or
"A" are also legitimate menu/enum text and would false-positive otherwise).

Binding-consistency check: `label`'s bound payload in `alias_payload` must
structurally equal `chosen` (TURN: `alias_payload[label]["plan"] == chosen`;
REACTION: direct dict equality) -- the field naming what was offered and the
field recording what was taken must never disagree. And whenever
`teacher_label` is set (i.e. the built-in's own pick was actually offered,
not a fallback), `chosen` must begin with -- TURN: `chosen[0] ==
built_in_pick`; REACTION: `chosen == built_in_pick` -- since the self-play
provider always executes the true built-in pick when it is offered. Neither
teacher check applies when `teacher_label` is `None` (the documented case
where the built-in's pick was not on the menu). An absent executed label
is invalid and the collector drops that record.

No-hidden-info check (structural, see limits below): a position token
"(x,y)" may only appear on a line build_prompt() is known to put one on --
an actor's own HP/Threat/Ally/Defeated line (agent_seats/choices.py
build_prompt, fed only by own_view's already-perception-filtered actor
list) or an offered option/shared-effect line (a candidate's own
destination, never another actor's hidden position). Any position token on
any other line would mean something outside that filtered view leaked into
the model input.

Limit: this is a structural check on the stored text, not an independent
re-derivation of what the acting creature actually perceived at decision
time -- it would accept a record that dropped the position line for a
hidden creature's name entirely while leaving some other stray position
text, for instance. It catches a regression in this file's own output
pipeline (the thing this script and the collector both touch), not every
conceivable perception bug in the engine's own redaction. End-to-end
perception correctness -- a genuinely hidden creature never appearing by
name or position -- is covered separately by a real decision captured
through SeatRunner in tests/test_d1_collect.py.

Usage: d1_validate.py SHARD.jsonl.gz [SHARD.jsonl.gz ...]
Exits 1 and prints every problem found; exits 0 and prints a count when clean.
"""
import gzip
import json
import re
import sys

REQUIRED_KEYS = {"record_id", "lineage_id", "match_id", "decision_id", "kind", "engine_revision",
                 "menu_hash", "original_menu_hash", "state", "options", "alias_payload", "label",
                 "teacher_label", "chosen", "built_in_pick", "fallback", "origin"}
POSITION = re.compile(r"\(-?\d+,\s*-?\d+\)")
# The fighter's own situation lines (agent_seats.menu_pages.tactical_situation and
# the "Plan so far" line of ranked pages) carry only the acting fighter's own
# position and its own legal move destinations, never another creature's position.
ALLOWED_POSITION_LINE = re.compile(
    r"^(?:[A-L]\)|HP:|Threat:|Ally:|Defeated:|For "
    r"|You at \(-?\d+,\s*-?\d+\), -?\d+ ft above ground; squares are 5 ft\.$"
    r"|Plan so far: )")
MIN_SECRET_LENGTH = 8  # shorter strings ("USE", "A", "DECLINE") are legitimate menu/enum text
HINT_NAMES = ("built_in_pick", "teacher_label")  # never legitimate menu/enum text; no length threshold


def _payload_strings(value):
    """Every string leaf inside a (possibly nested) chosen/built_in_pick payload."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        found = set()
        for v in value.values():
            found |= _payload_strings(v)
        return found
    if isinstance(value, list):
        found = set()
        for v in value:
            found |= _payload_strings(v)
        return found
    return set()


def _label_matches_chosen(record, label):
    """alias_payload[label] -- what was offered under that letter -- must
    structurally equal chosen -- what was actually taken."""
    payload = record["alias_payload"].get(label)
    chosen = record.get("chosen")
    if record["kind"] == "TURN":
        return isinstance(payload, dict) and payload.get("plan") == chosen
    return payload == chosen


def _teacher_matches_built_in_pick(record):
    """When teacher_label is set, the built-in's own pick was actually
    offered (not a fallback), and the self-play provider always executes
    that true pick -- so chosen must begin with built_in_pick."""
    chosen = record.get("chosen")
    built_in_pick = record.get("built_in_pick")
    if record["kind"] == "TURN":
        return isinstance(chosen, list) and bool(chosen) and chosen[0] == built_in_pick
    return chosen == built_in_pick


def validate_record(record):
    problems = []
    missing = REQUIRED_KEYS - set(record)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
        return problems
    if record["kind"] not in {"TURN", "REACTION"}:
        problems.append(f"unexpected kind: {record['kind']!r}")
    state = record.get("state")
    options = record.get("options")
    alias_payload = record.get("alias_payload")
    # Truncation shortens state/options; it never makes them absent or the
    # wrong type. Checked unconditionally, not only on an untruncated record.
    if not isinstance(state, str) or not state:
        problems.append("state must be a nonempty string")
    if not isinstance(alias_payload, dict) or not alias_payload:
        problems.append("alias_payload must be a nonempty dict")
    if not isinstance(options, dict) or not options:
        problems.append("options must be a nonempty dict")
    else:
        if not isinstance(record.get("label"), str) or not record["label"]:
            problems.append("label must name the executed offered option")
        for field in ("label", "teacher_label"):
            value = record.get(field)
            if value is not None and value not in options:
                problems.append(f"{field} {value!r} is not an offered option")
            if value is not None and isinstance(alias_payload, dict) and value not in alias_payload:
                problems.append(f"{field} {value!r} has no bound payload")
        label = record.get("label")
        if label is not None and isinstance(alias_payload, dict) and label in alias_payload:
            if not _label_matches_chosen(record, label):
                problems.append(f"label {label!r}'s bound payload does not match chosen")
        if record.get("teacher_label") is not None:
            if not _teacher_matches_built_in_pick(record):
                problems.append("teacher_label is set but chosen does not begin with built_in_pick")
            teacher = record["teacher_label"]
            if isinstance(alias_payload, dict) and teacher in alias_payload:
                payload = alias_payload[teacher]
                if record["kind"] == "TURN":
                    plan = payload.get("plan") if isinstance(payload, dict) else None
                    matches = isinstance(plan, list) and bool(plan) and plan[0] == record["built_in_pick"]
                else:
                    matches = payload == record["built_in_pick"]
                if not matches:
                    problems.append("teacher_label's bound payload does not match built_in_pick")
    if isinstance(state, str):
        for line in state.splitlines():
            if POSITION.search(line) and not ALLOWED_POSITION_LINE.match(line):
                problems.append(f"position token outside an allowed line: {line!r}")
        secrets = set()
        for field in ("chosen", "built_in_pick"):
            secrets |= {s for s in _payload_strings(record.get(field)) if len(s) >= MIN_SECRET_LENGTH}
        for secret in secrets:
            if secret in state:
                problems.append(f"internal {secret!r} from chosen/built_in_pick leaked into state")
    # Both state and option text are model input; hint names are forbidden
    # even when the raw pick is a single character.
    for field, value in (("state", state), ("options", options)):
        visible_text = json.dumps(value, ensure_ascii=False).lower()
        for hint in HINT_NAMES:
            if hint in visible_text:
                problems.append(f"literal teacher-hint name {hint!r} found in {field}")
    return problems


def main(argv=None):
    paths = argv if argv is not None else sys.argv[1:]
    if not paths:
        print("usage: d1_validate.py SHARD.jsonl.gz [...]", file=sys.stderr)
        return 2
    total, bad = 0, []
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                total += 1
                record = json.loads(line)
                problems = validate_record(record)
                if problems:
                    bad.append((path, line_no, record.get("record_id"), problems))
    if bad:
        for path, line_no, record_id, problems in bad:
            print(f"{path}:{line_no} {record_id}: {'; '.join(problems)}")
        print(f"FAIL: {len(bad)} of {total} records failed validation")
        return 1
    print(f"PASS: {total} records validated across {len(paths)} shard(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
