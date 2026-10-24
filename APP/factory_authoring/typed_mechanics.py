"""Typed combat mechanics for Sphere talents and base abilities, read from their printed rules.

Owner rulings 2026-09-24: combat runs the typed core of every talent (rolls,
damage, conditions, movement, zones, buffs) and hands whatever cannot be typed
to the GM as a rider; typing is done at compile time (the engine never reads
prose), first by this deterministic parser, then by the local model for what
the parser leaves.  Every typed field keeps the exact source fragment it came
from (``evidence``) so a reviewer, or a validator for model output, can check
it against the printed text.

Coverage per mechanic:
  FULL              every effect line was typed;
  CORE_WITH_RIDERS  typed core plus GM-adjudicated riders;
  RIDERS_ONLY       nothing typed yet (all riders).
"""

from __future__ import annotations

import re
from typing import Any

SCHEMA = "TianxiaFoundry.TypedMechanic.v1"
PARSER_VERSION = "typed-mechanics-parser.v1"

ABILITIES = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
DAMAGE_TYPES = ("acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison",
                "psychic", "radiant", "slashing", "thunder")
CONDITIONS = ("blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated", "invisible", "paralyzed",
              "petrified", "poisoned", "prone", "restrained", "stunned", "unconscious", "burning", "smothered")
ECONOMY = {
    "action": "action", "bonus action": "bonus_action", "reaction": "reaction", "no action": "no_action",
    "free action": "free_action", "ritual procedure": "ritual", "multi-mode": "multi_mode",
    "linked modifier": "linked_modifier", "passive": "passive", "magic action": "action",
}
RESOURCES = {
    "cp": "cp", "qi": "qi", "stamina": "stamina", "resonance": "resonance", "hp": "hp", "hit point": "hp",
    "hit points": "hp", "martial focus": "martial_focus", "devoured essence": "devoured_essence",
}

_HEADER_KEYS = {
    "action type": "action_type", "canonical action type": "action_type", "range": "range", "area": "area",
    "target": "target", "targets": "target", "duration": "duration", "cost": "cost", "use limit": "use_limit",
    "trigger": "trigger", "requirement": "requirement", "requirements": "requirement", "tags": "tags",
    "prerequisite": "prerequisite", "prerequisites": "prerequisite", "timing detail": "timing_detail",
    "talent type": "talent_type", "limit": "use_limit", "uses": "use_limit",
    # Foundation catalog rows label the action type "Type:" instead of a bare economy
    # line (owner 2026-09-25); no other typed source uses this key.
    "type": "action_type",
}
# "Available At" (a Foundation stage gate) and "Attack or Save" (a Foundation category
# note) are Foundation-catalog-only fields (owner 2026-09-25): recognized so they don't
# end the header early, but not stored -- stage lives in the Foundation feature record
# (non_sphere_authority/foundation_features.py), and delivery is inferred from the
# effect text like every other source.
#
# Bookkeeping and label lines the catalogs print among the real fields (hunt 3, 2026-09-29: Ember Talisman's "Range: 60
# feet" was typed as no range, so its reactions were classed as melee): a talisman formula prints Rank / Family /
# Activation / Consumed above its Range, a base ability prints Classification / Tag and the Factory split-review notes,
# a recipe prints Rarity. None is a field the typing reads, but each one used to end the header (or eat the few lines a
# header may follow an intro by), so every field printed beneath it was dropped.
_IGNORED_HEADERS = {"factory combat bucket", "factory routing", "concentration", "available at", "attack or save",
                    "rank", "family", "activation", "consumed", "rarity", "classification", "tag",
                    "split candidate buckets", "split review decision", "recommended factory realization"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("—", "-")).strip()


def _dice(text: str) -> dict[str, Any] | None:
    """'8d8', 'PBd6', '12' or '2d8 + your Music key ability modifier' as a dice spec."""
    match = re.match(r"^\s*(\d+|PB)d(\d+)\s*(?:\+\s*(.+?))?\s*$", text, re.I)
    if match:
        bonus = match.group(3)
        return {
            "count": int(match.group(1)) if match.group(1).isdigit() else None,
            "count_formula": None if match.group(1).isdigit() else "pb",
            "sides": int(match.group(2)),
            "bonus": int(bonus) if bonus and bonus.strip().isdigit() else None,
            "bonus_formula": _formula(bonus) if bonus and not bonus.strip().isdigit() else None,
        }
    if re.match(r"^\s*\d+\s*$", text):
        return {"count": 0, "count_formula": None, "sides": 0, "bonus": int(text), "bonus_formula": None}
    return None


