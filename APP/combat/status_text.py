"""Read-only status descriptions shared by table hovers and the pop-out sheet.

Rules come from stored descriptions, typed condition rules and the owner's printed
ability text. Plug-ins can describe their own state via status_description; this
module never writes engine state, modifies a compiled bundle or resolves effects.
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

from .condition_text import all_conditions, mechanics
from .display_text import printed_headers
from .player_text import explain_cp, plain as _plain, source_plain as _source_plain
from . import ext
from . import hover_text

# What a mark does by itself, in plain words. Named so the layout can recognise
# that the mark's summary line already says this and must not repeat it.
MARK_HANDLING = "The mark does nothing on its own; the abilities that use it do something with it."


def zone_sight_text(profile: dict[str, Any], rules: dict[str, Any]) -> str:
    """Describe targeting/zones metadata, never infer mechanics from cloud art.

    The client fallback in zones.js follows this same presentation contract.
    Percentages are optional owner policy; exceptions remain conditional on the
    viewer's perception rather than promising a penalty for every attack.
    """
    visual, wall = profile.get("visual") or {}, profile.get("wall") or {}
    heavy = not wall and (profile.get("obscured") == "heavy" or visual.get("darkness"))
    light = (profile.get("lightly_obscured") is True or profile.get("obscured") == "light"
             or visual.get("light") == "dim")
    through = bool(wall.get("obscures"))
    if not (heavy or light or through):
        return ("Visual cloud only: this area adds no concealment."
                if visual.get("obscured") and not wall.get("blocks_sight")
                and not (wall.get("blocks_movement") and not wall.get("see_through")) else "")
    parts = []
    if heavy:
        name = profile.get("name") or "this area"
        parts.append("Heavily obscured: creatures inside cannot see out, but creatures outside can see in."
                     if visual.get("sees") == "inward" else
                     f"Heavily obscured ({name}): you can't see into it. Creatures inside cannot be seen from outside or by others inside.")
    elif light:
        parts.append("Lightly obscured: creatures inside are still visible.")
    if through:
        parts.append("This wall hides creatures on the other side from its creator's foes."
                     if wall.get("obscures") == "hostile" else "This wall hides creatures on the other side.")
    parts.append("Attacks against creatures you can't see have Disadvantage.")
    total = rules.get("total_concealment_miss_percent") or 0
    partial = rules.get("concealment_miss_percent") or 0
    if (heavy or through) and total:
        parts.append(f"If you can't see the target, attacks also have a {total}% miss chance (total concealment).")
    if light and partial:
        parts.append(f"Sight-based attacks against visible creatures inside have a {partial}% miss chance (concealment).")
    if heavy and profile.get("owner_sees"):
        parts.append("Its creator sees through it normally.")
    if profile.get("obscured") == "heavy" and profile.get("team_sees"):
        if heavy and profile.get("owner_sees"):
            parts.append("Its creator's teammates see creatures inside as lightly obscured.")
        if partial:
            parts.append(f"Teammates' sight-based attacks against visible creatures inside have a {partial}% miss chance (concealment).")
    parts.append("Senses that perceive the target without sight bypass this concealment within their range; "
                 "senses that see through this effect bypass its sight blocking.")
    return " ".join(parts)


def _sentences(parts: list[str]) -> str:
    """Join stored description sentences, deduplicated, each ending properly.

    One implementation for ``rule_text`` and for the hover's body, so the two
    never disagree about where a sentence ends (a part already ending in a
    full stop keeps it; one without gets exactly one).
    """
    return " ".join(part.rstrip(". ") + "." if part[-1:] not in ".!?" else part
                    for part in dict.fromkeys(part.strip() for part in parts if part.strip()))


RULES_TEXT_PATH = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/rules_text.json"


@functools.lru_cache(maxsize=2)
def _printed_rules_at(path: str, mtime_ns: int, size: int) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def printed_rules() -> dict[str, str]:
    """The owner's printed rules text, re-read whenever the file changes (owner edits while playtesting).

    Keyed by the file's identity (path, mtime, size), the same identity combat/tooltip_digest.py hashes against,
    so a "Summary pending" card and the full text under it always come from one version. Saved fights are not
    affected: their stored button descriptions keep the wording they were compiled with; only live hover text
    resolved from this file follows the edit.
    """
    path = RULES_TEXT_PATH
    try:
        stat = path.stat()
    except OSError:
        return {}
    return _printed_rules_at(str(path), stat.st_mtime_ns, stat.st_size)


printed_rules.cache_clear = _printed_rules_at.cache_clear  # existing callers/tests may clear it


def plain(text: Any) -> str:
    # The owner's printed records carry an authoring header block (Action Type, Range,
    # Duration, Cost, Concentration, Tags).  Put those in words a player can read
    # before the run-on cleanup below, so a free ability never prints "Cost: None" and
    # two header lines that lost their break are split back apart (combat/display_text).
    text = printed_headers(text)
    return _plain(text)


def source_plain(text: Any) -> str:
    """``plain`` for a printed quote: the owner's words without a player-card reflow."""
    return _source_plain(printed_headers(text))


