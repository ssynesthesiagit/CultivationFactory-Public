"""Local-model pass over the typed mechanics authority: type what the parser left as riders.

Owner ruling 2026-09-24: deterministic parser first, then the local model.
The model sees one talent's printed text and the parser's typed core and
returns typed effects for the untyped rule lines, constrained by a JSON
schema (llama.cpp grammar).  ``validate`` keeps an effect only when every
number, dice expression, damage type and condition it states appears in the
printed text; anything else stays a GM rider.  Results are appended to a JSONL
file so a run can stop and resume; the authority builder merges them.

    python tools/type_mechanics_with_model.py --endpoint http://127.0.0.1:11446/v1/chat/completions \
        --model mimo-v2.6-distill-qwen-9b-q4km --out <proposals.jsonl>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTHORITY = APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
sys.path.insert(0, str(APP))

from factory_authoring.typed_mechanics import CONDITIONS, DAMAGE_TYPES  # noqa: E402

ECONOMIES = ["action", "bonus_action", "reaction", "no_action", "free_action", "passive", "ritual", "special"]
_DICE = {"type": "string", "pattern": "^(([0-9]+|PB)d[0-9]+)?$"}
_EFFECT = {
    "type": "object",
    "properties": {
        "type": {"enum": ["damage", "extra_damage", "half_damage", "save", "attack_modifier", "damage_modifier", "condition",
                          "forced_movement", "movement", "teleport", "temp_hp", "healing", "ac_bonus", "resistance",
                          "immunity", "speed", "advantage", "disadvantage", "reaction_denied", "gain_resource",
                          "spend_resource", "zone"]},
        "applies_to": {"enum": ["self", "target", "ally", "enemies_in_area", "creatures_in_area", "attacker"]},
        "dice": _DICE,
        "flat": {"type": "integer"},
        "formula": {"enum": ["none", "pb", "cl", "key_ability_modifier", "half_pb"]},
        "damage_types": {"type": "array", "items": {"enum": list(DAMAGE_TYPES)}},
        "ability": {"enum": ["none", "str", "dex", "con", "int", "wis", "cha"]},
        "condition": {"enum": ["none", *CONDITIONS]},
        "distance_ft": {"type": "integer"},
        "on": {"type": "string"},
        "duration": {"enum": ["instant", "until_end_of_turn", "until_start_of_next_turn", "one_round", "one_minute", "concentration", "special"]},
        "evidence": {"type": "string"},
    },
    # Every field is required so the grammar makes the model state each value
    # (0, "" or "none" when it does not apply) instead of silently skipping it.
    "required": ["type", "applies_to", "dice", "flat", "formula", "damage_types", "ability", "condition",
                 "distance_ft", "on", "duration", "evidence"],
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "economy": {"enum": ECONOMIES},
        "trigger": {"type": "string"},
        "modifies": {"type": "string"},
        "effects": {"type": "array", "items": _EFFECT, "maxItems": 8},
        "still_untyped": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
    "required": ["economy", "trigger", "modifies", "effects", "still_untyped"],
}

PROMPT = """You convert one tabletop-RPG talent's printed rules into typed combat effects.
Use ONLY what the text states. Never invent numbers, dice, damage types or conditions.
Every effect states its values: "flat" (a signed whole number from the text, e.g. -5 or 10), "dice" (e.g. "2d6"),
"formula" ("pb" for Proficiency Bonus), "distance_ft", "ability" for saves, "condition", "damage_types", "on" for
Advantage/Disadvantage. Use 0, "" or "none" only for values that do not apply. Copy the exact phrase into "evidence".
"economy": the talent's "Action Type" line if it has one. Without one: "reaction" only if the text says to use your
Reaction; otherwise "passive" (it triggers on an event or changes another technique).
"trigger": the "When ..." condition from the text, else "".  "modifies": the other technique it changes, else "".
Type the UNTYPED LINES only; ALREADY TYPED is context. Put rules you cannot type into "still_untyped" verbatim.

EXAMPLE (a DIFFERENT talent; never copy its names, trigger or values)
TALENT: Brutal Strike
PRINTED TEXT: When making Batter, take: -5 to the attack roll. Hit: Deal: +10 damage
OUTPUT: {{"economy":"passive","trigger":"When making Batter","modifies":"Batter","effects":[
{{"type":"attack_modifier","applies_to":"self","dice":"","flat":-5,"formula":"none","damage_types":[],"ability":"none","condition":"none","distance_ft":0,"on":"","duration":"instant","evidence":"-5"}},
{{"type":"damage_modifier","applies_to":"target","dice":"","flat":10,"formula":"none","damage_types":[],"ability":"none","condition":"none","distance_ft":0,"on":"","duration":"instant","evidence":"+10 damage"}}],"still_untyped":[]}}