def _formula(text: str | None) -> str | None:
    if not text:
        return None
    lowered = _norm(text).lower().rstrip(".;")
    if lowered in {"your proficiency bonus", "proficiency bonus", "pb"}:
        return "pb"
    if lowered in {"your cl", "cl"}:
        return "cl"
    match = re.match(r"^(?:your )?(\w+)(?: key ability)? modifier$", lowered)
    if match:
        return f"mod:{match.group(1)}"
    return f"text:{lowered}"


def _types(text: str) -> tuple[list[str], bool]:
    found = [kind for kind in DAMAGE_TYPES if re.search(rf"\b{kind}\b", text, re.I)]
    return found, bool(re.search(r"\bor\b", text)) and len(found) > 1


# ------------------------------------------------------------------ header
def parse_header(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    header: dict[str, str] = {}
    body: list[str] = []
    in_header = True
    prose = 0  # body lines that are not header fields; a header field may follow an intro by only a few of them
    for raw in lines:
        # Path chapters print headers in bold markdown ("**Cost:** 1 Qi", "**Reaction**").
        line = raw.strip().replace("**", "").strip()
        if not line or line.startswith("#") or line == "---":
            continue
        if in_header and "action_type" not in header and _norm(line).lower() in ECONOMY:
            header["action_type"] = line
            continue
        match = re.match(r"^([A-Za-z][A-Za-z ]{1,30}):\s*(.*)$", line)
        key = match.group(1).strip().lower() if match else None
        if in_header and match and (key in _HEADER_KEYS or key in _IGNORED_HEADERS):
            if key == "concentration":
                header.setdefault("concentration", match.group(2).strip())  # "**Concentration:** Required" in the header block
            if key in _HEADER_KEYS and _HEADER_KEYS[key] not in header:
                header[_HEADER_KEYS[key]] = match.group(2).strip()
            continue
        if in_header and (line.startswith("“") or line.startswith('"')):
            continue  # epigraph
        # A header field printed after an intro sentence ("When you learn the Blood sphere, you learn
        # Coagulate automatically." then "Action Type:", "Range:", "Cost: 1 CP") still belongs to the
        # header (owner 2026-09-26 tournament: 344 usable abilities lost their printed cost and ran free).
        if not in_header and match and key in _HEADER_KEYS and _HEADER_KEYS[key] not in header and match.group(2).strip() and prose <= 3:
            header[_HEADER_KEYS[key]] = match.group(2).strip()
            continue
        if not in_header and match and key in _IGNORED_HEADERS and prose <= 3:
            if key == "concentration":
                header.setdefault("concentration", match.group(2).strip())  # printed after an intro sentence, as Burial Drum's
            continue
        # A field the header already has (a "Canonical Action Type:" under the "Action Type:", a second "Cost:") stays body
        # text, but is not one of the lines a header may follow an intro by: it does not close the window on a "Range:".
        if not in_header and match and key in _HEADER_KEYS and _HEADER_KEYS[key] in header and prose <= 3:
            body.append(line)
            continue
        in_header = False
        body.append(line)
        prose += 1
    return header, body


def _economy(value: str | None) -> str | None:
    if not value:
        return None
    lowered = _norm(value).lower()
    for label, economy in ECONOMY.items():
        if lowered.startswith(label):
            return economy
    return "special"


def _cost(value: str | None) -> list[list[dict[str, Any]]]:
    """'12 CP or 12 Devoured Essence' -> [[{cp 12}], [{devoured_essence 12}]]; 'None' -> []."""
    if not value or _norm(value).lower().rstrip(".") in {"none", "0 cp", "no cost"}:
        return []
    options = []
    for option in re.split(r",\s*(?:or\s+)?|\s+or\s+", _norm(value).rstrip(".")):
        parts = []
        for part in re.split(r"\s+and\s+", option):
            part = part.strip()
            if re.match(r"^expend martial focus$", part, re.I):
                parts.append({"resource": "martial_focus", "amount": 1})
                continue
            match = re.match(r"^(\d+|PB)\s+(.+)$", part, re.I)
            resource = RESOURCES.get(match.group(2).strip().lower()) if match else None
            if not resource:
                return [[{"resource": "text", "text": _norm(value)}]]
            amount = match.group(1)
            parts.append({"resource": resource, "amount": int(amount) if amount.isdigit() else None,
                          "amount_formula": None if amount.isdigit() else "pb"})
        options.append(parts)
    return options


def _use_limit(value: str | None) -> str | None:
    if not value:
        return None
    lowered = _norm(value).lower()
    for pattern, limit in ((r"once per turn", "once_per_turn"), (r"once per round", "once_per_round"),
                           (r"short or long rest", "once_per_short_rest"), (r"short rest", "once_per_short_rest"),
                           (r"long rest", "once_per_long_rest"), (r"once per day|per day", "once_per_day")):
        if re.search(pattern, lowered):
            return limit
    return "text:" + lowered


def _range(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    lowered = _norm(value).lower().rstrip(".")
    match = re.match(r"^(\d+)\s*(?:feet|ft)", lowered)
    if match:
        return {"kind": "feet", "feet": int(match.group(1))}
    match = re.match(r"^(\d+)-foot emanation", lowered)
    if match:
        return {"kind": "self", "feet": 0, "emanation_ft": int(match.group(1))}
    # "A point within 60 feet", "An unoccupied space within 120 feet": the distance is the range. A value that also names
    # another reach ("Melee reach or 60 feet", "Touch, or within 30 feet ...") or a second distance ("30/90 feet") is left
    # as text: which of them applies is the ability's own condition, not something to guess here.
    within = re.findall(r"\bwithin\s+(\d+)\s*(?:feet|foot|ft)\b", lowered)
    if len(within) == 1 and len(re.findall(r"\d+", lowered)) == 1 and not re.search(r"\b(?:self|touch|melee|reach|weapon|thrown|sight)\b", lowered):
        return {"kind": "feet", "feet": int(within[0])}
    for word, kind in (("self", "self"), ("touch", "touch"), ("weapon reach", "reach"), ("reach", "reach"),
                       ("weapon", "weapon"), ("sight", "sight")):
        if lowered.startswith(word):
            return {"kind": kind, "feet": 0 if kind in {"self"} else 5 if kind in {"touch", "reach"} else None}
    return {"kind": "special", "feet": None, "text": _norm(value)}


def _area(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    lowered = _norm(value).lower()
    match = re.search(r"(\d+)-foot(?:-radius)?\s+(sphere|cone|line|cube|emanation|aura|cylinder|radius|square)", lowered)
    if match:
        shape = {"radius": "sphere", "aura": "emanation"}.get(match.group(2), match.group(2))
        return {"shape": shape, "size_ft": int(match.group(1)), "centered_on_self": "centered on you" in lowered or "from you" in lowered or shape == "emanation"}
    return {"shape": "special", "size_ft": None, "text": _norm(value)}


def _duration(value: str | None, concentration_header: str | None = None) -> dict[str, Any]:
    # "**Concentration:** Required" is its own header line, printed apart from "Duration:" (Burial Drum, Paper Heaven,
    # Elemental Dominion); a header that prints it is concentration whatever the Duration line says.
    printed_concentration = _norm(concentration_header or "").lower().startswith(("required", "yes"))
    if not value:
        return {"kind": "instant", "amount": None, "concentration": printed_concentration}
    lowered = _norm(value).lower()
    concentration = printed_concentration or ("concentration" in lowered and "not required" not in lowered)
    for pattern, kind in ((r"until the end of your (?:next )?turn", "until_end_of_turn"),
                          (r"until the start of your next turn", "until_start_of_next_turn"),
                          (r"instant", "instant")):
        if re.search(pattern, lowered):
            return {"kind": kind, "amount": None, "concentration": concentration}
    match = re.search(r"(\d+)\s+(round|minute|hour|day)s?", lowered)
    if match:
        return {"kind": match.group(2) + "s", "amount": int(match.group(1)), "concentration": concentration}
    return {"kind": "special", "amount": None, "concentration": concentration, "text": _norm(value)}


# ------------------------------------------------------------------ effects
_DAMAGE_RE = re.compile(
    r"\b(?:take|takes|deal|deals|dealing|taking)\s+(?:an extra |an additional |extra )?"
    r"((?:\d+|PB)d\d+(?:\s*\+\s*(?:\d+|your [\w ]+? modifier|your proficiency bonus))?|\d+)\s+"
    r"((?:[A-Z][a-z]+)(?:(?:,\s*|,?\s+or\s+|,?\s+and\s+)[A-Z][a-z]+)*)\s+damage", re.I)
_SAVE_RE = re.compile(r"\b(?:makes?|must make|make)\s+(?:an?\s+)?(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s+saving throws?", re.I)
_ATTACK_RE = re.compile(r"\bmake\s+(one|a|an|two|three)\s+((?:melee |ranged |thrown )?(?:weapon|saber|spear|sword|axe|unarmed|technique|spell|bow|natural)?\s*)attacks?\b", re.I)
_FORCED_RE = re.compile(r"\b(?:is |are )?(?:moved|pushed|pulled|move|push|pull|moves)\s+(?:up to\s+)?(\d+)\s+feet\s+(away from you|toward you|toward (?:the center|a point you choose|the source)|in a direction you choose|away)", re.I)
_SELF_MOVE_RE = re.compile(r"\b(?:you may |you can )?move up to (\d+) feet(?: without provoking opportunity attacks)?", re.I)
_TELEPORT_RE = re.compile(r"\bteleport(?:s)?\s+(?:up to\s+(\d+)\s+feet|to an unoccupied space you can see within range)", re.I)
_CONDITION_RE = re.compile(r"\b(?:is|are|becomes?|fall|falls|knocked|gains? the|give it the|has the)\s+(" + "|".join(CONDITIONS) + r")\b", re.I)
_HALF_RE = re.compile(r"\b(?:take|takes)\s+half\s+(?:as much\s+)?damage\b|\bhalf damage\b", re.I)
_AC_RE = re.compile(r"(?:gain|gains|\+)\s*\+?(\d+)\s+(?:bonus to\s+)?AC\b|\+(\d+)\s+AC\b", re.I)
_RESIST_RE = re.compile(r"\b(Resistance|Immunity)\s+to\s+((?:[A-Z][a-z]+)(?:(?:,\s*|,?\s+or\s+|,?\s+and\s+)[A-Z][a-z]+)*)\s+damage", re.I)
_TEMP_HP_RE = re.compile(r"\b(?:gain|gains)\s+(?:(\d+d\d+|\d+)\s+)?Temporary (?:HP|hit points)(?:\s+equal to\s+([^.;]+))?", re.I)
_HEAL_RE = re.compile(r"\bregains?\s+((?:\d+|PB)d\d+(?:\s*\+\s*[^.;]+?)?|\d+)\s+(?:HP|hit points)", re.I)
_SPEED_RE = re.compile(r"\b(?:Speed|speed) (?:increases|is increased) by (\d+) feet|\+(\d+) feet Speed", re.I)
_REDUCE_SPEED_RE = re.compile(r"\bSpeed is reduced by (\d+) feet|\bspeed is halved", re.I)
_NO_REACTIONS_RE = re.compile(r"\bcannot take Reactions\b", re.I)
_ADVANTAGE_RE = re.compile(r"\b(Advantage|Disadvantage) on ([^.;]+)", re.I)


# CL-scaled dice (playtest 2026-09-24: Mind Spike's "listed dice" were never
# typed, so at CL 10 it dealt only the Wisdom modifier).  Two printed forms:
# a table "| 5–10 | `2d8 + Wisdom modifier` |" and "increases by 1d8 at CL 5,
# CL 11, and CL 17".
_CL_TABLE_ROW = re.compile(r"\|\s*(?:CL\s*)?(\d+)\s*[–-]\s*(\d+)\s*\|\s*`?(\d+)d(\d+)", re.I)
# Realm tables ("| Foundation | 2d10 + your key ability modifier |"), by each Realm's entry CL.
_REALM_TABLE_ROW = re.compile(r"\|\s*(Mortal|Foundation|Core Formation|Nascent Soul|Immortal)(?:\s+Realm)?\s*\|\s*`?(\d+)d(\d+)", re.I)
_REALM_CL = (("mortal", 1, 4), ("foundation", 5, 9), ("core formation", 10, 14), ("nascent soul", 15, 19), ("immortal", 20, 20))
_CL_INCREASE = re.compile(r"(?:damage|healing)\s+increases by (\d+)d(\d+) at (CL ?\d+(?:,?\s*(?:and\s+)?CL ?\d+)*)", re.I)
_SCALED_TYPES = {"damage", "extra_damage", "healing", "temp_hp"}


def cl_dice_table(text: str, base: dict[str, Any] | None = None) -> list[list[int]] | None:
    """[[from_cl, to_cl, count, sides], ...] for the character's CL, or None."""
    rows = sorted({(int(a), int(b), int(c), int(d)) for a, b, c, d in _CL_TABLE_ROW.findall(text or "") if int(a) <= int(b)})
    if rows:
        return [list(row) for row in rows]
    realms: dict[str, tuple[int, int]] = {}
    for name, count, sides in _REALM_TABLE_ROW.findall(text or ""):
        realms.setdefault(name.lower(), (int(count), int(sides)))  # the first table (e.g. "Safe" before "Unbound")
    if len(realms) >= 2:
        return [[low, high, *realms[name]] for name, low, high in _REALM_CL if name in realms]
    match = _CL_INCREASE.search(text or "")
    if match and base and isinstance(base.get("count"), int) and isinstance(base.get("sides"), int) and int(match.group(2)) == base["sides"]:
        steps = sorted(int(value) for value in re.findall(r"CL ?(\d+)", match.group(3)))
        table, low, count = [], 1, base["count"]
        for step in steps:
            table.append([low, step - 1, count, base["sides"]])
            low, count = step, count + int(match.group(1))
        table.append([low, 20, count, base["sides"]])
        return table
    return None


def _scaled_effects(effects: list[dict[str, Any]]):
    for effect in effects or []:
        if not isinstance(effect, dict):
            continue
        if effect.get("type") in _SCALED_TYPES:
            yield effect
        for key in ("on_fail", "on_success", "on_hit"):
            yield from _scaled_effects(effect.get(key) or [])


def apply_cl_scaling(mechanic: dict[str, Any], text: str) -> None:
    """Attach dice_by_cl to damage, healing and temporary-HP effects when the text prints CL-scaled dice."""
    effects = list(_scaled_effects(mechanic.get("effects") or []))
    if not effects:
        return
    base = next((effect["dice"] for effect in effects if isinstance(effect.get("dice"), dict) and effect["dice"].get("count")), None)
    table = cl_dice_table(text, base)
    if table:
        for effect in effects:
            effect["dice_by_cl"] = table


def dice_for_cl(table: list[list[int]] | None, cl: int | None) -> dict[str, int] | None:
    if not table or not isinstance(cl, int):
        return None
    for low, high, count, sides in table:
        if low <= cl <= high:
            return {"count": count, "sides": sides}
    below = [row for row in table if row[1] < cl]
    row = below[-1] if below else table[0]
    return {"count": row[2], "sides": row[3]}


def _line_effects(line: str) -> list[dict[str, Any]]:
    """Every typed effect a single rules line states, each with its evidence."""
    effects: list[dict[str, Any]] = []
    for match in _DAMAGE_RE.finditer(line):
        dice = _dice(match.group(1))
        types, choice = _types(match.group(2))
        if dice and types:
            effects.append({"type": "damage", "dice": dice, "damage_types": types, "type_choice": choice, "evidence": match.group(0)})
    if re.search(r"\bnormal weapon damage\b", line, re.I):
        effects.append({"type": "damage", "weapon_damage": True, "evidence": "normal weapon damage"})
    if _HALF_RE.search(line):
        effects.append({"type": "half_damage", "evidence": _HALF_RE.search(line).group(0)})
    for match in _FORCED_RE.finditer(line):
        direction = match.group(2).lower()
        effects.append({"type": "forced_movement", "distance_ft": int(match.group(1)),
                        "direction": "away" if "away" in direction else "toward" if "toward you" in direction
                        else "toward_center" if "center" in direction else "choice",
                        "evidence": match.group(0)})
    for match in _CONDITION_RE.finditer(line):
        # "The court ends if you are Incapacitated" names a condition; it does not inflict one.
        clause = re.split(r"[.;:]", line[:match.start()])[-1]
        if re.search(r"\b(if|while|unless|when|whenever|until|ends?|cannot|can't|immune|against|except)\b", clause, re.I):
            continue
        effects.append({"type": "condition", "condition": match.group(1).lower(), "evidence": match.group(0)})
    if not any(effect["type"] == "condition" for effect in effects):
        bare = re.match(r"^(?:•\s*)?(?:fall |be knocked )?(prone|restrained|frightened|stunned|blinded|poisoned|grappled|charmed|deafened)[.;]?$", line.strip(), re.I)
        if bare:
            effects.append({"type": "condition", "condition": bare.group(1).lower(), "evidence": line.strip()})
    for match in _AC_RE.finditer(line):
        effects.append({"type": "ac_bonus", "amount": int(match.group(1) or match.group(2)), "evidence": match.group(0)})
    for match in _RESIST_RE.finditer(line):
        types, _ = _types(match.group(2))
        if types:
            effects.append({"type": match.group(1).lower(), "damage_types": types, "evidence": match.group(0)})
    for match in _TEMP_HP_RE.finditer(line):
        effects.append({"type": "temp_hp", "dice": _dice(match.group(1)) if match.group(1) else None,
                        "formula": _formula(match.group(2)), "evidence": match.group(0)})
    for match in _HEAL_RE.finditer(line):
        effects.append({"type": "healing", "dice": _dice(match.group(1)), "evidence": match.group(0)})
    for match in _SPEED_RE.finditer(line):
        effects.append({"type": "speed", "amount": int(match.group(1) or match.group(2)), "evidence": match.group(0)})
    for match in _REDUCE_SPEED_RE.finditer(line):
        effects.append({"type": "speed", "amount": -int(match.group(1)) if match.group(1) else None, "halved": match.group(1) is None, "evidence": match.group(0)})
    if _NO_REACTIONS_RE.search(line):
        effects.append({"type": "condition", "condition": "reaction_denied", "evidence": _NO_REACTIONS_RE.search(line).group(0)})
    for match in _TELEPORT_RE.finditer(line):
        effects.append({"type": "movement", "mode": "teleport", "distance_ft": int(match.group(1)) if match.group(1) else None,
                        "within_range": match.group(1) is None, "evidence": match.group(0)})
    if not any(effect["type"] in {"forced_movement", "movement"} for effect in effects):
        for match in _SELF_MOVE_RE.finditer(line):
            effects.append({"type": "movement", "mode": "move", "distance_ft": int(match.group(1)),
                            "no_opportunity_attacks": "without provoking" in match.group(0).lower(), "evidence": match.group(0)})
    for match in _ADVANTAGE_RE.finditer(line):
        effects.append({"type": match.group(1).lower(), "on": _norm(match.group(2)), "evidence": match.group(0)})
    return effects


def _typed_fraction(line: str, effects: list[dict[str, Any]]) -> float:
    covered = sum(len(effect["evidence"]) for effect in effects)
    return covered / max(1, len(re.sub(r"[^\w]", "", line)) + line.count(" "))


_MECHANICAL_WORDS = re.compile(
    r"\d|\b(?:save|saving|attack|damage|advantage|disadvantage|feet|foot|hp|hit points?|cp|qi|stamina|resonance|"
    r"martial focus|turn|round|minute|action|reaction|speed|ac|resistance|immunity|immune|condition|"
    + "|".join(CONDITIONS) + r"|spend|expend|regain|gain|lose|move|teleport|target|creature|ally|allies|enemy|enemies|"
    r"once|until|each|when|while|if|choose|instead|cannot|can't)\b", re.I)


def _is_description(line: str) -> bool:
    """Flavour and list introducers carry no rule of their own."""
    text = _norm(line)
    if text.endswith(":") and len(text) <= 60:
        return True
    return not _MECHANICAL_WORDS.search(text)


def parse_body(body: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Typed effects (saves and attacks own their branches), untyped rider lines, and description lines."""
    effects: list[dict[str, Any]] = []
    riders: list[str] = []
    description: list[str] = []
    current: dict[str, Any] | None = None  # open save or attack
    branch: str | None = None
    for line in body:
        text = _norm(line)
        lowered = text.lower()
        save = _SAVE_RE.search(text)
        attack = _ATTACK_RE.search(text)
        if save:
            current = {"type": "save", "ability": ABILITIES[save.group(1).lower()], "dc": "technique_save_dc",
                       "on_fail": [], "on_success": [], "evidence": save.group(0)}
            effects.append(current)
            branch = None
            rest = text[save.end():]
            fail = re.search(r"on a (?:failed save|failure)[,:]?\s*(.*?)(?:on a (?:successful save|success)[,:]?\s*(.*))?$", rest, re.I)
            if fail:
                current["on_fail"].extend(_line_effects(fail.group(1)))
                if fail.group(2):
                    current["on_success"].extend(_line_effects(fail.group(2)))
            continue
        if attack:
            current = {"type": "attack", "attack_kind": _norm(attack.group(2)).lower() or "weapon",
                       "count": {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3}[attack.group(1).lower()],
                       "on_hit": [], "evidence": attack.group(0)}
            effects.append(current)
            branch = "on_hit"
            continue
        marker = re.match(r"^(failed save|on a failed save|on a failure|successful save|on a successful save|on a success|hit|on a hit)[:,]\s*(.*)$", text, re.I)
        if marker and current is not None:
            label = marker.group(1).lower()
            branch = "on_hit" if "hit" in label else "on_success" if "success" in label else "on_fail"
            text = marker.group(2)
            if not text:
                continue
        found = _line_effects(text)
        if current is not None and branch and branch in current:
            if found:
                current[branch].extend(found)
                if _typed_fraction(text, found) < 0.5:
                    riders.append(line)
            elif _is_description(line):
                description.append(line)
            else:
                riders.append(line)
            continue
        if found:
            effects.extend(found)
            if _typed_fraction(text, found) < 0.5:
                riders.append(line)
        elif _is_description(line):
            description.append(line)
        else:
            riders.append(line)
    return effects, riders, description


def type_mechanic(record_id: str, name: str, text: str, *, kind: str, sphere_id: str | None,
                  source: dict[str, Any]) -> dict[str, Any]:
    header, body = parse_header(text.splitlines())
    effects, riders, description = parse_body(body)
    economy = _economy(header.get("action_type"))
    if economy == "multi_mode":
        economy = None  # "Multi-Mode": the modes' own action types are read from the text (model typing), not the header
    header_economy = economy is not None
    if economy is None:
        # No Action Type header: a passive or a modifier of another technique.
        economy = "reaction" if re.search(r"\buse your Reaction\b", text, re.I) else "passive"
    coverage = "FULL" if effects and not riders else "CORE_WITH_RIDERS" if effects else "RIDERS_ONLY"
    return {
        "schema": SCHEMA,
        "mechanic_id": record_id,
        "kind": kind,
        "name": name,
        "sphere_id": sphere_id,
        "source": source,
        "activation": {"economy": economy, "trigger": header.get("trigger"), "requirement": header.get("requirement"),
                       "source": "printed_action_type" if header_economy else "inferred"},
        "header_economy": header_economy,
        "cost": _cost(header.get("cost")),
        "use_limit": _use_limit(header.get("use_limit")),
        "range": _range(header.get("range")),
        "area": _area(header.get("area")),
        "target": {"text": header.get("target")} if header.get("target") else None,
        "duration": _duration(header.get("duration"), header.get("concentration")),
        "effects": effects,
        "riders": riders,
        "description": description,
        "coverage": coverage,
        "provenance": {"method": PARSER_VERSION},
    }