def markup(text: Any) -> str:
    """Printed text with its ``**Label:**`` fields and line structure intact.

    ``plain()`` is right for prose but flattens a printed card: stripping the bold
    leaves "Type: No Action" glued to the heading, and joining the lines loses the
    field boundaries the shared hover layout (combat/hover_text.py) needs. The
    internal-source strips are the same ones ``plain()`` applies.
    """
    text = re.sub(r"\s*\((?:combat/|combat\.|typed_executor)[^)]*\)", "", str(text or ""))
    text = re.sub(r"\s*\(owner[^)]*\)", "", text)
    text = re.sub(r";\s*combat/[^.\s]+\.py[^.]*\.", ".", text)
    text = re.sub(r",?\s*worker\s+[\w-]+\s+\d{4}-\d{2}-\d{2}", "", text)
    return "\n".join(line.rstrip() for line in text.split("\n") if line.strip())


# The print scales some clauses by Cultivation Level and abbreviates it ("5 x CL pounds"). A player who knows only
# basic D&D does not know what CL means, so the abbreviation is never shown to one.
_CL_SCALE = re.compile(r"(\d+)\s*[x×]\s*CL\b")
_CL_ABBREVIATION = re.compile(r"\bCL\b")


def area_wording(text: Any, cultivation_level: Any = None) -> str:
    """A shaped area's own printed text, in words a player who knows only basic D&D can act on.

    Used for the inside-clauses the zone card shows (MMX114). The print scales a few of them by Cultivation Level
    ("You may move objects weighing up to 5 x CL pounds"): the area's owner, whose Cultivation Level ``cultivation_level``
    is, gets the actual weight ("weighing up to 100 pounds"); anything read about a character whose level this view does
    not carry gets the full phrase instead of the abbreviation ("weighing up to 5 x your Cultivation Level in pounds").
    Keys on the printed abbreviation, never on a talent id, and is inert on text without one.
    """
    text = plain(text)
    try:
        level = int(cultivation_level or 0)
    except (TypeError, ValueError):
        level = 0

    def scaled(match: re.Match[str]) -> str:
        return str(int(match.group(1)) * level) if level > 0 else f"{match.group(1)} x your Cultivation Level in"

    return _CL_ABBREVIATION.sub("Cultivation Level", _CL_SCALE.sub(scaled, text))


