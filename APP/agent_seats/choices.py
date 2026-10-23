"""Controller-ranked complete plans for runner's letter-only small-model seat.

Consumes redacted observations and scores, never an engine or future dice rolls.
Plans use current menu keys; the runner checks each step against a fresh menu.
"""
import itertools
import re
from typing import NamedTuple

from .protocol import dao_line, validate_answer
from .tactics import tactical_moves, observed_grid, plausible_after_move
from .flight_options import representatives

# A byte ceiling is deliberately conservative: even byte-level tokenizers need
# no more than 800 content tokens by default. Providers can opt into a larger
# bounded menu. No server/tokenizer is needed to enforce its byte ceiling.
PROMPT_BYTES = 800
SYSTEM = (
    "Choose one complete plan; End is implicit. Reply with one offered letter only. "
    "Use only observations below. Dao is temperament, not a power."
)
REASONS = {
    "immediate_effect": "damage or recovery",
    "character_policy": "fits your fighting style",
    "target": "pressure on a visible foe",
    "defeat_prevention_or_finish": "finish or prevent defeat",
    "resource_use": "conserve resources",
    "position": "preferred distance",
    "tactical_position": "cover or fewer adjacent foes",
    "avoidable_risk": "reduce exposure",
    "survival": "survive at low HP",
    "ally_support": "support an ally",
    "policy_sequence": "fits your fighting style",
    "posture": "stand up first",
    "bystander": "avoid danger",
}


def decision_payload(prompt):
    """Turn the packed own-view frame into d1 criteria without adding facts.

    Shared mechanics belong to each referenced option. The same budget-packed
    labels and perception-safe situation are used by letter and decision seats.
    """
    state, criteria, shared = [], {}, []
    for line in prompt.splitlines():
        match = re.fullmatch(r"([A-L])\) (.+)", line)
        common = re.fullmatch(r"For ([A-L](?:, [A-L])*): (.+)", line)
        if match:
            criteria[match[1]] = match[2]
        elif common:
            shared.append((common[1].split(", "), common[2]))
        elif not line.startswith("Reply "):
            state.append(line)
    if not criteria:
        raise ValueError("Decision seat requires a packed choices menu.")
    for letters, effect in shared:
        for letter in letters:
            criteria[letter] += "; " + effect
    return {"state": "\n".join(state), "options": criteria}


class Option(NamedTuple):
    answer: dict
    label: str
    reason: str
    effect: str = ""


class TurnOptions(list):
    """Turn plans with nonserialized tactical-key metadata for packing.

    Geometry is classified once by the builder, not again on every initial
    and repair frame. The provider and answer protocol receive no metadata.
    """
    def __init__(self, options, tactical_keys=(), flight_keys=()):
        super().__init__(options)
        self.tactical_keys = frozenset(tactical_keys)
        self.tactical_purposes = dict(tactical_keys) if isinstance(tactical_keys, dict) else {}
        self.flight_keys = tuple(flight_keys)


def shortlist_limit(budget, maximum):
    """Small byte frames spend their space on fewer complete alternatives."""
    return min(maximum, 4 if budget <= 800 else 5 if budget <= 1200 else maximum)


def compact_move_purpose(purpose):
    """Shorten tactical intentions only; retain targets and risk warnings."""
    for old, new in (
        ("put distance between you and ", "retreat from "),
        ("reposition and keep ", "keep "),
        ("seek cover from visible threats", "seek cover"),
        ("seek cover near the last seen enemy position", "seek cover near last seen enemy position"),
        ("advance toward the last seen enemy position; watch the approach", "approach last seen enemy position"),
        ("take a covered spot and watch the approach to the last seen enemy position", "seek cover near last seen enemy position"),
        ("advance near observed cover and look for enemies", "seek cover and look for enemies"),
        ("advance carefully and look for enemies", "look for enemies"),
        ("reposition carefully around the visible threats", "reposition around visible threats"),
    ):
        purpose = purpose.replace(old, new)
    return purpose


