"""Versioned, transport-independent AI player contract (runner and CLI adapters).

Formatting recovery never grants legality: validate_answer checks the actual
actor-view menu before the table service checks a fresh candidate again.
"""
import json
import hashlib
import re

VERSION = "factory-seat/1"
SYSTEM_PROMPT = (
    "You play one fighter in a D&D-style combat. Use only your own observations; "
    "unseen creatures' current positions are unknown. Grid squares are 5 feet. "
    "Map cell_runs are [y,x_first,x_last] inclusive; wall points use thousandths "
    "of a square. Last-seen positions are past observations, not current targets. "
    "Dao describes your temperament, preferred distance and resource reserves. "
    "Choose only keys/options supplied in this decision. Costs and action economy "
    "still apply; a plan is rechecked after each step. Reuse a key only if still legal. "
    "TURN: plan the remaining turn, ending with End turn. If a step becomes illegal, "
    "you will get a new decision. REACTION: answer only the named trigger; DECLINE "
    "uses no options or resources. The built-in suggestion is advice, not an order. "
    "Return one JSON object matching reply_schema. No tools, commands or commentary."
)


def dao_line(view, temperament_chars=100):
    """Compact source-derived identity and fighting temperament, never rules.

    The choices renderer retains identity and uncut source clauses at every
    budget and repair. Sphere verbs are the owner's plain-language temperament;
    no policy ids or new per-Dao instructions are emitted.
    """
    from .choices import text
    dao = view.get("dao") or {}
    temperament = dao.get("temperament") or {}
    name = dao.get("name") or " / ".join(temperament.get("spheres") or []) or "Unnamed Dao"
    fighting = (temperament.get("fighting") or ", ".join(temperament.get("verbs") or [])
                or temperament.get("natural") or "; ".join(dao.get("tenets") or [])
                or ", ".join(dao.get("role") or []) or "temperament not recorded")
    # Drop whole optional source clauses, never cut off a word or tenet.
    fighting = text(fighting, len(str(fighting)) + 1)
    clauses = re.split(r"[,;] ", fighting)
    kept = clauses[:1]
    for clause in clauses[1:]:
        if len(", ".join([*kept, clause])) > temperament_chars:
            break
        kept.append(clause)
    return "Dao: " + text(name, len(str(name)) + 1) + ": " + ", ".join(kept)


def compact_map(board):
    """Lossless row runs for visible terrain, zones and trunks; wall pieces."""
    result = {k: board[k] for k in ("width", "height") if k in board}
    for kind in ("terrain", "zones", "trees"):
        rows = []
        for row in board.get(kind, []):
            cells = sorted({(c["y"], c["x"]) if isinstance(c, dict) else (c[1], c[0])
                            for c in row.get("cells", [])})
            runs = []
            for y, x in cells:
                if runs and runs[-1][0] == y and runs[-1][2] + 1 == x:
                    runs[-1][2] = x
                else:
                    runs.append([y, x, x])
            rows.append({**{k: v for k, v in row.items() if k != "cells"}, "cell_runs": runs})
        result[kind] = rows
    walls = {}
    for wall in board.get("walls", []):
        walls[json.dumps(wall, sort_keys=True)] = wall
    result["walls"] = list(walls.values())
    return result


def reply_schema(kind, max_plan_length=32):
    properties = {"why": {"type": "string", "maxLength": 160}}
    if kind == "TURN":
        properties["plan"] = {"type": "array", "minItems": 1, "maxItems": max_plan_length,
                              "items": {"type": "string"}}
        required = ["plan"]
    else:
        properties.update(selection={"enum": ["USE", "DECLINE"]},
                          option_ids={"type": "array", "uniqueItems": True, "items": {"type": "string"}},
                          spend={"type": "integer", "minimum": 0})
        required = ["selection", "option_ids", "spend"]
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required}