def printed_excerpt(record: str, label: str = "", *, with_markup: bool = False,
                    source: bool = False) -> str:
    """Use the selected printed section, preserving all its rules and exceptions.

    A source record already scoped to a talent is left intact. For larger records,
    an exact heading match selects the option through the next peer heading.
    Never truncate at a character count or lose the end of a mechanical sentence.

    ``with_markup`` keeps the printed ``**Label:**`` fields and line breaks so
    combat/hover_text.py can lay the card out; the default stays the flattened
    prose every existing caller expects. ``source`` keeps the printed wording for
    a surface that promises to quote it (a condition-chip catalogue entry): it
    skips the reviewed card projection that reorders and relabels the record.
    """
    flatten = markup if with_markup else (source_plain if source else plain)
    text = printed_rules().get(record, "")
    headings = list(re.finditer(r"(?m)^(#{2,})\s+(.+)$", text))
    wanted = label.split(": ", 1)[-1]
    wanted = re.sub(r"\s*\((?:Concentration|Persistent)\)$", "", wanted).strip().casefold()
    for i, heading in enumerate(headings):
        name = re.sub(r"\s*[-–]\s*(?:Meld|Talent|Augment)$", "", heading[2]).strip().casefold()
        if wanted and name == wanted:
            end = next((h.start() for h in headings[i + 1:] if len(h[1]) <= len(heading[1])), len(text))
            return flatten(text[heading.start():end])
    return flatten(text)


def _parameters(engine: Any, source: str) -> dict[str, Any]:
    action = engine.action_catalog.get(source)
    return dict(getattr(action, "parameters", None) or {})


def _record(source: str, parameters: dict[str, Any], data: dict[str, Any]) -> str:
    texts = printed_rules()
    typed = parameters.get("typed") or {}
    candidates = [data.get("talent"), data.get("record"), parameters.get("meld_talent"),
                  typed.get("option_of"), typed.get("source"), typed.get("forged_from"), data.get("source"), source,
                  source.partition(":")[-1],
                  source.split(".", 2)[-1].split("#", 1)[0],
                  source.split(".", 2)[-1].split("+", 1)[0]]
    return next((str(key) for key in candidates if key and key in texts), "")