def text(value, size):
    """Plain bounded prose, excluding internal identifiers and control lines."""
    value = re.sub(r"\b[\w.-]+:[\w:.-]+\b|\b\w+_\w+\b", "", str(value or ""))
    value = " ".join(value.split())
    if len(value) > size:
        value = value[:size-1].rsplit(" ", 1)[0] + "…"
    return value


def action_label(value):
    """Keep the complete action and variant; alternatives yield to the cap."""
    return text(value, len(str(value or "")) + 1)


def perceived_names(view):
    """Shared by plan rendering and packing; only observed actor/object names."""
    rows = [*view.get("actors", []), *view.get("objects", [])]
    names = {a.get("entity_id", a.get("id")): a.get("display_name", a.get("name", "creature")) for a in rows}
    collisions = list(names.values())
    for a in rows:
        key = a.get("entity_id", a.get("id"))
        p = a.get("position")
        if p and collisions.count(names[key]) > 1:
            names[key] += f" (at {p['x']},{p['y']})"
    return names


def step_label(row, names, purpose=""):
    """Render one complete step, including its whole charge and destination."""
    label = action_label(row.get("movement_label") or row["action"])
    if row.get("targets"):
        label += " on " + action_label(", ".join(names[t] for t in row["targets"]))
    if row.get("destination") and not row.get("movement_label"):
        p = row["destination"]
        label += f" to ({p['x']},{p['y']})"
        if p.get("z"):
            label += f", {p['z'] * 5} feet above ground"
        if purpose:
            label += " — " + action_label(purpose)
    cost = action_label(row.get("cost_label"))
    return label + (" (" + cost + ")" if cost else "")


def action_signatures(legal):
    """Runner continuation identities for actual Action/Bonus Action offers.

    Ignore changed area-origin squares and free preparations. A newly legal
    ability, target or mode after moving merits a fresh own-view decision.
    """
    return frozenset((r["action"], r.get("source"), tuple(r.get("targets", [])),
                      tuple(r.get("options", []))) for r in legal.values()
                     if r.get("economy") in {"ACTION", "BONUS_ACTION", "Action", "Bonus Action"})


def option_description(row, legal):
    """Drop whole descriptions of other named modes, never part of a rule.

    Menus often repeat an ability's entire printed list for each selected mode.
    Recognize siblings only from that same menu's named variants. Preserve the
    final mode's tail conservatively because it may contain common rules.
    """
    # A generic repetition of the action/target label adds no mechanics.
    description = str(row.get("choice_description") or row.get("description") or "")
    base, separator, variant = row["action"].rpartition(": ")
    if separator:
        siblings = {r["action"][len(base) + 2:] for r in legal.values()
                    if r["action"].startswith(base + ": ")}
        headings = sorted((match.start(), match.end(), mode)
                          for mode in siblings for match in
                          re.finditer(r"(?<!\w)" + re.escape(mode) + r":\s", description))
        if not any(mode == variant for _, _, mode in headings):
            return text(description, len(description) + 1)
        if headings and headings[-1][2] != variant:
            start, end, _ = headings[-1]
            # A trailing sentence naming the base ability or Realm scaling is
            # shared text, outside the last optional mode's description.
            tail = re.search(r"(?<=\.)\s+(?=" + re.escape(base) + r"\b|At [\w ]+ Realm\b)", description[end:])
            if tail:
                description = description[:start] + description[end + tail.end():]
        for index in range(len(headings) - 2, -1, -1):
            start, _, mode = headings[index]
            if mode != variant:
                description = description[:start] + description[headings[index + 1][0]:]
    return text(description, len(description) + 1)