def build_prompt(view, legal, builtin, reason, kind, max_plan_length=32, repair=None,
                 prompt_profile="full", ranked_keys=()):
    """Full retains every choice; compact offers a bounded scored subset."""
    if prompt_profile == "choices":
        from .choices import turn_options, reaction_options, build_prompt as choice_prompt
        options = (turn_options(view, legal, builtin, ranked_keys, limit=min(max_plan_length, 3))
                   if kind == "TURN" else reaction_options(legal, builtin))
        return choice_prompt(view, options, kind, legal, repair)[0]
    if prompt_profile in {"compact", "tiny"}:
        from .compact import build_compact_prompt
        return build_compact_prompt(view, legal, builtin, kind, max_plan_length, repair, ranked_keys, prompt_profile)
    if prompt_profile != "full":
        raise ValueError("Unknown prompt profile")
    frame = build_frame(view, legal, builtin, reason, kind, max_plan_length, repair)
    return serialize_prompt(SYSTEM_PROMPT, frame, max_plan_length)


def build_frame(view, legal, builtin, reason, kind, max_plan_length=32, repair=None):
    """Compose unencoded decision fields shared by full/compact/tiny prompts.

    Fighter-static metadata belongs to serialize_prompt, which must run once
    after a profile finishes composing its state, menu and examples.
    """
    groups, menu = {}, legal
    if kind == "TURN":
        menu = {}
        for key, option in legal.items():
            shared = {k: option[k] for k in ("action", "description", "cost_label", "economy") if k in option}
            group = hashlib.sha256(json.dumps(shared, sort_keys=True).encode()).hexdigest()[:16]
            groups[group] = shared
            menu[key] = {k: v for k, v in option.items() if k not in {"description", "cost_label", "economy"}}
            menu[key]["group"] = group
        end = next(k for k, option in legal.items() if option["action"] == "End turn")
        example = {"plan": ([builtin, end] if builtin != end and max_plan_length > 1 else [end]),
                   "why": "Take the suggested legal step, then end my turn."}
    else:
        # Use the already-legal built-in response, including mandatory choices.
        example = {**builtin, "why": "Answer the offered choice as suggested."}
    frame = {"state": {k: v for k, v in view.items() if k not in {"visible_cells", "map"}},
             "protocol": VERSION, "decision_kind": kind,
             "visible_map": compact_map(view.get("map", {})),
             "legal_menu": menu, "action_groups": groups, "built_in_pick": builtin,
             "built_in_reason": reason, "reply_schema": reply_schema(kind, max_plan_length),
             "worked_example": example}
    if repair:
        frame["repair"] = "Your previous answer was invalid: " + repair + ". Return a corrected JSON object using this same menu."
    return frame