def duration_text(expiry: str, data: dict[str, Any], typed: dict[str, Any],
                  source_name: str, holder_name: str, actors: dict[str, str], engine: Any) -> str:
    """Translate engine lifetime tokens without exposing internal IDs to players."""
    duration = data.get("duration") or typed.get("duration") or {}
    duration = duration if isinstance(duration, dict) else {}
    concentration = bool(data.get("concentration", duration.get("concentration", False))) or expiry == "CONCENTRATION_END"
    kind = str(duration.get("kind") or "") if isinstance(duration, dict) else ""
    amount = duration.get("amount") if isinstance(duration, dict) else None
    timed = f"{amount} {kind.rstrip('s')}{'' if amount == 1 else 's'}" if amount and kind in {"rounds", "minutes", "hours"} else ""
    if concentration:
        return "while concentrating" + (f", up to {timed}" if timed else "")
    deadline = data.get("end_after_owner_turn")
    if deadline is not None:
        owner = engine.state.actors.get(data.get("owner_id")) if engine is not None else None
        counter = getattr(owner, "turns_started", None)
        turn = ("current turn" if counter == deadline else "next turn" if counter is not None and deadline == counter + 1
                else f"turn {deadline}")
        return f"until the end of {source_name}'s {turn}"
    deadline = data.get("start_of_owner_turn")
    if deadline is not None:
        owner = engine.state.actors.get(data.get("owner_id")) if engine is not None else None
        counter = getattr(owner, "turns_started", None)
        turn = ("current turn" if counter == deadline else "next turn" if counter is not None and deadline == counter + 1
                else f"turn {deadline}")
        return f"until the start of {source_name}'s {turn}"
    token, _, rest = str(expiry or "UNTIL_REMOVED").partition(":")
    if token in {"START_OF_SOURCE_NEXT_TURN", "START_OF_MARKER_NEXT_TURN"}:
        return f"until the start of {source_name}'s next turn"
    if token in {"START_OF_SELF_NEXT_TURN", "START_OF_TARGET_NEXT_TURN"}:
        # These two legacy tokens share the sealed source-or-holder sweep.
        if source_name == holder_name:
            return f"until the start of {source_name}'s next turn"
        return f"until the start of {source_name}'s or {holder_name}'s next turn, whichever comes first"
    if token == "END_OF_MARKER_NEXT_TURN":
        return f"until the end of {source_name}'s next turn"
    if token == "END_OF_HOLDER_NEXT_TURN":
        current = actors.get(getattr(engine.state, "current_actor_id", ""), "") if engine is not None else ""
        if current == holder_name:
            return f"until the end of {holder_name}'s current turn"
        return f"until the end of {holder_name}'s next turn"
    if token == "END_OF_CURRENT_TURN":
        current = actors.get(getattr(engine.state, "current_actor_id", ""), "the current creature")
        return f"until the end of {current}'s current turn"
    if token in {"START_OF_TURN_AT", "END_OF_TURN_AT", "END_OF_SOURCE_TURN_AT"}:
        who, _, count = rest.rpartition(":") if token != "END_OF_SOURCE_TURN_AT" else ("", "", rest)
        name = actors.get(who, source_name)
        moment = "start" if token.startswith("START") else "end"
        actor = engine.state.actors.get(who) if engine is not None and who else None
        counter = getattr(actor, "turns_started", None)
        next_turn = counter is not None and count.isdigit() and int(count) == int(counter) + 1
        turn = "next turn" if next_turn else f"turn {count}"
        return f"{timed + '; ' if timed else ''}until the {moment} of {name}'s {turn}"
    if token == "START_OF_SLOT_AT":
        round_number, _, slot = rest.partition(":")
        order = getattr(engine.state, "initiative_order", ()) if engine is not None else ()
        turn_actor = order[int(slot)] if slot.isdigit() and int(slot) < len(order) else ""
        name = actors.get(turn_actor, "the triggering creature")
        return f"{timed + '; ' if timed else ''}until the start of {name}'s turn in round {round_number}"
    if token == "STAND_UP":
        return "until it stands up"
    if token == "CONSUMED":
        return "until used or removed"
    if data.get("until_round"):
        return f"{timed + '; ' if timed else ''}until the start of {holder_name}'s turn in round {data['until_round']}"
    # UNTIL_REMOVED does not promise that the engine enforces a printed clock.
    return f"until removed (printed duration: {timed})" if timed else "until removed"


