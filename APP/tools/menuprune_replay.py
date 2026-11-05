#!/usr/bin/env python3
"""Explicit MENUPRUNE1 offline replay. Never changes registry rows or fight state.

Old seat_decisions rows contain only a *shortlist*, not a reconstructible state.
Supply --states JSONL keyed by match_id/decision_id/attempt, with a "state":
{view, legal, ranked, scores, provider, limit, reference_top_k, useful_keys}.
Provider is the ORIGINAL row, not the model endpoint used for replay. Optional
pages holds RankedPages attributes plus selected_steps for a navigation frame.
Inline "state" uses the same contract. --captures can recover historical TURN
boundaries from copied match archives with score_seat_tactics.capture_menus.
Missing state, ranking references, useful labels and reconstruction drift remain
visible; a prompt is never parsed into imaginary omitted legal options.

Only the lead runs this tool, through the host queue. See menuprune.md.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_seats.choices import (build_prompt, parse_letter, reaction_options,
                                 turn_options, TurnOptions)
from agent_seats.d1 import APP_LIMIT, INSTRUCTIONS
from agent_seats.menu_pages import RankedPages, choice_frame
from agent_seats.protocol import guidance_block, with_guidance
from agent_seats.providers import choices_settings
from provider_transport import urllib_json

ARMS = ("A", "B", "C")


def identity(row):
    # Ranked navigation/repair frames can share decision_id.
    return (row.get("match_id", ""), row["decision_id"], row.get("attempt", 0))


def canonical(answer):
    return json.dumps(answer, sort_keys=True, separators=(",", ":"))


def fingerprint(state):
    # Legal-map insertion order is an input to the selector, not incidental
    # JSON formatting. Preserve it when checking paired/resumed states.
    payload = {"state": state, "legal_order": list(state.get("legal", {}))}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def arm_settings(provider, arm):
    """Experiment configuration is deliberately NOT accepted by live registries."""
    budget, maximum = choices_settings(provider)
    if arm not in ARMS:
        raise ValueError("Unknown experiment arm")
    return (budget, maximum) if arm == "A" else (budget, 12) if arm == "B" else (None, "all")


def frame(row, state, arm):
    """Rebuild one exact response binding; C cannot silently shed alternatives."""
    provider = state["provider"]
    budget, maximum = arm_settings(provider, arm)
    view, legal = state["view"], state["legal"]
    builtin = row["built_in_pick"]
    kind = row["kind"].upper()
    guidance = guidance_block(provider.get("primer", "")) if provider.get("kind") != "d1" else ""
    repair = state.get("repair")
    if state.get("pages") is not None:
        # Existing navigation is explicitly excluded from C's no-cut promise.
        # The runner always exposes one active option per choices frame.
        pages = RankedPages(legal, state.get("ranked", ()), builtin, 1)
        pages.first = pages.first[:1]
        for key, value in state["pages"].items():
            if key not in {"page_number", "detail_offset", "rule_offsets", "situation_offset",
                           "history", "remaining", "first"}:
                raise ValueError("Unknown navigation snapshot attribute")
            setattr(pages, key, deepcopy(value))
        frame_budget = choices_settings(provider)[0] if budget is None else budget
        frame_budget -= len(guidance.encode())
        prompt, offered, _ = choice_frame(view, pages, frame_budget,
                                         state.get("selected_steps", ()), repair)
        return with_guidance(prompt, guidance), offered
    experiment = "menuprune1" if arm == "C" else None
    # C's byte budget changes packing, not plan composition. Generate with the
    # original byte budget, then fit the complete result without removing rows.
    generation_budget = provider.get("choices_bytes", 800)
    if kind in {"TURN", "STEP"}:
        options = turn_options(view, legal, builtin, state.get("ranked", ()),
                               state.get("scores"), state.get("limit", 3),
                               generation_budget, maximum, experiment=experiment)
    elif kind == "REACTION":
        options = reaction_options(legal, builtin, experiment=experiment)
    else:
        raise ValueError("Unknown decision kind")
    if arm != "A" and kind in {"TURN", "STEP"}:
        # Keep the incumbent order for every shared plan. C also retains
        # incumbent compositions: changing max_options must not replace a
        # plan before we can measure the effect of offering more plans.
        original = turn_options(view, legal, builtin, state.get("ranked", ()),
                                state.get("scores"), state.get("limit", 3),
                                generation_budget, provider.get("max_options", 6))
        allowed = {canonical(o.answer) for o in options}
        ordered, seen = [], set()
        for option in [*original, *options]:
            key = canonical(option.answer)
            if key in seen or (arm == "B" and key not in allowed):
                continue
            ordered.append(option)
            seen.add(key)
        # End stays at its incumbent end of the menu, not between old and new.
        if not is_end(ordered[0].answer, legal):
            ordered.sort(key=lambda o: is_end(o.answer, legal))
        options = TurnOptions(ordered, getattr(options, "tactical_purposes", {}),
                              getattr(options, "flight_keys", ()))
    if arm == "C":
        # Includes descriptions and shared facts; no fixed option/byte cutoff.
        budget = max(4800, 4 * len(canonical([view, legal, options]).encode()) + 4096)
    return build_prompt(view, options, kind, legal, repair, budget, maximum,
                        guidance, experiment=experiment)


def references(row, state, offered):
    answers = list(offered.values())
    first_keys = {a["plan"][0] for a in answers if a.get("plan")}
    builtin = row["built_in_pick"]
    builtin_present = (builtin in first_keys if isinstance(builtin, str)
                       else builtin in answers)
    result = {"built_in_id": row.get("built_in_id"),
              "built_in_in_menu": builtin_present}
    for tier in ("MASTERMIND", "TRICKY"):
        expected = state.get("reference_top_k", {}).get(tier)
        flags = None if expected is None else [
            (a in first_keys if isinstance(a, str) else a in answers) for a in expected]
        result[tier.lower() + "_top_k_in_menu"] = flags
    return result


def is_end(answer, legal):
    plan = answer.get("plan", ())
    return bool(plan) and all(legal.get(k, {}).get("action") == "End turn" for k in plan)


def useful_offered(state, offered):
    """Use recorded positive-scoring first steps, never 'non-END means good'.

    Explicit useful_keys is preferred. Without a recorded evaluation this is
    unknown, not false: legality alone does not demonstrate a useful action.
    """
    keys = state.get("useful_keys")
    if keys is None:
        return None
    for answer in offered.values():
        if answer.get("selection") == "USE" and answer in state.get("useful_reactions", []):
            return True
        if answer.get("plan") and answer["plan"][0] in keys:
            return True
    return False


def replay_one(row, state, arm, model, client):
    """One call at most; errors are observations, not silently repaired picks."""
    result = {"model": model, "arm": arm, "decision_id": row["decision_id"],
              "match_id": row.get("match_id", ""), "attempt": row.get("attempt", 0),
              "kind": row["kind"].upper(), "geometry": (state or {}).get("geometry", "unknown"),
              "menu_size": None, "menu_bytes": None, "candidate_generation_ms": None,
              "inference_ms": None, "pick": None, "probabilities": None,
              "end_while_useful": None, "only_in_larger_menu": None,
              "fallback": False, "error": None, "built_in_in_menu": None,
              "mastermind_top_k_in_menu": None, "tricky_top_k_in_menu": None}
    started = time.perf_counter()
    try:
        if state is None:
            raise ValueError("Missing exact state: packed seat prompts cannot reconstruct omitted options")
        result["state_sha256"] = fingerprint(state)
        result["reconstruction"] = state.get("reconstruction", "exact-state")
        prompt, offered = frame(row, state, arm)
        result["candidate_generation_ms"] = (time.perf_counter() - started) * 1000
        result.update(menu_size=len(offered), menu_bytes=len(prompt.encode()),
                      menu_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                      **references(row, state, offered))
        # Build A for comparison, outside the arm's timed candidate generation.
        a_prompt, a_offered = (prompt, offered) if arm == "A" else frame(row, state, "A")
        result["a_byte_identical"] = a_prompt == row.get("prompt")
        if not result["a_byte_identical"]:
            raise ValueError("Reconstructed A prompt differs from recorded prompt; refuse confounded replay")
        result["offered_answers"] = list(offered.values())
        useful = useful_offered(state, offered)
        result["useful_offered"] = useful
        inference_started = time.perf_counter()
        try:
            reply = client(prompt, offered, state["provider"])
        finally:
            result["inference_ms"] = (time.perf_counter() - inference_started) * 1000
        token = reply["choice"].strip()
        if token in offered:
            picked = offered[token]
        else:
            # Preserve live letter recovery for shared A..Z choices in C too;
            # stricter parsing in C would confound menu size with fallbacks.
            picked = parse_letter(token, offered)
        result.update(pick=picked, choice=token, probabilities=reply.get("probabilities"),
                      usage=reply.get("usage"))
        result["end_while_useful"] = None if useful is None else is_end(picked, state["legal"]) and useful
        result["only_in_larger_menu"] = arm != "A" and picked not in a_offered.values()
        # Detect selector ordering confounds; don't mistake them for size-only effects.
        a_order = [canonical(a) for a in a_offered.values()]
        order = [canonical(a) for a in offered.values()]
        shared = set(a_order) & set(order)
        result["common_order_changed"] = ([a for a in a_order if a in shared] !=
                                          [a for a in order if a in shared])
    except Exception as exc:
        if result["candidate_generation_ms"] is None:
            result["candidate_generation_ms"] = (time.perf_counter() - started) * 1000
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["fallback"] = True
        # A failed inference has no experimental model pick. Record what the
        # live runner would fall back to separately, never use it for agreement.
        result["fallback_pick"] = row.get("built_in_pick")
    return result


def decision_payload(prompt, offered):
    """Full-menu counterpart of choices.decision_payload, including IDs > L."""
    state, criteria, shared = [], {}, []
    for line in prompt.splitlines():
        match = re.fullmatch(r"([A-Z]|P[0-9]+)\) (.+)", line)
        common = re.fullmatch(r"For ((?:[A-Z]|P[0-9]+)(?:, (?:[A-Z]|P[0-9]+))*): (.+)", line)
        if match:
            criteria[match[1]] = match[2]
        elif common:
            shared.append((common[1].split(", "), common[2]))
        elif not line.startswith("Reply "):
            state.append(line)
    if set(criteria) != set(offered):
        raise ValueError("Prompt option bindings are incomplete")
    for ids, effect in shared:
        for key in ids:
            criteria[key] += "; " + effect
    return {"state": "\n".join(state), "options": criteria}


class ModelClient:
    """Experiment transports only; no changes to live protocol/defaults.

    openai uses BASE/chat/completions (include /v1 in BASE when required).
    d1 uses BASE/decide with state/options. local-app and systemone use the
    named-question session/decide protocol; only local-app has the 6000 cap.
    One /decide or chat request per frame, no repair or automatic retry.
    """
    def __init__(self, endpoint, protocol, model, timeout=60, key_env=None):
        url = urllib.parse.urlsplit(endpoint)
        if (url.scheme not in {"http", "https"} or not url.hostname or
                url.username or url.password or url.query or url.fragment):
            raise ValueError("Endpoint must be HTTP(S), without credentials or query")
        self.endpoint, self.protocol, self.model = endpoint.rstrip("/"), protocol, model
        self.timeout, self.key_env, self.token = timeout, key_env, None
        self.last_request = 0.0

    def request(self, path, body=None, headers=None):
        # All requests, session included, are <= 5/s. No live model in tests.
        time.sleep(max(0, .2 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = urllib.request.Request(self.endpoint + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json", **(headers or {})})
        return urllib_json(request, self.timeout, too_large="Experiment model reply too large")

    def __call__(self, prompt, offered, provider):
        if self.protocol == "openai":
            headers = {}
            if self.key_env:
                headers["Authorization"] = "Bearer " + os.environ[self.key_env]
            reply = self.request("/chat/completions", {"model": self.model,
                "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                "seed": 202, "max_tokens": 16}, headers)
            return {"choice": reply["choices"][0]["message"]["content"], "usage": reply.get("usage")}
        payload = decision_payload(prompt, offered)
        if self.protocol in {"local-app", "systemone"}:
            primer = provider.get("primer", "")
            questions = {"action": {"type": "choice", "instructions":
                INSTRUCTIONS + ("\n" + guidance_block(primer).rstrip() if primer else ""),
                "criteria": payload["options"]}}
            if self.protocol == "local-app" and len(json.dumps([payload["state"], questions])) > APP_LIMIT:
                raise ValueError("Full frame exceeds local-app 6000-character cap; no request sent")
            if self.token is None:
                self.token = self.request("/session")["token"]
            reply = self.request("/decide", {"state": payload["state"], "questions": questions},
                                 {"X-D1-Token": self.token})["answers"]["action"]
        else:
            if provider.get("primer"):
                payload["state"] = guidance_block(provider["primer"]) + payload["state"]
            reply = self.request("/decide", payload)
        if reply.get("choice") not in offered:
            raise ValueError("Decision endpoint selected an unoffered ID")
        probabilities = reply.get("probabilities")
        if (not isinstance(probabilities, dict) or set(probabilities) != set(offered) or
            any(type(p) not in {int, float} or not math.isfinite(p) or not 0 <= p <= 1
                for p in probabilities.values()) or
            not math.isclose(sum(probabilities.values()), 1, abs_tol=.02)):
            raise ValueError("Invalid decision probabilities")
        return {"choice": reply["choice"], "probabilities": probabilities}


def jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def load_states(path):
    states = {}
    if path:
        for row in jsonl(path):
            key = identity(row)
            if key in states:
                raise ValueError("Duplicate exact state identity")
            states[key] = row["state"]
    return states


def archive_states(root, records, providers):
    """Optional historical TURN re-derivation. Never opens live state.

    capture_menus verifies journal hashes. Its older projection may differ from
    today's ranking/expansion/Dao: replay_one MUST verify recorded A bytes.
    Unsupported reaction/STEP boundaries are retained as missing-state errors.
    """
    from tools.score_seat_tactics import capture_menus
    from combat.gate3_storage import resolve_match_directory
    states = {}
    for mid in dict.fromkeys(r.get("match_id") for r in records):
        if not mid or Path(mid).name != mid:
            raise ValueError("Unsafe capture match id")
        directory, _ = resolve_match_directory(Path(root), mid)
        if not directory.is_dir():
            continue  # Missing copied archive becomes a missing-state result.
        by_id = {r["decision_id"]: r for r in records if r.get("match_id") == mid}
        for view, legal, boundary in capture_menus(directory):
            did = boundary.get("decision_id")
            if did not in by_id:
                continue
            record = by_id[did]
            ranking = boundary.get("dao_policy_top2", [])
            state = {"view": view, "legal": legal,
                     "ranked": ranking, "provider": providers[record["provider_id"]],
                     "limit": 3, "reconstruction": "archive-turn"}
            states[identity(record)] = state
    return states


def check_owner_idle(matches):
    """Read only genesis/commit receipts, never instantiate a repairing store.

    Conservatively refuses *any* unfinished, unpaused saved fight, including AI
    seats. Missing/incomplete/corrupt data fails closed. Check before EACH call.
    """
    matches = Path(matches)
    if not matches.is_dir():
        raise RuntimeError("Live matches directory unavailable; cannot establish owner idle")
    for directory in matches.iterdir():
        if not directory.is_dir():
            continue
        metadata = json.loads((directory / "FactoryIntegration.json").read_text())
        if metadata.get("paused") is True:
            continue
        state = json.loads((directory / "GenesisState.json").read_text())["state"]
        terminal = state.get("terminal_result")
        journal = directory / "Journal.ndjson"
        for record in jsonl(journal):
            if record.get("record_type") == "COMMIT":
                if "terminal_result" not in record:
                    raise RuntimeError("Cannot establish fight completion from commit")
                terminal = record["terminal_result"]
        if terminal is None:
            raise RuntimeError("Active owner fight; experiment refused")


def psi_full(path):
    for line in Path(path).read_text().splitlines():
        if line.startswith("full "):
            value = float(dict(word.split("=") for word in line.split()[1:])["avg60"])
            if not math.isfinite(value) or value < 0:
                break
            return value
    raise RuntimeError("IO PSI full avg60 unavailable")


def wait_idle(matches, psi_paths, *, sleep=time.sleep):
    while True:
        check_owner_idle(matches)
        if all(psi_full(path) <= 5 for path in psi_paths):
            return
        sleep(5)


def select_records(records, maximum):
    """Deterministic round-robin kind/geometry strata, identical across arms."""
    buckets = defaultdict(list)
    seen = set()
    for row in records:
        key = identity(row)
        if key in seen:
            continue
        seen.add(key)
        buckets[(row["kind"], row.get("state", {}).get("geometry", "unknown"))].append(row)
    selected = []
    while buckets and len(selected) < maximum:
        for key in list(sorted(buckets)):
            selected.append(buckets[key].pop(0))
            if not buckets[key]:
                del buckets[key]
            if len(selected) == maximum:
                break
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--states", type=Path)
    parser.add_argument("--captures", type=Path, help="COPIED match archives, not live matches")
    parser.add_argument("--providers", type=Path, help="Original provider registry COPY for archive reconstruction")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--protocol", choices=("openai", "d1", "local-app", "systemone"), required=True)
    parser.add_argument("--model", required=True, help="Stable model identifier, also sent to OpenAI endpoint")
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-decisions", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--key-env")
    parser.add_argument("--live-matches", type=Path, required=True, help="Read-only owner fight safety check")
    parser.add_argument("--psi", type=Path, action="append", help="Local and mounted remote IO PSI files; default /proc/pressure/io")
    args = parser.parse_args(argv)
    if not 1 <= args.max_decisions <= 200 or not 0 < args.timeout <= 180:
        parser.error("Caps: 1..200 decisions, timeout 0..180 seconds")
    os.setpriority(os.PRIO_PROCESS, 0, 19)
    wait_idle(args.live_matches, args.psi or [Path("/proc/pressure/io")])
    states = load_states(args.states)
    records = list(jsonl(args.decisions))
    if args.captures:
        if args.captures.resolve() == args.live_matches.resolve():
            parser.error("--captures must be an offline COPY, never live matches")
        if not args.providers:
            parser.error("--captures requires the original --providers COPY")
        from agent_seats.providers import ProviderRegistry
        states.update(archive_states(args.captures, records, ProviderRegistry(args.providers).load()))
    for row in records:
        if identity(row) in states:
            row["state"] = states[identity(row)]
    records = select_records(records, args.max_decisions)
    done = {}
    if args.out.exists():
        for previous in jsonl(args.out):
            if previous["model"] == args.model and previous["arm"] == args.arm:
                if identity(previous) in done:
                    raise ValueError("Duplicate output identity")
                done[identity(previous)] = previous
    client = ModelClient(args.endpoint, args.protocol, args.model, args.timeout, args.key_env)
    def guarded_client(prompt, offered, provider):
        wait_idle(args.live_matches, args.psi or [Path("/proc/pressure/io")])
        return client(prompt, offered, provider)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as output:
        for row in records:
            if identity(row) in done:
                previous = done[identity(row)]
                if previous.get("state_sha256") != (fingerprint(row["state"]) if row.get("state") else None):
                    raise ValueError("Resume state differs; use a separate output file")
                continue
            if len(done) >= args.max_decisions:
                break
            wait_idle(args.live_matches, args.psi or [Path("/proc/pressure/io")])
            result = replay_one(row, row.get("state"), args.arm, args.model, guarded_client)
            result.update(protocol=args.protocol)
            output.write(json.dumps(result, ensure_ascii=False) + "\n")
            output.flush()
            done[identity(row)] = result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