def serialize_prompt(instructions, frame, limit):
    """All profiles put canonical fighter-static content before changing state.

    Both decision schemas/examples precede decision_kind, so turns, reactions
    and repairs share the prefix when fighter/profile/plan limit are unchanged.
    worked_example remains a separately validated current-menu example.
    """
    state = frame["state"]
    stable = {"protocol": VERSION, "fighter": state.get("fighter"),
              "dao": state.get("dao", {}),
              "schemas": {k: reply_schema(k, limit) for k in ("TURN", "REACTION")},
              "format_examples": {"TURN": {"plan": (["legal-step-key", "end-turn-key"] if limit > 1 else ["end-turn-key"])},
                                  "REACTION": {"selection": "USE", "option_ids": ["offered-option"], "spend": 0}},
              "map_legend": "Coordinates and runs are absolute 5-foot squares; walls use thousandths. Only observed geometry is supplied. Example keys are placeholders; use the current legal_menu."}
    # Do not cache dynamic observations as part of fighter identity.
    dynamic = {k: v for k, v in frame.items() if k != "protocol"}
    dynamic["state"] = {k: v for k, v in state.items() if k != "dao"}
    prefix = json.dumps(stable, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    suffix = json.dumps(dynamic, ensure_ascii=False, separators=(",", ":"))
    return instructions + "\n" + prefix[:-1] + "," + suffix[1:]


def stable_prefix(prompt):
    """Return cacheable bytes-as-text for offline prefix-fraction measurements."""
    if "\nSituation:\n" in prompt:
        return prompt.split("\nSituation:\n", 1)[0] + "\nSituation:\n"
    return prompt.split(',"state":', 1)[0]


def _without_trailing_commas(text):
    result, quoted, escaped = [], False, False
    for i, char in enumerate(text):
        if quoted:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        else:
            if char == '"':
                quoted = True
            if char == "," and text[i + 1:].lstrip().startswith(("}", "]")):
                continue
            result.append(char)
    return "".join(result)


def parse_reply(text):
    """Accept fences/prose/trailing commas, reject ambiguous multiple objects.

    Never evaluate code or reinterpret strings, booleans, numbers or menu keys.
    """
    if not isinstance(text, str) or len(text) > 65536:
        raise ValueError("Reply must be text of at most 65536 characters")
    cleaned = _without_trailing_commas(text)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Repeated JSON key")
            result[key] = value
        return result
    decoder = json.JSONDecoder(object_pairs_hook=unique_object)
    if cleaned.lstrip().startswith("["):
        raise ValueError("Reply must be an object, not an array")
    answers, i = [], 0
    while i < len(cleaned):
        if cleaned[i] != "{":
            i += 1
            continue
        try:
            value, count = decoder.raw_decode(cleaned[i:])
        except ValueError:
            raise ValueError("Reply contains malformed JSON; use double-quoted keys and values") from None
        answers.append(value)
        i += count
    if len(answers) != 1:
        raise ValueError("Reply must contain exactly one JSON object")
    return answers[0]


def validate_answer(answer, legal, kind, max_plan_length=32):
    if not isinstance(answer, dict):
        raise ValueError("Expected a JSON object")
    fields = {"plan", "why"} if kind == "TURN" else {"selection", "option_ids", "spend", "why"}
    if set(answer) - fields:
        raise ValueError("Remove fields not in reply_schema")
    if "why" in answer and (not isinstance(answer["why"], str) or len(answer["why"]) > 160):
        raise ValueError("why must be a sentence of at most 160 characters")
    if kind == "TURN":
        plan = answer.get("plan")
        if not isinstance(plan, list) or not 1 <= len(plan) <= max_plan_length:
            raise ValueError("plan must fit the reply_schema length limit")
        if any(not isinstance(k, str) or k not in legal for k in plan):
            raise ValueError("plan must use only legal_menu keys")
        has_end = any(row["action"] == "End turn" for row in legal.values())
        if not has_end and len(plan) != 1:
            raise ValueError("A follow-up decision requires exactly one current choice")
        if has_end and legal[plan[-1]]["action"] != "End turn":
            raise ValueError("plan must finish with the End turn key")
        return {"plan": plan}
    if not isinstance(answer.get("selection"), str) or answer["selection"] not in {"USE", "DECLINE"}:
        raise ValueError("selection must be USE or DECLINE")
    choice = legal.get("choice") or {}
    ids = answer.get("option_ids")
    allowed = {o["id"] for o in choice.get("options", [])}
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids) or not set(ids) <= allowed:
        raise ValueError("option_ids must contain unique offered option ids")
    spend = answer.get("spend")
    if not isinstance(spend, int) or isinstance(spend, bool) or spend < 0:
        raise ValueError("spend must be a nonnegative integer")
    if answer["selection"] == "USE":
        if choice and not choice["minimum"] <= len(ids) <= choice["maximum"]:
            raise ValueError("Select the required number of options")
        if spend not in legal.get("spend_options", [0]):
            raise ValueError("Choose an offered spend amount")
    else:
        if choice and not choice.get("allow_decline", True):
            raise ValueError("This mandatory choice requires USE")
        if spend or ids:
            raise ValueError("DECLINE requires empty option_ids and zero spend")
    return {"selection": answer["selection"], "option_ids": ids, "spend": spend}