def describe(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any],
             actors: dict[str, str], definitions: dict[str, str], *, kind: str = "condition",
             condition_rules: dict[str, Any] | None = None, mark_readings: dict[str, str] | None = None) -> dict[str, str]:
    """Build specific rule text plus provenance, lifetime and evidenced handling.

    rule_text remains empty when no source supports a description, allowing
    coverage checks to distinguish unresolved state from successful descriptions.
    """
    source = str(row.get("source_definition_id") or data.get("source") or "")
    parameters = _parameters(engine, source)
    typed = parameters.get("typed") or {}
    record = _record(source, parameters, data)
    label = str(row.get("display_name") or data.get("label") or "")
    cid = str(row.get("condition_id") or "")
    suppressed = kind == "condition" and cid.startswith("condition:typed.suppressed.")
    key = cid.split(".")[-1]
    owner = str(row.get("source_actor_id") or row.get("owner_id") or "")
    mark = cid.removeprefix("condition:typed.mark.").partition(".") if cid.startswith("condition:typed.mark.") else None
    if mark:
        key, _, mark_owner = mark
        owner = owner or mark_owner
    source_name = actors.get(owner, "Map" if data.get("map") else "Unknown applier")
    source_ability = definitions.get(source) or plain(printed_rules().get(record, "").splitlines()[0] if record else "") or "Source ability unavailable in this saved fight"
    if data.get("map"):
        source_ability = f"{label or data.get('name') or 'Map'} terrain"
    info = (condition_rules or {}).get(key) or {}
    rule = {**(info.get("rule") or {}), **(data.get("rule") or {})}
    native = "; ".join(mechanics(rule) if data.get("rule") else info.get("mechanics") or [])
    if (data.get("rule") or {}).get("next") and native:
        native += "; used up by the next applicable roll"
    reading = plain(data.get("reading") or data.get("description") or row.get("detail") or info.get("reading") or rule.get("_rule") or "")
    selected = printed_excerpt(record, label) if record else ""
    # The same printed card with its "**Label:**" fields intact, for the shared
    # hover layout. The flattened copy above still builds ``rule_text`` unchanged.
    selected_markup = printed_excerpt(record, label, with_markup=True) if record else ""
    parts = [native, reading]
    readers_line = ""
    if mark:
        parts.append((mark_readings or {}).get(key, ""))
        mark_name = key.replace("_", " ").casefold()
        readers = sorted({definitions.get(action_id, "") for action_id, action in engine.action_catalog.items()
                          if getattr(action, "owner_id", None) == owner
                          and mark_name in printed_rules().get(_record(action_id, _parameters(engine, action_id), {}), "").casefold()}
                         - {"", source_ability})
        if readers:
            # rule_text keeps its own sentence: it is the raw channel the coverage
            # checks read, and for some marks it is the only rule text there is.
            parts.append(f"{source_name}'s abilities that use it: {', '.join(readers[:8])}.")
            # The hover shows the same fact as a labelled line (owner 2026-10-03:
            # it opened the Edict Seal card and read like an engine note).
            readers_line = f"Used by: {', '.join(readers[:8])}."
    # Generic readings explain a condition category; selected text supplies its
    # actual option/ability. Include both rather than substitute a generic label.
    if selected and selected not in reading:
        parts.append(selected)
    if not any(parts) and info.get("reading"):
        parts.append(plain(info["reading"]))
    elif info.get("reading") and not reading and not mark:
        parts.insert(1, plain(info["reading"]))
    # A descriptor failure must not create observational-hook error events.
    supplied = [] if suppressed else ext.query("status_description", engine, holder, row, data)
    handling = ""
    duration_override = None
    from .ext.resource_readings import paying_pool, expand_cp
    pool = None
    display_name = ""
    # A plug-in that supplies ``rules`` owns this row's card. The printed record it
    # was read from is then superseded: laying the old card out beside the
    # replacement would show a scoped selector's parent ability and its sibling
    # options as though they applied here, which is exactly the scope the setting
    # hook exists to narrow. ``override_markup`` is the plug-in's own labelled
    # form, and ``override_parts`` are the flattened sentences it already covers.
    override_markup = ""
    override_parts: set[str] = set()
    override_text = ""
    rules_supplied = False
    conceal_source = False
    for description in supplied:
        conceal_source = conceal_source or bool(description.get("conceal_source"))
        if description.get("rules"):
            rules_supplied = True
            rules_plain = plain(description["rules"])
            parts = [rules_plain]
            override_markup = str(description.get("markup") or "")
            override_parts = {rules_plain}
        if description.get("text"):
            text_plain = plain(description["text"])
            override_text = text_plain
            parts.insert(0, text_plain)
            if rules_supplied:
                # A plug-in that supplies a labelled card owns the whole card, so
                # the sentences that card is built from are not repeated in the body.
                override_parts.add(text_plain)
        if description.get("duration"):
            duration_override = plain(description["duration"])
        if "paying_pool" in description:
            pool = description["paying_pool"]
        handling = description.get("handling") or handling
        source_ability = description.get("source_ability") or source_ability
        source_name = description.get("applied_by") or source_name
        display_name = plain(description.get("display_name")) or display_name
    # The paying resource is resolved once and by the same source-aware lookup for
    # every channel, so a stored "Spend 1 CP" reading is explained wherever it is
    # displayed -- not only in ``rule_text`` (review finding 3).
    _resolved: list[str | None] = [None]

    def expanded(text: str) -> str:
        if not re.search(r"\bCP\b", str(text or "")):
            return text
        if _resolved[0] is None:
            _resolved[0] = pool if pool is not None else paying_pool(engine, holder, row, record)
        return expand_cp(text, _resolved[0])

    rule_text = _sentences(parts)
    if suppressed:
        rule_text = "This effect is temporarily suppressed and provides no benefit."
        handling = "The table restores it when the suppression expires."
        # The pill is renamed before the card is built, so the card's own title says
        # what it is rather than showing the benefit under its original name.
        display_name = f"Suppressed: {display_name or label}" if (display_name or label) else "Suppressed effect"
    rule_text = expanded(rule_text)
    if not handling:
        if native:
            handling = "The table applies the listed mechanical modifiers."
        elif typed.get("riders") and not typed.get("effects"):
            handling = "GM line: the table records this status; the GM applies its printed rule."
        elif mark:
            # Plain words, not engine wording (owner 2026-10-03: the hover must
            # read for a player who knows only basic D&D).
            handling = MARK_HANDLING
        elif typed.get("effects"):
            handling = "The table runs the compiled effects; any GM lines in the source remain GM rulings."
        elif info.get("reading"):
            handling = "The table records this status. " + ("GM portions are identified in the rule text." if "GM" in info["reading"] else "Its rule text describes when it is used or removed.")
        elif kind == "zone":
            handling = "The table applies the represented terrain and trigger rules; printed GM portions remain GM rulings."
    until = duration_override or duration_text(str(row.get("expires_on") or ""), data, typed, source_name,
                                                actors.get(getattr(holder, "entity_id", ""), "the affected creature"), actors, engine)
    # Which printed card the layout shows, and which of ``parts`` that card already
    # covers so no sentence is shown twice. A plug-in's own card wins; a suppressed
    # row shows none at all, because a suppressed benefit must not look active.
    card_markup, drop = "", set()
    if not suppressed:
        if override_markup and hover_text.split_fields(override_markup)[1]:
            card_markup, drop = override_markup, set(override_parts)
        elif rules_supplied:
            # A plug-in replaced the rules but offered no labelled form: the record
            # it replaced is still superseded, so it is not shown as a second
            # opinion. The plug-in's own sentence leads the card -- a row's own
            # display name is frequently an internal condition id
            # ("Mountain-Rending: deny_reactions") and must never be a title a
            # player reads -- and the replacement's rules stay in the body.
            card_markup, drop = override_text, ({override_text} if override_text else set())
        elif hover_text.split_fields(selected_markup)[1]:
            card_markup, drop = selected_markup, {selected.strip()}
    # Expanded before splitting, so the labelled fields and the summary derived from
    # them name the paying resource too, not just the body.
    card_markup = expanded(card_markup)
    _lead, fields = hover_text.split_fields(card_markup)
    # ``parts`` is the authoritative sentence list: the engine's native mechanics,
    # the stored reading, a mark's own reading, and anything a plug-in supplied
    # through the status_description hook. Once a card is split into labelled
    # fields its flattened copy (inside parts) would repeat every line, so it is
    # dropped then and only then, and no rule text is lost.
    engine_parts = [part for part in parts if part and part.strip() and part.strip() not in drop]
    body = _sentences([expanded(part) for part in engine_parts])
    if not body and not fields and not suppressed:
        # Nothing supports a description at all: the coverage checks distinguish
        # this unresolved state from a successful one.
        body = "Rule description unavailable for this saved status."
    extra = [part for part in ([body] if body else []) \
        + ([readers_line] if readers_line else []) + ([expanded(handling)] if handling else [])]
    if suppressed:
        # The suppression note replaces the whole card, printed fields included.
        extra = [rule_text, handling] if handling else [rule_text]
    elif mark and handling == MARK_HANDLING:
        # A mark's summary already says it does nothing on its own; repeating the
        # same thought in the handling line is the "one wall of text" complaint.
        extra = [body] if body else []
    hover = hover_text.layout(
        subject=display_name or label, kind="mark" if mark else kind, markup=card_markup,
        summary=hover_text.summary_for(
            display_name or label, fields, kind="mark" if mark else kind,
            mark_note=("A mark " + (f"{source_name} placed" if source_name != "Map" else "the map placed")
                       + ". It does nothing on its own.")),
        extra=extra, applied_by=source_name, source_ability=source_ability, duration=until)
    detail = hover["text"]
    result = {"rule_text": rule_text, "applied_by": source_name, "source_ability": source_ability,
              "duration": until, "handling": handling, "detail": detail,
              "hover": {key: value for key, value in hover.items() if key != "text"}}
    if display_name:
        result["display_name"] = display_name
    if conceal_source:
        # A private ledger may explain its purpose without publishing the raw
        # provenance identifiers that let clients reconstruct its secret source.
        result["source_actor_id"] = ""
        result["source_definition_id"] = ""
    # One CP wording on every surface: the pool-specific expansion above already
    # ran, so this only catches a bare "CP" in text it could not resolve.
    return {key: explain_cp(value) if isinstance(value, str) else value for key, value in result.items()}