def turn_options(view, legal, builtin, ranked=(), scores=None, limit=32,
                 choices_bytes=None, max_options=6):
    """Distinct ranked plans with a protected tactical move and neutral End.

    Each candidate ends the turn after its ranked action and, when possible,
    the top complementary action (move then act, or Action plus Bonus Action).
    Legality is deliberately checked again after the first step, rather than
    predicting a hit, hidden creature, or reaction. Smaller plan limits apply.
    Sparse menus offer fewer choices instead of inventing actions.
    """
    choices_bytes = PROMPT_BYTES if choices_bytes is None else choices_bytes
    end = next((k for k, v in legal.items() if v["action"] == "End turn"), None)
    if end is None:
        names = perceived_names(view)
        ordered = list(dict.fromkeys([builtin, *ranked, *legal]))
        return [Option({"plan": [key]}, step_label(legal[key], names), "resolve the current action",
                       option_description(legal[key], legal)) for key in ordered if key in legal
                and set(legal[key].get("targets", [])) <= set(names)][:max_options]
    known = {a["entity_id"] for a in view.get("actors", [])}
    known.update(o["id"] for o in view.get("objects", []))
    names = perceived_names(view)
    tactics = dict(tactical_moves(view, legal))
    flight_keys = representatives(view, legal, ranked)
    for key in flight_keys:
        tactics.setdefault(key, "")
    grid = observed_grid(view) if tactics else None
    ordered = list(dict.fromkeys([builtin, *ranked, *legal]))
    # Prefer a different action over another target/destination of the same
    # action. Ranking still chooses the best member of each action family;
    # the Dao-weighted built-in pick stays first, including a preferred End.
    primary = legal.get(builtin, {}).get("action")
    alternative = next((k for k in ordered if k in legal and k != end
                        and legal[k]["action"] != primary), None)
    if alternative is not None:
        ordered.remove(alternative)
        ordered.insert(1, alternative)
    target_alternative = next((k for k in ordered if k in legal and k != builtin
                               and legal[k]["action"] == primary
                               and legal[k].get("targets") != legal[builtin].get("targets")), None)
    if target_alternative:
        ordered.remove(target_alternative)
        ordered.insert(2 if alternative else 1, target_alternative)
    # Reserve a standalone tactical move before costly combinations. It must
    # survive budget packing even when the controller prefers End turn.
    if tactics:
        # Generate each purpose before many target/mode variants can fill the
        # candidate pool. Ranking still selects the action paired with it.
        movement_keys = list(dict.fromkeys([*flight_keys, *tactics]))
        movement_keys = [k for k in movement_keys if k != builtin]
        ordered = [k for k in ordered if k not in movement_keys]
        ordered[1:1] = movement_keys
    options, seen, plans_seen, families = [], set(), set(), {}
    for key in ordered:
        if key not in legal or key == end or limit < 1:
            continue
        row = legal[key]
        if not set(row.get("targets", [])) <= known:
            continue
        moving = row["action"] == "Move"
        signature = (row["action"], row.get("source"), tuple(row.get("targets", [])),
                     tuple(sorted((row.get("destination") or {}).items())) if moving else (),
                     tuple(row.get("options", [])))
        if signature in seen or (moving and key not in tactics and key != builtin):
            continue
        family = row["action"].partition(": ")[0]
        family_limit = (1 if row.get("economy") in {"NONE", "FREE", "Free"}
                        else 3 if max_options > 6 else 2)
        if not moving and key != builtin and families.get(family, 0) >= family_limit:
            continue
        seen.add(signature)
        if not moving:
            families[family] = families.get(family, 0) + 1
        plan = [key]
        if limit >= 2 and not moving:
            economy = row.get("economy")
            complement = {"Action": "Bonus Action", "Bonus Action": "Action",
                          "ACTION": "BONUS_ACTION", "BONUS_ACTION": "ACTION"}.get(economy)
            follow = next((k for k in ordered if k != key and k in legal
                           and legal[k]["action"] not in {"Move", "End turn"}
                           and (moving or (complement and legal[k].get("economy") == complement))
                           and set(legal[k].get("targets", [])) <= known), None)
            if follow and len(option_description(row, legal)) + len(option_description(legal[follow], legal)) < choices_bytes // 2:
                plan.append(follow)
        plan.append(end)
        # Execution is ordered: a buff before an attack can change that attack.
        plan_signature = tuple(plan)
        if plan_signature in plans_seen:
            continue
        plans_seen.add(plan_signature)
        def step(k):
            return step_label(legal[k], names, tactics.get(k, ""))
        score = (scores or {}).get(key, {})
        positive = [c for c in score.get("components", []) if c.get("value", 0) > 0 and c.get("component") in REASONS]
        positive.sort(key=lambda c: -c["value"])
        reason = REASONS[positive[0]["component"]] if positive else "fits your fighting style"
        effect = "; ".join(dict.fromkeys(
            option_description(legal[k], legal) for k in plan[:-1]))
        label = ", then ".join(step(k) for k in plan[:-1])
        if any(o.label == label and o.effect == effect for o in options):
            continue  # opaque option variants must not become identical letters
        options.append(Option({"plan": plan}, label, reason, effect))
        # Larger budgets earn genuinely different compositions, including
        # unused movement after acting. Each step is rechecked by the runner.
        if not moving and tactics and len(plan) - 1 < limit:
            for move in list(tactics)[:max_options // 3]:
                combined = [*plan[:-1], move, end]
                options.append(Option({"plan": combined},
                    label + ", then " + step(move), reason, effect))
        elif moving and key in tactics and limit >= 2:
            follow = next((k for k in ordered if k in legal
                           and legal[k]["action"] not in {"Move", "End turn"}
                           and set(legal[k].get("targets", [])) <= known
                           and plausible_after_move(view, legal[k], row["destination"], grid)), None)
            if follow:
                active = [key, follow]
                complement = {"Action": "Bonus Action", "Bonus Action": "Action",
                              "ACTION": "BONUS_ACTION", "BONUS_ACTION": "ACTION"}.get(legal[follow].get("economy"))
                if complement and limit >= 3:
                    bonus = next((k for k in ordered if k not in active and k in legal
                                  and legal[k].get("economy") == complement
                                  and set(legal[k].get("targets", [])) <= known
                                  and plausible_after_move(view, legal[k], row["destination"], grid)), None)
                    if bonus and len(option_description(legal[follow], legal)) + len(option_description(legal[bonus], legal)) < choices_bytes // 2:
                        active.append(bonus)
                combined = [*active, end]
                options.append(Option({"plan": combined}, ", then ".join(step(k) for k in active),
                                      reason, "; ".join(dict.fromkeys(option_description(legal[k], legal) for k in active))))
        if len(options) >= max_options * 6:
            break
    # Composition is used only to prioritize diversity, never to declare
    # reordered execution equivalent. Offer a reorder only when no different
    # action/target plan is available (End is the separate safe fallback).
    if options:
        composition = lambda o: tuple(sorted(o.answer["plan"][:-1]))
        primary_composition = composition(options[0])
        different = [o for o in options[1:] if composition(o) != primary_composition]
        reorders = [o for o in options[1:] if composition(o) == primary_composition]
        pool = []
        for option in [options[0], *(different if different else reorders[:1])]:
            if not any(o.label == option.label and o.effect == option.effect for o in pool):
                pool.append(option)
        # Movement gets a slot even if optional action combinations came first.
        tactical_option = next((o for o in pool if len(o.answer["plan"]) == 2
                                and o.answer["plan"][0] in tactics), None)
        if tactical_option and tactical_option != pool[0]:
            pool.remove(tactical_option)
            pool.insert(1, tactical_option)
        if tactics:
            # Spend extra slots on different purposes and action families
            # before more variants of one action, including free preparations.
            selected = [pool[0]]
            def take(option):
                if option is not None and option not in selected:
                    selected.append(option)
            take(tactical_option)
            for key in flight_keys:
                take(next((o for o in pool if o.answer["plan"] == [key, end]), None))
            take(next((o for o in pool if len(o.answer["plan"]) > 2
                       and o.answer["plan"][0] == pool[0].answer["plan"][0]
                       and any(legal[k]["action"] == "Move" for k in o.answer["plan"])), None))
            if max_options > 6:
                moving_first = [o for o in pool if len(o.answer["plan"]) > 2
                                and o.answer["plan"][0] in tactics]
                take(next((o for o in moving_first if o.answer["plan"][1] == builtin),
                          next((o for o in moving_first
                                if legal[o.answer["plan"][1]].get("economy") in {"Action", "ACTION"}),
                               next(iter(moving_first), None))))
                for o in pool:
                    if len(o.answer["plan"]) == 2 and o.answer["plan"][0] in tactics:
                        take(o)
                    if len(selected) >= 5:
                        break
            def action_family(o):
                return tuple(legal[k]["action"].partition(": ")[0]
                             for k in o.answer["plan"] if legal[k]["action"] not in {"Move", "End turn"})
            used_families = {action_family(o) for o in selected}
            for o in pool:
                family = action_family(o)
                if family and family not in used_families:
                    take(o)
                    used_families.add(family)
            for o in pool:
                take(o)
            pool = selected
        options = pool[:max_options - 1]
    safe_end = Option({"plan": [end]}, "End turn here", "", "take no further action")
    if builtin == end:
        options.insert(0, safe_end)
    else:
        options.append(safe_end)
    # Retain a bounded shortlist with different active plans before further
    # destinations of one mode. Budget packing below selects at most six.
    if builtin != end and limit >= 1 and not any(o[0]["plan"][0] == builtin for o in options):
        raise ValueError("Built-in choice is outside own-view menu")
    return TurnOptions(options, tactics, flight_keys)


def reaction_options(legal, builtin):
    """Complete responses; mechanics are never shortened to fit a menu.

    The prompt shares ability/summary once and can remove alternatives/context.
    Labels, descriptions and spend amounts belong to the executable choice.
    """
    options = []
    choice = legal.get("choice") or {}
    rows = {o["id"]: o for o in choice.get("options", [])}
    ability = str(legal.get("ability", "reaction"))
    def prose(value):
        # Sanitize identifiers/control lines without truncating mechanics.
        return text(value, len(str(value or "")) + 1)
    def add(answer, reason):
        answer = validate_answer(answer, legal, "REACTION")
        if any(o[0] == answer for o in options):
            return
        if answer["selection"] == "DECLINE":
            label = "Pass; spend nothing"
            effect = ""
        else:
            labels, descriptions = [], []
            for i in answer["option_ids"]:
                row = rows[i]
                label = str(row.get("label") or "offered response")
                label = label.removeprefix(ability + ": ")
                labels.append(prose(label))
                description = prose(row.get("description"))
                if description and description not in descriptions:
                    descriptions.append(description)
            label = "Use" + (": " + "; ".join(labels) if labels else " this reaction")
            effect = "; ".join(descriptions)
            if answer["spend"]:
                label += f"; spend {answer['spend']}"
        # Only mechanical equality (checked above) establishes duplication.
        options.append(Option(answer, label, reason, effect))
    add(builtin, "controller's pick")
    maximum = min(choice.get("maximum", 0), len(rows))
    # Lazy enumeration: never materialize a large combinatorial menu.
    for count in range(choice.get("minimum", 0), maximum + 1):
        for ids in itertools.islice(itertools.combinations(rows, count), 6):
            for spend in legal.get("spend_options", [0]):
                if len(options) >= 5:
                    break
                add({"selection": "USE", "option_ids": list(ids), "spend": spend}, "use an offered response")
            if len(options) >= 5:
                break
        if len(options) >= 5:
            break
    if choice.get("allow_decline", True):
        add({"selection": "DECLINE", "option_ids": [], "spend": 0}, "save the reaction")
    return options


def build_prompt(view, options, kind, legal, repair=None,
                 choices_bytes=None, max_options=6):
    """Return bounded text and the exact letter-to-answer mapping offered.

    Own HP/position and all perceived actor positions remain mandatory, as do
    Dao and complete mechanics/costs. Optional words and whole alternatives
    yield first. A long built-in alternative can yield to Move plus End;
    retained mechanics are complete. Required overflow fails before dispatch.
    """
    choices_bytes = PROMPT_BYTES if choices_bytes is None else choices_bytes
    max_options = shortlist_limit(choices_bytes, max_options)
    own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
    dao = dao_line(view)
    p = own.get("position")
    others = [a for a in view["actors"] if a["entity_id"] != view["fighter"]]
    others.sort(key=lambda a: a["entity_id"])
    hp = own.get("hit_points", "unknown")
    if isinstance(hp, dict):
        hp = f"{hp.get('current', '?')}/{hp.get('maximum', '?')}" + (f" +{hp['temporary']} temporary" if hp.get("temporary") else "")
    def location(p):
        return (f"({p['x']},{p['y']})" + (f", {p['z'] * 5} ft above ground" if p.get("z") else "")) if p else "unknown position"
    position = location(p)
    situation = [f"HP: {action_label(hp)} at {position}. Squares are 5 feet."]
    for allied, label in [(False, "Threat"), (True, "Ally")]:
        for actor in (a for a in others if (a.get("team_id") == own.get("team_id")) == allied):
            at = actor.get("position")
            where = location(at)
            observed_label = "Defeated" if actor.get("active") is False else label
            situation.append(f"{observed_label}: {action_label(actor.get('display_name') or 'creature')} at {where}.")
    situation.extend(view.get('information') or [])
    # Same facts, with optional connective words/punctuation removed.
    minimum_situation = [situation[0].replace(". Squares are 5 feet.", " 5ft/square")]
    minimum_situation += [line.rstrip(".") for line in situation[1:]]
    reaction = kind == "REACTION"
    follow_up = not reaction and not any(row["action"] == "End turn" for row in legal.values())
    def reaction_facts(compact=False, minimum=False):
        """Share exact repeated activation names; never summarize mechanics."""
        def complete(value):
            return text(value, len(str(value or "")) + 1)
        ability = str(legal.get("ability") or "reaction")
        trigger = str(legal.get("trigger") or legal.get("action") or "offered reaction")
        affected = str(legal.get("affected") or "you")
        if compact:
            # The ability and affected creature are already explicit below.
            # Remove only this exact repeated sentence, not arbitrary prose.
            trigger = trigger.removesuffix(f" — {affected} uses {ability}.")
            if trigger.startswith(ability + " ("):
                trigger = trigger[len(ability) + 1:]
            if minimum:
                # Optional connective words, not the action, cost or timing.
                trigger = re.sub(r"\btake the\s+", "", trigger)
                trigger = re.sub(r"\bor the\s+", "or ", trigger)
        # "You" is already the affected creature in an explicit own-target
        # trigger; share that fact instead of repeating "; for you".
        shared_self = (minimum and affected == "you" and
                       re.search(r"\b(?:attacks|hits|targets|affecting|affects)\s+you\b", trigger, re.I))
        facts = ["Reaction: " + complete(ability) +
                 ("\n" if minimum else ". Trigger: ") +
                 complete(trigger.removeprefix(ability + ": ")) +
                 ("" if shared_self else ("; for " if minimum else "; affects ") + complete(affected))]
        summary = complete(legal.get("summary") or legal.get("rules"))
        if summary:
            facts.append(("" if minimum else "If used: ") + summary)
        return facts
    required = reaction_facts() if reaction else []
    if repair:
        required.append("Invalid reply. Reply with one letter.")
    def fits(prompt, minimum=False):
        # Reserve the corresponding repair feedback in initial frames so a
        # repair does not unexpectedly lose its stable identity/Dao prefix.
        reserve = 0 if repair else len(("\nInvalid reply" if minimum else
                                       "\nInvalid reply. Reply with one letter.").encode())
        return len(prompt.encode("utf-8")) + reserve <= choices_bytes
    def option_lines(selected, reasons=False, compact=False):
        def label(option):
            value = option.label
            if compact and not reaction:
                for purpose in getattr(options, "tactical_purposes", {}).values():
                    value = value.replace(" — " + purpose, " — " + compact_move_purpose(purpose))
            return value
        effects = {}
        by_option = []
        for i, o in enumerate(selected):
            # Share each complete step's mechanics, so adding Move after an
            # action doesn't repeat that action's entire printed rules.
            prose = ([o.effect] if reaction or len(o.answer["plan"]) == 1 else
                     list(dict.fromkeys(option_description(legal[k], legal)
                                        for k in o.answer["plan"][:-1])))
            prose = [effect for effect in prose if effect]
            by_option.append(prose)
            for effect in prose:
                effects.setdefault(effect, []).append(chr(65+i))
        shared = {effect for effect, letters in effects.items() if not reaction and len(letters) > 1}
        lines = [f"{chr(65+i)}) {label(o)}" +
                 (": " + "; ".join(e for e in by_option[i] if e not in shared)
                  if any(e not in shared for e in by_option[i]) else "") +
                 (f" — {o.reason}." if not reaction and reasons and o.reason else "")
                 for i, o in enumerate(selected)]
        return lines + ["For " + ", ".join(effects[effect]) + ": " + effect for effect in effects if effect in shared]
    selected = list(options)
    tactical_keys = getattr(options, "tactical_keys", ()) if not reaction else ()
    flight_keys = getattr(options, "flight_keys", ()) if not reaction else ()
    while True:
        # Advertise the actual packed range, never removed alternatives.
        letters = "A" if len(selected) == 1 else "A-" + chr(64 + len(selected))
        instructions = SYSTEM.replace("Choose one complete plan; End is implicit.", "Choose one follow-up to resolve the current action.") if follow_up else SYSTEM
        prefix = instructions + "\nFighter: " + action_label(own.get("display_name")) + "\n" + dao + "\nSituation:\n"
        # Reasons are optional; mechanics and situation are complete or fail closed.
        for reasons in ((False,) if reaction else (True, False)):
            lines = option_lines(selected, reasons, compact=choices_bytes <= 1200)
            prompt = prefix + "\n".join(situation + required + ["Reply " + letters] + lines)
            if len(selected) <= max_options and fits(prompt):
                return prompt, {chr(65+i): o.answer for i, o in enumerate(selected)}
        # Repeated headings and fighter identity are optional; situation and
        # mechanics aren't. Try compact wording before dropping an alternative.
        if len(selected) <= (5 if not reaction and choices_bytes <= 1200 else 3):
            facts = reaction_facts(compact=True, minimum=True) if reaction else [
                "Choose one follow-up to resolve the current action." if follow_up else "Plans end your turn."]
            if repair:
                facts.append("Invalid reply")
            # Whole optional alternatives yield before source Dao clauses.
            # Only the mandatory two-choice frame may need fewer clauses.
            for width in ((100,) if len(selected) > 2 else (100, 70, 45, 25, 10)):
                for context in (situation, minimum_situation):
                    prompt = "Reply " + letters + "\n" + dao_line(view, width) + "\nSituation:\n" + "\n".join(context + facts + option_lines(selected, compact=True))
                    if len(selected) <= max_options and fits(prompt, minimum=True):
                        return prompt, {chr(65+i): o.answer for i, o in enumerate(selected)}
        # Keep the built-in plan (first) and safe End/Pass (last). Long complete
        # plans or mandatory reactions may need fewer than four choices; never
        # hide a step by chopping its label to meet the byte budget.
        if len(selected) <= 2:
            break
        last = selected[-1].answer
        safe_last = (last.get("selection") == "DECLINE" or
                     (kind == "TURN" and len(last["plan"]) == 1 and legal[last["plan"][0]]["action"] == "End turn"))
        if reaction:
            selected.pop(-2 if safe_last else -1)
        else:
            # Repeated complete descriptions are shared, so prefer removing
            # an expensive unique alternative over an affordable target choice.
            stop = len(selected) - int(safe_last)
            mandatory_move = next((i for key in flight_keys for i, o in enumerate(selected)
                                   if key in o.answer["plan"]), None)
            if mandatory_move is None:
                mandatory_move = next((i for i, o in enumerate(selected)
                                       if any(k in tactical_keys for k in o.answer["plan"])), None)
            if mandatory_move is None:
                mandatory_move = next((i for i, o in enumerate(selected)
                                       if any(legal[k]["action"] == "Move" for k in o.answer["plan"])), None)
            candidates = [i for i in range(1, stop) if i != mandatory_move]
            if not candidates:
                # Keep complete mandatory facts. Remove optional actions from
                # the protected move plan before declaring overflow.
                if mandatory_move is not None:
                    old = selected[mandatory_move]
                    move = next(k for k in old.answer["plan"] if legal[k]["action"] == "Move")
                    standalone = next((o for o in options if o.answer["plan"] == [move, old.answer["plan"][-1]]), None)
                    if standalone and standalone != old:
                        selected[mandatory_move] = standalone
                        continue
                first = selected[0]
                if len(first.answer["plan"]) > 2:
                    key = first.answer["plan"][0]
                    selected[0] = Option({"plan": [key, first.answer["plan"][-1]]},
                                         step_label(legal[key], perceived_names(view)), first.reason,
                                         option_description(legal[key], legal))
                    continue
                if mandatory_move not in (None, 0) and len(selected) > 2:
                    # A complete expensive controller pick may leave no room
                    # for movement at 800 bytes. Drop that whole alternative,
                    # never its mechanics or the required tactical move.
                    selected.pop(0)
                    continue
                break
            size = len("\n".join(option_lines(selected)).encode())
            drop = max(candidates, key=lambda i: (
                size - len("\n".join(option_lines(selected[:i] + selected[i+1:])).encode()), i))
            selected.pop(drop)
    raise ValueError("Choices mandatory frame exceeds prompt budget")


def parse_letter(reply, offered):
    """Recover a leading plain/bold letter and optional trailing reasoning.

    A second letter or explicit selection is ambiguous. English articles and
    the pronoun I in reasoning are not selections, but their surrounding words
    must support that reading; uncertain references fail closed for repair.
    No recovery grants legality.
    """
    if not isinstance(reply, str) or len(reply) > 1024:
        raise ValueError("Reply with one offered letter")
    match = re.fullmatch(r"\s*(?:option\s+)?(?:\*\*([A-Za-z])\*\*|([A-Za-z]))(?:\s*$|[).:\-\s]+(.*))",
                         reply, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("Reply with one offered letter")
    letter = (match[1] or match[2]).upper()
    suffix = match[3] or ""
    # These two English words are also option letters. An article needs a
    # recognizable noun/adjective, while a pronoun needs a recognizable verb.
    # This deliberately small reasoning grammar rejects unfamiliar prose for
    # repair rather than guessing whether a bare letter names another option.
    for word in re.finditer(r"\b[ai]\b", suffix, re.I):
        following = re.match(r"\s+([A-Za-z]{2,})\b", suffix[word.end():])
        next_word = following[1].lower() if following else ""
        if word[0].lower() == "a":
            ambiguous = next_word not in {
                "move", "resource", "visible", "defensive", "target", "creature",
                "foe", "fighter", "position", "step", "plan", "turn", "reaction",
                "bonus", "safe", "safer", "better", "different", "useful", "good",
                "single", "small", "strong", "melee", "ranged", "weapon",
                "spell", "chance", "cost", "risk", "threat", "hit", "strike",
                "shield", "counter", "dodge", "retreat", "tactical", "nearby",
                "clear", "new", "short", "long", "full", "quick", "free",
            }
        else:
            ambiguous = next_word not in {
                "attack", "choose", "select", "pick", "prefer", "think", "want",
                "will", "would", "should", "could", "can", "must", "might",
                "may", "am", "have", "do", "use", "take", "move", "conserve",
                "avoid", "need", "believe", "expect", "favor", "favour",
            }
        if ambiguous:
            raise ValueError("Reply with one offered letter")
    if (letter not in offered or
            re.search(r"\*\*[A-Za-z]\*\*", suffix) or
            re.fullmatch(r"\s*(?:\*\*)?[aAiI](?:\*\*)?\s*", suffix) or
            re.search(r"\b[aAiI](?:\*\*)?[).:\-](?:\s|$)", suffix) or
            re.search(r"\b(?:[A-HJ-Zb-hj-z])\b", suffix) or
            re.search(r"\b(?:option|choice|letter|actually|or)\s+(?:\*\*)?[a-z]\b", suffix, re.I) or
            re.search(r"\b(?:choose|select)\s+(?:\*\*)?[b-z]\b", suffix, re.I)):
        raise ValueError("Reply with one offered letter")
    return offered[letter]