NOW THE REAL TALENT
TALENT: {name}
PRINTED TEXT:
{text}

ALREADY TYPED:
{typed}

UNTYPED LINES:
{riders}
"""


def _numbers(value: str) -> set[str]:
    return set(re.findall(r"\d+", value))


def _has_amount(effect: dict) -> bool:
    return bool(effect.get("dice")) or effect.get("flat") not in (None, 0) or effect.get("formula") not in (None, "none")


# The values each effect type must state to mean anything to the engine.
_REQUIRED = {
    "damage": _has_amount, "extra_damage": _has_amount, "attack_modifier": _has_amount, "damage_modifier": _has_amount,
    "temp_hp": _has_amount, "healing": _has_amount, "gain_resource": _has_amount, "spend_resource": _has_amount,
    "save": lambda e: e.get("ability") not in (None, "none"),
    "condition": lambda e: e.get("condition") not in (None, "none"),
    "forced_movement": lambda e: bool(e.get("distance_ft")), "movement": lambda e: bool(e.get("distance_ft")),
    "teleport": lambda e: bool(e.get("distance_ft")), "zone": lambda e: bool(e.get("distance_ft")),
    "ac_bonus": lambda e: e.get("flat") not in (None, 0), "speed": lambda e: e.get("flat") not in (None, 0),
    "resistance": lambda e: bool(e.get("damage_types")), "immunity": lambda e: bool(e.get("damage_types")),
    "advantage": lambda e: bool(str(e.get("on") or "").strip()), "disadvantage": lambda e: bool(str(e.get("on") or "").strip()),
    "half_damage": lambda e: True, "reaction_denied": lambda e: True,
}


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("“", '"').replace("”", '"').lower()).strip()


def validate(effect: dict, source: str) -> str | None:
    """None when the effect is grounded in the printed text, else the reason it is rejected."""
    lowered = source.lower()
    evidence = str(effect.get("evidence") or "")
    if not evidence or _plain(evidence) not in _plain(source):
        return "evidence is not a phrase of the printed text"
    required = _REQUIRED.get(effect.get("type"))
    if required is None or not required(effect):
        return f"{effect.get('type')} states none of its required values"
    if (effect.get("type") == "condition" and effect.get("applies_to") == "self"
            and effect.get("condition") in {"incapacitated", "stunned", "paralyzed", "unconscious", "petrified", "restrained", "blinded", "charmed", "frightened"}):
        return "a self-disabling condition needs review (usually a condition the text only names)"
    dice = effect.get("dice")
    if dice and dice.lower() not in lowered.replace(" ", ""):
        return f"dice {dice} not in text"
    for key in ("flat", "distance_ft"):
        if effect.get(key) not in (None, 0) and str(abs(int(effect[key]))) not in _numbers(source):
            return f"{key} {effect[key]} not in text"
    for kind in effect.get("damage_types") or []:
        if kind not in lowered:
            return f"damage type {kind} not in text"
    condition = effect.get("condition")
    if condition and condition != "none" and condition not in lowered:
        return f"condition {condition} not in text"
    return None


def _call(endpoint: str, model: str, prompt: str, timeout: int) -> tuple[dict, float]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 1800,
        "response_format": {"type": "json_schema", "json_schema": {"name": "typed", "schema": RESPONSE_SCHEMA}},
    }
    request = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    return json.loads(payload["choices"][0]["message"]["content"]), time.monotonic() - started


BATCH_PROMPT = """Return ONLY one JSON object, no prose, no code fences. Its keys are the TALENT IDs below; each value is
{{"economy": "...", "trigger": "", "modifies": "", "effects": [...], "still_untyped": [...]}}.
You convert tabletop-RPG talents' printed rules into typed combat effects. Use ONLY what each text states; never
invent numbers, dice, damage types or conditions. Every effect has ALL of these fields:
"type" (one of: {types}), "applies_to" (self|target|ally|enemies_in_area|creatures_in_area|attacker),
"dice" (e.g. "2d6" or ""), "flat" (signed whole number from the text or 0), "formula" (none|pb|cl|key_ability_modifier|half_pb),
"damage_types" (list of: {damage_types}), "ability" (none|str|dex|con|int|wis|cha), "condition" (none|{conditions}),
"distance_ft" (number or 0), "on" (what Advantage/Disadvantage applies to, else ""),
"duration" (instant|until_end_of_turn|until_start_of_next_turn|one_round|one_minute|concentration|special),
"evidence" (the exact phrase copied from that talent's text).
"economy": the talent's "Action Type" line if it has one; without one, "reaction" only if the text says to use your
Reaction, otherwise "passive". "trigger": the "When ..." condition, else "". "modifies": the other technique it changes, else "".
Type each talent's UNTYPED LINES; ALREADY TYPED is context only. Put rules you cannot type into "still_untyped" verbatim.
Example value: {{"economy":"passive","trigger":"When making Batter","modifies":"Batter","effects":[{{"type":"attack_modifier","applies_to":"self","dice":"","flat":-5,"formula":"none","damage_types":[],"ability":"none","condition":"none","distance_ft":0,"on":"","duration":"instant","evidence":"-5"}}],"still_untyped":[]}}

{talents}
"""


def _call_commandcode(model: str, prompt: str, timeout: int, workdir: Path) -> tuple[dict, float, dict]:
    """One headless Command Code call (owner 2026-09-24: use the Command Code login), run in an empty folder."""
    import subprocess

    workdir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    completed = subprocess.run(
        ["commandcode", "-p", prompt, "-m", model, "--max-turns", "2", "--no-session", "--skip-onboarding",
         "--no-auto-update", "--output-format", "json"],
        cwd=workdir, capture_output=True, text=True, timeout=timeout,
    )
    result = next((json.loads(line) for line in reversed(completed.stdout.splitlines())
                   if line.startswith('{"type":"result"')), None)
    # Exit 8 is the turn cap; its result can still carry the complete JSON answer.
    text = (result or {}).get("finalText") or ""
    if completed.returncode not in (0, 8) or not result or "{" not in text:
        raise RuntimeError(f"commandcode exit {completed.returncode}: {(completed.stderr or '')[-300:]}")
    # The answer may hold more than one JSON object; keep the largest one that parses.
    decoder, best = json.JSONDecoder(), None
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _end = decoder.raw_decode(text[index:])
            except ValueError:
                continue
            if isinstance(value, dict) and (best is None or len(value) > len(best)):
                best = value
    if best is None:
        raise ValueError("no JSON object in the answer")
    return best, time.monotonic() - started, result.get("usage") or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", nargs="*", default=[])
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--via", choices=["llama", "commandcode"], default="llama")
    parser.add_argument("--batch", type=int, default=15)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.via == "commandcode" and args.model != "deepseek/deepseek-v4.1-flash":
        # Owner 2026-09-26: only DeepSeek V4.1 Flash through Command Code; others used a lot of data.
        parser.error("Command Code runs use only deepseek/deepseek-v4.1-flash (owner rule)")

    authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
    sys.path.insert(0, str(APP / "tools"))
    from typed_mechanics_sources import source_texts

    texts = source_texts()
    # Owner 2026-09-24: talents change during playtesting.  A proposal belongs to
    # the exact printed text it read; an edited or new talent is queued again.
    done = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                # A proposal from another model does not count: the stronger model redoes it.
                if args.via != "commandcode" or str(row.get("model", "")).startswith(args.model):
                    done.add((row["mechanic_id"], row.get("text_sha256")))
    # Sphere by Sphere, so review can start on a finished Sphere while the run continues.
    keys = args.ids or sorted(authority["mechanics"], key=lambda key: (authority["mechanics"][key]["sphere_id"] or "", key))
    queue = [
        key for key in keys
        if authority["mechanics"][key]["coverage"] != "FULL"
        and (key, hashlib.sha256(texts.get(key, "").encode("utf-8")).hexdigest()) not in done
    ]
    if args.limit:
        queue = queue[: args.limit]
    if args.via == "commandcode":
        return _run_commandcode(args, authority, texts, queue)
    prompt_sha = hashlib.sha256(PROMPT.encode()).hexdigest()
    with args.out.open("a", encoding="utf-8") as sink:
        for index, key in enumerate(queue, 1):
            mechanic = authority["mechanics"][key]
            source = texts[key]
            prompt = PROMPT.format(
                name=mechanic["name"], text=source.strip(),
                typed=json.dumps([{k: v for k, v in e.items() if k != "evidence"} | {"evidence": e.get("evidence")} for e in mechanic["effects"]], ensure_ascii=False)[:3000],
                riders="\n".join(f"- {line}" for line in mechanic["riders"]) or "(none)",
            )
            row = {"mechanic_id": key, "text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                   "model": args.model, "prompt_sha256": prompt_sha}
            try:
                output, seconds = _call(args.endpoint, args.model, prompt, args.timeout)
                accepted, rejected = [], []
                for effect in output.get("effects") or []:
                    reason = validate(effect, source)
                    (rejected if reason else accepted).append({**effect, **({"rejected": reason} if reason else {})})
                row.update({"seconds": round(seconds, 2), "economy": output.get("economy"), "trigger": output.get("trigger") or None,
                            "modifies": output.get("modifies") or None, "accepted": accepted, "rejected": rejected,
                            "still_untyped": output.get("still_untyped") or []})
            except Exception as exc:  # recorded, retried on the next run
                row.update({"error": f"{type(exc).__name__}: {exc}"[:300]})
            if "error" not in row:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
            print(f"[{index}/{len(queue)}] {key} {row.get('seconds', '-')}s accepted={len(row.get('accepted', []))} "
                  f"rejected={len(row.get('rejected', []))} {row.get('error', '')}", flush=True)
    return 0



def _run_commandcode(args, authority: dict, texts: dict, queue: list[str]) -> int:
    """Batches of talents per call, several calls in parallel; each result validated like the local path."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    types = ", ".join(_EFFECT["properties"]["type"]["enum"])
    template = BATCH_PROMPT.replace("{types}", types).replace("{damage_types}", ", ".join(DAMAGE_TYPES)).replace(
        "{conditions}", "|".join(CONDITIONS))
    prompt_sha = hashlib.sha256(template.encode()).hexdigest()
    lock = threading.Lock()
    batches = [queue[i:i + args.batch] for i in range(0, len(queue), args.batch)]
    totals = {"done": 0, "input": 0, "output": 0}

    def work(numbered):
        number, keys = numbered
        blocks = []
        for key in keys:
            mechanic = authority["mechanics"][key]
            typed = [{k: v for k, v in e.items() if k not in {"origin"}} for e in mechanic["effects"] if e.get("origin", "parser") == "parser"]
            blocks.append(f"TALENT ID: {key}\nNAME: {mechanic['name']}\nPRINTED TEXT:\n{texts[key].strip()}\n"
                          f"ALREADY TYPED: {json.dumps(typed, ensure_ascii=False)[:1500]}\n"
                          "UNTYPED LINES:\n" + ("\n".join(f"- {line}" for line in mechanic["riders"]) or "(none)"))
        prompt = template.replace("{talents}", "\n\n".join(blocks)).replace("{{", "{").replace("}}", "}")
        try:
            output, seconds, usage = _call_commandcode(args.model, prompt, args.timeout, Path("/var/tmp/cf-commandcode-work") / f"w{number % args.workers}")
        except Exception as exc:
            print(f"[batch {number}] error {type(exc).__name__}: {str(exc)[:200]}", flush=True)
            return
        rows = []
        for key in keys:
            result = output.get(key)
            if not isinstance(result, dict):
                continue
            source = texts[key]
            accepted, rejected = [], []
            for effect in result.get("effects") or []:
                if isinstance(effect, dict):
                    reason = validate(effect, source)
                    (rejected if reason else accepted).append({**effect, **({"rejected": reason} if reason else {})})
            rows.append({"mechanic_id": key, "text_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                         "model": f"{args.model} via commandcode", "prompt_sha256": prompt_sha, "seconds": round(seconds / max(1, len(keys)), 2),
                         "economy": str(result.get("economy") or "").strip().lower().replace(" ", "_") or None,
                         "trigger": result.get("trigger") or None, "modifies": result.get("modifies") or None,
                         "accepted": accepted, "rejected": rejected, "still_untyped": result.get("still_untyped") or []})
        with lock:
            with args.out.open("a", encoding="utf-8") as sink:
                for row in rows:
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            totals["done"] += len(rows)
            totals["input"] += int(usage.get("inputTokens") or 0)
            totals["output"] += int(usage.get("outputTokens") or 0)
            print(f"[batch {number}/{len(batches)}] {len(rows)}/{len(keys)} typed in {seconds:.1f}s | total {totals['done']} "
                  f"| tokens in {totals['input']} out {totals['output']}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, enumerate(batches, 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