def explain_presentation(presentation: dict[str, Any], engine: Any, actors: dict[str, str],
                         definitions: dict[str, str], mark_readings: dict[str, str]) -> dict[str, Any]:
    """Enrich copies of projected rows, matching repeated instances in order."""
    from .ext.life_state import is_deceased

    table = all_conditions()
    for actor_row in presentation.get("actors") or []:
        actor = engine.state.actors.get(actor_row.get("entity_id"))
        if actor is None:
            continue
        if is_deceased(actor):
            actor_row["life_status_text"] = "Dead"
        elif actor.life_state == "DYING":
            saves = actor.turn_flags.get("life_round_record") or {}
            ok, bad = int(saves.get("ok") or 0), int(saves.get("bad") or 0)
            actor_row["life_status_text"] = (f"Dying — {ok} {'success' if ok == 1 else 'successes'}, "
                                            f"{bad} {'failure' if bad == 1 else 'failures'}")
        elif actor.life_state:
            actor_row["life_status_text"] = {"STABLE": "Stable", "CONSCIOUS": "Conscious at 0 HP"}.get(actor.life_state, "")
        elif not actor.active:
            actor_row["life_status_text"] = "Defeated — alive"
        stored: dict[tuple[Any, ...], list[Any]] = {}
        for _, condition in sorted(actor.conditions.items()):
            key = (condition.condition_id, condition.source_definition_id, condition.source_actor_id, condition.expires_on)
            stored.setdefault(key, []).append(condition)
        for row in actor_row.get("conditions") or []:
            key = tuple(row.get(name) for name in ("condition_id", "source_definition_id", "source_actor_id", "expires_on"))
            matches = stored.get(key) or []
            condition = matches.pop(0) if matches else None
            row.update(describe(engine, actor, row, dict(getattr(condition, "data", None) or {}), actors, definitions,
                                condition_rules=table, mark_readings=mark_readings))
    # What Cultivation Level each character reached, read once for the area cards below (see area_wording). Absent from
    # a view that does not carry it, in which case the abbreviation is expanded in words instead of resolved.
    levels = {str(row.get("entity_id")): (row.get("character_summary") or {}).get("cultivation_level")
              for row in presentation.get("actors") or []}
    for zone in presentation.get("zones") or []:
        from .zones import terrain_rules

        profile = zone.get("trigger_profile") or {}
        data = dict(profile)
        data["owner_id"] = zone.get("owner_id")
        # The area's own Cultivation Level, so a printed clause that scales by it can show the real number (see area_wording).
        owner_level = levels.get(str(zone.get("owner_id")))
        parts = [plain(profile.get("reading") or profile.get("description"))]
        for terrain in profile.get("terrain") or []:
            parts.append(plain((terrain_rules().get("terrains") or {}).get(terrain, {}).get("evidence")))
        parts.extend(plain(inside.get("reading")) for inside in profile.get("inside") or [])
        # The chosen talents' printed inside-clauses that no effect carries (Pure Darkness's "Darkvision is reduced to
        # 5 feet"): the zone card is the one place a player standing in it is told what the area itself does. Read
        # through area_wording so a clause the print scales by Cultivation Level reaches the card in plain words.
        parts.extend(area_wording(clause, owner_level) for clause in profile.get("inside_text") or [])
        wall = profile.get("wall") or {}
        if wall.get("blocks_movement"):
            parts.append("Blocks movement.")
        if wall.get("blocks_sight"):
            parts.append("Blocks sight.")
        if wall.get("cover"):
            cover = {"three_quarters": "three-quarters", "half": "half", "total": "total"}.get(
                str(wall["cover"]), plain(wall["cover"]).replace("_", " "))
            parts.append(f"Grants {cover} cover.")
        if wall.get("move_cost"):
            parts.append(f"Movement costs {wall['move_cost']} times normal.")
        difficult = profile.get("difficult")
        if difficult:
            parts.append("Difficult terrain: movement costs twice normal" + (" for its creator's enemies." if difficult == "hostile" else "."))
        from .targeting import policy as targeting_policy

        # Projection only: carry this fight's policy for clients missing sight_text.
        zone["sight_rules"] = {key: targeting_policy(engine).get(key, 0) for key in
                               ("concealment_miss_percent", "total_concealment_miss_percent")}
        zone["sight_text"] = zone_sight_text(profile, zone["sight_rules"])
        if zone["sight_text"]:
            parts.append(zone["sight_text"])
        data["reading"] = " ".join(part for part in parts if part)
        data["concentration"] = bool(zone.get("concentration_link"))
        if zone.get("duration_rounds"):
            data["duration"] = {"kind": "rounds", "amount": zone["duration_rounds"]}
            data["until_round"] = int(zone.get("created_round") or 0) + int(zone["duration_rounds"])
        zone["display_name"] = profile.get("name") or (profile.get("visual") or {}).get("name") or "Area"
        zone.update(describe(engine, engine.state.actors.get(zone.get("owner_id")), zone, data, actors, definitions, kind="zone"))
        from .zone_hover import forged_area_hover

        zone.update(forged_area_hover(engine, zone))
    return presentation


def explain_marks_compat(presentation: dict[str, Any], engine: Any, actors: dict[str, str],
                         definitions: dict[str, str], mark_readings: dict[str, str]) -> dict[str, Any]:
    """Preserve the old mark-summary entry point using the same rule builder.

    Existing integrations/tests use its placer's-next-turn lead sentence. Only
    formatting differs; source text and reader discovery have one implementation.
    """
    if engine is None:
        return presentation
    ends = {"END_OF_MARKER_NEXT_TURN": "until the end of its placer's next turn",
            "START_OF_MARKER_NEXT_TURN": "until the start of its placer's next turn",
            "START_OF_SOURCE_NEXT_TURN": "until the start of its placer's next turn",
            "UNTIL_REMOVED": "until it is spent or removed"}
    for actor in presentation.get("actors") or []:
        for row in actor.get("conditions") or []:
            cid = str(row.get("condition_id") or "")
            if not cid.startswith("condition:typed.mark.") or row.get("detail"):
                continue
            kind, _, owner = cid.removeprefix("condition:typed.mark.").partition(".")
            name, placer = kind.replace("_", " ").title(), actors.get(owner, "someone")
            source = definitions.get(str(row.get("source_definition_id") or ""), "")
            text = describe(engine, None, row, {}, actors, definitions, mark_readings=mark_readings)
            row["detail"] = (f"{name} mark from {placer}" + (f" ({source})" if source else "")
                             + f", {ends.get(str(row.get('expires_on')), 'while it lasts')}. " + text["rule_text"])
    return presentation
