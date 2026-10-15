"""Glass's tempered surfaces, Faultline Marks and Refraction Responses (rider lane 9, 2026-09-29; owner: "i want everything we can
automated").  Sphere Compendium, Glass (owner's text: authority/typed_mechanics/rules_text.json).  The Responses were "left GM-run for now"
(elements.json's note on GLASS_BASE_REFRACTION_RESPONSES); this module runs the four a fight can see.  Rows: feature block "lane9_glass"
(combat/rules/feature_blocks.d/riders_lane9.json); typed effects "glass_temper" and "glass_lens".

  Temper Glass Surface  a Bonus Action (it had no typed effect, so it was never offered): your body, worn armor or held weapon/shield becomes
                        a tempered Glass Surface for 1 minute ("condition:typed.glass_tempered").  Glass Domain and Incarnation of the
                        Transparent Fault make your body one while they last.  The table places a fighter's surfaces on the fighter itself
                        (and on its Glass Road and Contact Pane areas).
  Faultline Marks       besides the typed Faultline Strike and Glass Shard marks: a creature that attacks you while you are tempered gains
                        one; inside your Glass Domain, the first time each round a hostile creature inside damages your ally, crosses
                        one of your Glass Surfaces inside it, or attacks through one inside it (the blow's own path decides); with
                        Incarnation of the Transparent Fault, a hostile creature within 30 feet that hits you or an ally.  A mark lasts until the end of your next turn (typed_conditions mark_durations); past your PB the
                        oldest ends (elements.json mark_caps).
  Glass Domain          the Court's 30-foot Emanation also ties terrain to itself: "Shattered Glass Terrain you create inside the
                        Domain lasts until the Domain ends" -- a patch created there stops counting down, remembers the Domain's
                        zone id (a string, so a committed fight replays it) and is removed with the Domain. That printed lifetime
                        outranks the pane's own "until the end of your next turn" (glass_pane.owner_turn_terrain leaves a linked
                        patch alone). Three of its four
                        "the first time each round ... you may place a Faultline Mark" triggers are worked out from the fight's
                        own geometry (damages an ally inside, crosses a Glass Surface inside, attacks through one inside) and are
                        asked, so an Ask me owner decides even on someone else's turn.
  Living Pane Sutra     shattering the shell at 1 HP fills each space adjacent to you with Shattered Glass Terrain, the same patch
                        and two rounds Clean Break's printed square of it uses (the shell's own line prints no other length).
  Refraction Responses  one per triggering event, paid with your Reaction -- or, once per round, free inside your Glass Domain or during
    Turn the Angle      Incarnation of the Transparent Fault, and free again through Refraction of the Obvious Blow:
    Visible Crack       a marked creature hits you or an ally within 5 feet of your tempered surface: the damage drops by 1d8 (2d8 at CL 5,
    Bitter Edge         3d8 at CL 11, 4d8 at CL 17) + PB; at 0 the attacker makes no Opportunity Attacks until the start of its next turn.
    Shatter Warning     a marked creature Hides: it is not hidden (its space is known) until the start of your next turn.
                        a marked creature willingly moves 5 feet or more: PB Slashing damage and 10 feet less movement this turn.
                        a marked creature attacks you while you are tempered: -2 on the roll; on a miss, PB Piercing damage.
Talents: Lens of the Honest Crack (the target's first attack roll or technique before the start of your next turn marks it), Lens of
  Stored Pressure (after Turn the Angle, your next Faultline Strike or Glass Shard hit before the end of your next turn adds PB, 1d8 + PB at
  CL 11), Incarnation of the Transparent Fault (spending a mark: PB Temporary HP to an ally or PB Slashing to a foe within 30 feet), Living
  Pane Sutra (once a fight, 1 HP instead of 0 while your body is tempered), Careful Feet on Broken Light (your own Shattered Glass Terrain is
  not difficult for you), Walking Pane Body (the Faultline Mark a melee hit earns, and the Temporary HP spending it pays before the end of
  your next turn), Ten-Angle Refraction (one ally's step out of the marked creature's reach, paid for ending behind Cover,
holding a Glass Surface of the ally's own, or beside your broken glass -- standing on one of your panes is not holding it, and
that case is left to the GM), Faultline Transfer (a second mark moves), Refraction
  of the Obvious Blow (a marked creature that misses you answers to one Response without a Reaction).

Judgment calls: invisibility, Cover and a concealed origin (Visible Crack's other triggers) are the GM's; Refracted Step and Break the Line
(objects) are the GM's; Incarnation's choice goes to the ally with the least HP when one is Bloodied, else to the nearest foe. An ally
treating their own worn armor, held weapon or held shield as a Glass Surface (the Glass Domain's "may") is a standing choice that no
record of a fight holds, so the Domain's Glass Surfaces are the caster's own body and the glass they made. "One creature that saw it
break" (Clean Break) is read as line of sight to the broken thing's square, at any distance. Shard Needle is left to the GM: its printed
clause needs "If you are a Body Refiner", and a compiled fighter records its Spheres, Talents and Techniques, not its Path.

Shared for other Glass plug-ins: ``give_mark`` (place the printed Faultline Mark on one creature) and the mark-duration table
``mark_durations`` / ``mark_cap``; glass_pane (Clean Break's printed "place a Faultline Mark on one creature within 5 feet of it")
uses both, so a mark means the same thing and lasts the same time whichever Glass talent placed it.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_glass"
T = "TAL_GLASS_"
RESPONSES_ID = "GLASS_BASE_REFRACTION_RESPONSES"
MARK = "Faultline Mark"
C = "condition:typed."
TEMPERED, INCARNATION, LENS, STORED, SPARED = C + "glass_tempered", C + "glass_incarnation", C + "glass_lens", C + "glass_stored", C + "glass_spared"
DOMAIN_ID, INCARNATION_ID = T + "GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS", T + "INCARNATION_OF_THE_TRANSPARENT_FAULT"
SURFACE_SOURCES = {T + "GLASS_ROAD", T + "CONTACT_PANE", T + "THOUSAND_PANE_PALACE", T + "RAISED_PANE_SCRIPTURE",
                   T + "GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"}  # the Domain: "each ally inside may treat their worn armor ... as a Glass Surface"
STRIKES = {"GLASS_BASE_FAULTLINE_STRIKE", "GLASS_BASE_GLASS_SHARD"}


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             "key_mod": int(numbers.get("key_mod") or 0), "keeps_compiling": bool(spec.get("keeps_compiling"))}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _row(engine: Any, caster: Any) -> dict[str, Any]:
    found = rows(engine, caster, "refraction")
    return found[0] if found else {}


def _casters(engine: Any) -> list[Any]:
    return [a for a in engine.state.actors.values() if a.active and rows(engine, a, "refraction")]


def _held(actor: Any, condition_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _feature(engine: Any, source: Any) -> str:
    action = engine.action_catalog.get(str(source or ""))
    return str((((action.parameters or {}).get("typed") or {}).get("source") or "")) if action is not None else ""


def _mark_id(owner_id: str) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner_id)


def marked(actor: Any, owner_id: str) -> bool:
    return any(c.condition_id == _mark_id(owner_id) for c in actor.conditions.values())


def spend_mark(engine: Any, caster: Any, subject: Any, source: str) -> None:
    """Spend ``caster``'s Faultline Mark on ``subject`` and announce the spending to the Glass talents.

    Shared by the other Glass plug-ins that answer to a mark (glass_faults spends one for Break the Proud Weapon, Spell-Line
    Crack and Flaw Within the Golden Technique).  A mark is one record with one meaning wherever it was placed, so the
    removal and the ``mark_spent`` announcement live here and no other module keeps a second mark ledger.
    """
    from .. import ext

    engine._remove_condition(subject, _mark_id(caster.entity_id), source)
    ext.run("mark_spent", _ctx(engine, caster, subject, source, MARK), MARK, subject)
    engine._append_event("REACTION_WINDOW_OPENED", source, actor_id=caster.entity_id,
                         target_ids=(subject.entity_id,), payload={"checkpoint": "GLASS_MARK_SPENT", "mark": MARK})


def surface_cells(engine: Any, caster: Any) -> set[tuple[int, int]]:
    """Every square carrying one of ``caster``'s own Glass Surfaces (see ``_surface_cells``).

    Public for the other Glass plug-ins: glass_faults reads it for Spell-Line Crack's "while you can see it through a Glass
    Surface" trigger.
    """
    return _surface_cells(engine, caster)


def ai_owns(engine: Any, actor: Any) -> bool:
    """Whether this fighter's own controller answers for it (see ``_ai_owns``).

    Public for the other Glass plug-ins: glass_faults reads it so a printed "you may" is auto-answered by an AI owner and
    still asked of a player.
    """
    return _ai_owns(engine, actor)


def _ctx(engine: Any, actor: Any, other: Any, feature: str, name: str) -> Any:
    from .. import typed_reactions

    return typed_reactions._generic_context(engine, actor, other, {"feature_id": feature, "name": name, "effects": [], "numbers": {}})


def give_mark(engine: Any, caster: Any, subject: Any, source: str, *, any_side: bool = False) -> None:
    """Place the printed Faultline Mark on one creature.

    Faultline Marks are a hostile-creature rule, so a recipient on the caster's own side is refused unless the printed line
    that placed it names no side (``any_side``: Clean Break's "place a Faultline Mark on one creature within 5 feet of it",
    Faultline Transfer's "another creature"), and the table has already picked that creature."""
    from ..typed_executor import block_mark

    if subject is None or not subject.active or (subject.team_id == caster.team_id and not any_side) \
            or marked(subject, caster.entity_id):
        return
    block_mark(_ctx(engine, caster, subject, source, MARK), {"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_removed"}})


def _roll(engine: Any, actor: Any, count: int, sides: int, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def _zones_of(engine: Any, caster: Any, features: set[str]) -> list[Any]:
    from .. import zones

    return [z for z in zones.typed_zones(engine) if z.active and z.owner_id == caster.entity_id and _feature(engine, z.source_definition_id) in features]


def tempered(engine: Any, caster: Any) -> bool:
    return bool(_held(caster, TEMPERED) or _held(caster, INCARNATION) or _zones_of(engine, caster, {DOMAIN_ID}))


def _surface_cells(engine: Any, caster: Any) -> set[tuple[int, int]]:
    """Every square that carries one of ``caster``'s Glass Surfaces: their own tempered body, each pane they raised, and the
    Glass Road / Contact Pane / Thousand Pane Palace areas they made.

    This is the printed meaning of "a Glass Surface you control" (Ten-Angle Refraction) and of "crosses a Glass Surface"
    (Glass Domain). The Glass Domain's "each ally inside **may** treat their worn armor, held weapon, or held shield as a
    Glass Surface" is a standing choice by that ally, which no record of this fight holds, so those squares are not counted
    here: the Domain's own area is where the caster stands, not a sheet of glass."""
    from . import glass_pane

    cells: set[tuple[int, int]] = set()
    if tempered(engine, caster):
        cells |= {tuple(cell) for cell in engine._actor_cells(caster)}
    for zone in _zones_of(engine, caster, SURFACE_SOURCES - {DOMAIN_ID}):
        cells |= {(c.x, c.y) for c in zone.affected_cells}
    cells |= glass_pane.pane_cells(engine, caster)  # Raised Pane Scripture's panes are Glass Surfaces too
    return cells


def _square(cell: tuple[int, int]) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=cell[0], y=cell[1])


def _beside(after: tuple[int, int], cells: set[tuple[int, int]]) -> bool:
    return any(max(abs(after[0] - x), abs(after[1] - y)) <= 1 for x, y in cells)


MANUAL_MODES = {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}   # the modes the table waits on a player for (tabletop_service)


def _ai_owns(engine: Any, actor: Any) -> bool:
    """Whether this fighter's own controller answers for it, so a printed "you may" needs no player.

    The modes that wait for a player are the ones the table service knows (combat/tabletop_service.py MANUAL_MODES); a
    fighter with no declared mode at all -- a stock fight, an engine-level harness -- has always been driven by its
    controller and keeps that behaviour."""
    modes = getattr(engine, "typed_control_modes", {}) or {}
    return str(modes.get(actor.entity_id, "LOCAL_AUTO")) not in MANUAL_MODES


def _near_surface(engine: Any, caster: Any, creature: Any, feet: int = 5) -> bool:
    reach = feet // engine.grid.square_size_ft
    cells = _surface_cells(engine, caster)
    return any(max(abs(x - cx), abs(y - cy)) <= reach for x, y in engine._actor_cells(creature) for cx, cy in cells)


def _free_response(engine: Any, caster: Any) -> bool:
    return (bool(_held(caster, INCARNATION)) or bool(_zones_of(engine, caster, {DOMAIN_ID}))) and \
        caster.turn_flags.get("glass_free_response") != engine.state.round_number


def _refracted_step_label(engine: Any, caster: Any) -> str:
    """Refracted Step's printed reach on the user's Cultivation Level bands (5 feet; 10 at CL 5, 15 at CL 11, 20 at CL 17)."""
    cl = int(_row(engine, caster).get("cl", 1))
    return f"Refracted Step: move {5 if cl < 5 else 10 if cl < 11 else 15 if cl < 17 else 20} feet without provoking its Opportunity Attacks"


def _refracted_step_feet(engine: Any, caster: Any) -> int:
    cl = int(_row(engine, caster).get("cl", 1))
    return 5 if cl < 5 else 10 if cl < 11 else 15 if cl < 17 else 20


def _step_offered(engine: Any, caster: Any, subject: Any) -> bool:
    """Refracted Step's trigger: "You spend a Faultline Mark on a creature within 5 feet of you or your tempered Glass Surface.\""""
    return (engine._distance_actor_to_actor(caster, subject) <= engine.grid.square_size_ft + 1
            or _near_surface(engine, caster, subject))


@contextmanager
def _offer(engine: Any, caster: Any, subject: Any, response: str, label: str, *, want: bool = True,
           also: list[tuple[str, str]] | None = None, free: bool = False) -> Iterator[str | None]:
    """Spend ``subject``'s Faultline Mark on one Response: the Reaction, or a Response the printed text makes free.

    ``response``/``label`` are the Response this trigger offers by default; ``also`` names any other Response the same
    marked creature offers right now (Refracted Step, which any mark spent within 5 feet may be spent on instead), and
    the table chooses. Yields the Response chosen under its own activation, or None when the mark stays.
    """
    from .. import typed_reactions

    if not marked(subject, caster.entity_id):
        yield None
        return
    free = free or _free_response(engine, caster)
    if not free and not typed_reactions._can_react(engine, caster):
        yield None
        return
    options = [(response, label), *(also or [])]
    names = [name for name, _text in options]
    texts = dict(options)
    # an Ask me owner is asked and may decline; an AI owner answers for itself, so the printed Response is the default
    automatic = _ai_owns(engine, caster)
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "REFRACTION", caster.entity_id, subject.entity_id, response), caster,
                 CHOICE + "refraction_response", names, labels=texts, allow_decline=True, target_id=subject.entity_id,
                 default="first" if (want and automatic) else "decline", automatic=automatic,
                 prompt=f"{subject.display_name} (Faultline Mark): spend it on {texts[response]}?")
    if not picked or picked[0] not in names:
        yield None
        return
    with activation(engine, caster, RESPONSES_ID):
        chosen = picked[0]
        if free:
            caster.turn_flags["glass_free_response"] = engine.state.round_number
        else:
            caster.reaction_available = False
        engine._remove_condition(subject, _mark_id(caster.entity_id), RESPONSES_ID)
        # the mark is spent: tell the talents that answer to a spending mark (Faultline Transfer, Ten-Angle Refraction,
        # Walking Pane Body), the way typed_executor.block_spend_mark does for a typed spend
        from .. import ext

        ext.run("mark_spent", _ctx(engine, caster, subject, RESPONSES_ID, MARK), MARK, subject)
        engine._append_event("REACTION_WINDOW_OPENED", RESPONSES_ID, actor_id=caster.entity_id, target_ids=(subject.entity_id,),
                             payload={"checkpoint": "REFRACTION", "response": chosen, "free": free})
        note(engine, RESPONSES_ID, caster, f"Refraction Response: {texts[chosen]} ({subject.display_name}'s Faultline Mark).")
        _spent(engine, caster)
        yield chosen


def _also_step(engine: Any, caster: Any, subject: Any) -> list[tuple[str, str]] | None:
    """Refracted Step as a second answer wherever a marked creature may be spent on it."""
    return [("step", _refracted_step_label(engine, caster))] if _step_offered(engine, caster, subject) else None


def _do_step(engine: Any, caster: Any, subject: Any) -> None:
    from .rider_choices import step

    step(engine, caster, "glass_refracted_step", "Refracted Step", subject, _refracted_step_feet(engine, caster), RESPONSES_ID,
         trigger=f"spending {subject.display_name}'s Faultline Mark", ignored_oa=[subject.entity_id])


def _spent(engine: Any, caster: Any) -> None:
    """Incarnation of the Transparent Fault: "when you spend a Faultline Mark, choose one creature within 30 feet. That creature either gains
    Temporary HP equal to your Proficiency Bonus or takes Slashing damage equal to your Proficiency Bonus.\""""
    if not _held(caster, INCARNATION):
        return
    pb = int(_row(engine, caster).get("pb", 2))
    near = [a for a in engine.state.actors.values() if a.active and engine._distance_actor_to_actor(a, caster) <= 30]
    hurt = sorted((a for a in near if a.team_id == caster.team_id and a.current_hp * 2 <= a.maximum_hp), key=lambda a: (a.current_hp, a.entity_id))
    if hurt:
        engine._grant_temp_hp(hurt[0], pb, INCARNATION_ID, caster.entity_id)
        return
    foes = sorted((a for a in near if a.team_id != caster.team_id), key=lambda a: (engine._distance_actor_to_actor(a, caster), a.entity_id))
    if foes:
        engine._commit_damage(foes[0], pb, "SLASHING", INCARNATION_ID, caster.entity_id, None, reaction_depth=1)


# ------------------------------------------------------------------------------------------------ Turn the Angle
@hook("damage_pending")
def turn_the_angle(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    attacker = engine.state.actors.get(str(source_actor_id or ""))
    if attacker is None or pending <= 0:
        return None
    for caster in _casters(engine):
        if target.team_id != caster.team_id or not marked(attacker, caster.entity_id):
            continue
        if target is not caster and not _near_surface(engine, caster, target):
            continue
        if target is caster and not tempered(engine, caster) and not _surface_cells(engine, caster):
            continue
        with _offer(engine, caster, attacker, "turn", "Turn the Angle: the damage drops", also=_also_step(engine, caster, attacker)) as answer:
            if answer is None:
                continue
            if answer == "step":
                _do_step(engine, caster, attacker)
                return None
            row = _row(engine, caster)
            cl, pb = int(row.get("cl", 1)), int(row.get("pb", 2))
            cut = _roll(engine, caster, 1 if cl < 5 else 2 if cl < 11 else 3 if cl < 17 else 4, 8, "TURN_THE_ANGLE") + pb
            left = max(0, pending - cut)
            from .attack_reduction import remember
            left = remember(engine, target, pending, left, [(cut, ())])
            if left == 0:
                engine._apply_condition(attacker, C + "no_opportunity_attacks", RESPONSES_ID, caster.entity_id, expires_on=_token(attacker, "start"),
                                        data={"label": "Turn the Angle: no Opportunity Attacks"})
            stored = rows(engine, caster, "stored_pressure")
            if stored:
                engine._apply_condition(caster, STORED, T + "LENS_OF_STORED_PRESSURE", caster.entity_id, expires_on=_token(caster, "end"),
                                        data={"label": "Lens of Stored Pressure: the next Faultline Strike or Glass Shard hit adds damage"})
            return left
    return None


def _token(actor: Any, edge: str, ahead: int = 1) -> str:
    from .effect_durations import token

    return token(edge, actor.entity_id, int(actor.turns_started) + ahead)


# ------------------------------------------------------------------------------------------------ attacks against a tempered caster
@hook("attack_bonus")
def shatter_warning(ctx: Any, actor: Any) -> int | None:
    engine = ctx.engine
    target = ctx.target
    total = 0
    for caster in _casters(engine):
        if target is not caster or not tempered(engine, caster):
            continue
        if marked(actor, caster.entity_id):
            with _offer(engine, caster, actor, "warning", "Shatter Warning: -2 on the attack roll", also=_also_step(engine, caster, actor)) as answer:
                if answer == "step":
                    _do_step(engine, caster, actor)
                    continue
                if answer == "warning":
                    preserve_pending(engine, "_glass_warned")
                    engine.__dict__.setdefault("_glass_warned", set()).add((actor.entity_id, caster.entity_id))
                    retain(engine, ("_glass_warned", actor.entity_id, caster.entity_id), capture(engine))
                    total -= 2
    for lens in _held(actor, LENS):
        owner = engine.state.actors.get(lens.source_actor_id)
        engine._remove_condition(actor, LENS, T + "LENS_OF_THE_HONEST_CRACK")
        if owner is not None:
            give_mark(engine, owner, actor, T + "LENS_OF_THE_HONEST_CRACK")  # "the first time the target makes an attack roll"
    return total or None


@hook("after_miss")
def glass_after_miss(ctx: Any, target: Any) -> None:
    engine, attacker = ctx.engine, ctx.actor
    preserve_pending(engine, "_glass_warned")
    warned = engine.__dict__.get("_glass_warned") or set()
    for caster in _casters(engine):
        if (attacker.entity_id, caster.entity_id) in warned:
            with causal_scope(engine, take(engine, ("_glass_warned", attacker.entity_id, caster.entity_id))):
                warned.discard((attacker.entity_id, caster.entity_id))
                engine._commit_damage(attacker, int(_row(engine, caster).get("pb", 2)), "PIERCING", RESPONSES_ID, caster.entity_id, None, reaction_depth=1)
    _attacked(engine, attacker, target, hit=False)
    _domain_attacked(engine, attacker, target)  # Glass Domain: an attack on an ally standing inside it
    if target is not None and target.active:
        _obvious_blow(engine, attacker, target)


def _obvious_blow(engine: Any, attacker: Any, victim: Any) -> None:
    """Refraction of the Obvious Blow: "When a marked creature misses you with an attack roll, use one Refraction Response that
    targets that creature without spending your Reaction. Use Refraction of the Obvious Blow once per round."

    The Response is one that can reach a creature that just missed its owner, which at that moment is Shatter Warning's
    "if the attack misses, the marked creature takes Piercing damage equal to your Proficiency Bonus", or Refracted Step
    (the mark spent on a step). Both are offered and the answer is applied; the round is spent only when one is used."""
    for caster in _casters(engine):
        if not rows(engine, caster, "obvious_blow") or victim is not caster:
            continue
        if not marked(attacker, caster.entity_id) or caster.turn_flags.get("glass_obvious_blow") == engine.state.round_number:
            continue
        with _offer(engine, caster, attacker, "obvious",
                        "Shatter Warning: it takes Piercing damage equal to your Proficiency Bonus, and this costs no Reaction",
                        also=_also_step(engine, caster, attacker), free=True) as answer:
            if answer is None:
                continue
            caster.turn_flags["glass_obvious_blow"] = engine.state.round_number
            if answer == "step":
                _do_step(engine, caster, attacker)
            elif answer == "obvious":
                engine._commit_damage(attacker, int(_row(engine, caster).get("pb", 2)), "PIERCING", RESPONSES_ID,
                                      caster.entity_id, None, reaction_depth=1)


@hook("after_hit")
def glass_after_hit(ctx: Any, target: Any, kind: str) -> None:
    engine, attacker = ctx.engine, ctx.actor
    preserve_pending(engine, "_glass_warned")
    (engine.__dict__.get("_glass_warned") or set()).discard((attacker.entity_id, target.entity_id))
    take(engine, ("_glass_warned", attacker.entity_id, target.entity_id))
    _attacked(engine, attacker, target, hit=True)
    _domain_attacked(engine, attacker, target)  # Glass Domain: an attack on an ally standing inside it
    _pane_body_mark(engine, ctx, attacker, target, kind)
    if str(ctx.typed.get("source") or "") in STRIKES and target.active:
        for stored in _held(attacker, STORED):
            engine._remove_condition(attacker, STORED, T + "LENS_OF_STORED_PRESSURE")
            row = _row(engine, attacker)
            pb, cl = int(row.get("pb", 2)), int(row.get("cl", 1))
            extra = pb + (_roll(engine, attacker, 1, 8, "STORED_PRESSURE") if cl >= 11 else 0)
            engine._commit_damage(target, extra, "PIERCING", T + "LENS_OF_STORED_PRESSURE", attacker.entity_id, None, reaction_depth=1)
            break


PANE_MARK = C + "glass_pane_mark"   # condition:typed.glass_pane_mark.<creature>: the Faultline Mark a melee hit earned, and its deadline


def _pane_body_mark(engine: Any, ctx: Any, attacker: Any, target: Any, kind: str) -> None:
    """Walking Pane Body: "once per round when a creature hits you with a melee attack, you may place a Faultline Mark on that
    creature without using your Reaction. If you spend that mark before the end of your next turn, gain Temporary HP equal to
    your Proficiency Bonus."

    The mark itself is Faultline Marks' own line for an attack on a tempered body; this remembers *which creature* this one was
    earned from and keeps it until the end of the owner's next turn, so only spending that mark pays the Temporary HP. The
    record is a condition (not a turn flag) so it is swept by the engine's own expiry names and survives a table commit."""
    from ..typed_executor import ranged_attack_now
    from .rider_choices import pick

    if kind not in ("weapon", "unarmed") or not rows(engine, target, "walking_pane") or not tempered(engine, target):
        return
    if ranged_attack_now(ctx):   # "a melee attack": a thrown or shot weapon does not earn it
        return
    if target.turn_flags.get("glass_pane_mark_round") == engine.state.round_number:
        return
    pb = int(_row(engine, target).get("pb", 2))
    if not pick(engine, target, "glass_pane_mark", "Walking Pane Body", ["mark"], subject=attacker, preferred=["mark"],
                labels={"mark": f"Mark {attacker.display_name} with a Faultline Mark: spending it before the end of your "
                                f"next turn gives you {pb} Temporary HP"},
                trigger=f"{attacker.display_name} hits your tempered body with a melee attack",
                optional=True, automatic=_ai_owns(engine, target)):
        return
    target.turn_flags["glass_pane_mark_round"] = engine.state.round_number
    give_mark(engine, target, attacker, T + "WALKING_PANE_BODY")   # idempotent: Faultline Marks already placed this one
    engine._apply_condition(target, f"{PANE_MARK}.{attacker.entity_id}", T + "WALKING_PANE_BODY", target.entity_id,
                            expires_on=_token(target, "end"),
                            data={"creature": attacker.entity_id,
                                  "label": f"Walking Pane Body: spending {attacker.display_name}'s Faultline Mark before the "
                                           f"end of your next turn gives you {pb} Temporary HP"})


@hook("status_description")
def pane_mark_status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, str] | None:
    """What the Walking Pane Body record on a fighter's sheet means.

    The status hook is handed the condition row as a dict (combat/status_text.py ``describe``), and the record's own id
    carries the creature whose hit earned the mark (``condition:typed.glass_pane_mark.<creature>``), so the id is read by
    prefix rather than compared whole. A dict lookup, not attribute access: the old ``getattr(row, "condition_id", "")``
    found nothing on a dict and this card never appeared. The stored label names the creature and the reward, and is the
    fallback when an older record carries no label at all."""
    condition_id = str((row or {}).get("condition_id") or "")
    if not condition_id.startswith(PANE_MARK + "."):
        return None
    return {"text": str((data or {}).get("label") or "") or "Spending this Faultline Mark gives this fighter Temporary HP.",
            "handling": "It ends at the end of its owner's next turn, and only spending that one mark pays the Temporary HP."}


@hook("mark_spent")
def mark_spent(ctx: Any, name: str, subject: Any) -> None:
    """What spending a Faultline Mark pays the Glass talents that answer to the spending itself."""
    engine, caster = ctx.engine, ctx.actor
    if str(name) != MARK or subject is None:
        return
    _faultline_transfer(engine, caster, subject)
    _ten_angle(engine, caster, subject)
    _pane_body_pay(engine, caster, subject)


def _pane_body_pay(engine: Any, caster: Any, subject: Any) -> None:
    """Walking Pane Body's Temporary HP for the mark its own melee hit earned, spent before the end of your next turn.

    The creature and the deadline are the record's own: only the mark that creature's hit earned pays, and once the engine's
    expiry has swept the record (the end of your next turn) nothing pays."""
    condition = f"{PANE_MARK}.{getattr(subject, 'entity_id', subject)}"
    if not any(row.condition_id == condition for row in caster.conditions.values()):
        return
    pb = int(_row(engine, caster).get("pb", 2))
    engine._remove_condition(caster, condition, T + "WALKING_PANE_BODY")
    engine._grant_temp_hp(caster, pb, T + "WALKING_PANE_BODY", caster.entity_id)
    note(engine, T + "WALKING_PANE_BODY", caster,
         f"Walking Pane Body: you spent the mark {subject.display_name}'s hit earned, so you gain {pb} Temporary HP.")


def _faultline_transfer(engine: Any, caster: Any, spent: Any) -> None:
    """Faultline Transfer: "When you spend a Faultline Mark, you may move one different Faultline Mark from a creature within 30 feet
    to another creature, object, or Glass Surface within 5 feet of the original target. Use Faultline Transfer once per round."

    Every legal pair is offered (which mark moves, and which creature it lands on), so a mark whose target has no one beside it
    never hides a mark that could have moved, and the once-a-round chance is spent only when a pair is chosen. The object and
    Glass Surface destinations are a GM line: this fight's record of a mark is a condition on a creature."""
    from .rider_choices import pick

    if not rows(engine, caster, "transfer") or caster.turn_flags.get("glass_transfer") == engine.state.round_number:
        return
    everyone = [actor for actor in engine.state.actors.values() if actor.active]
    sources = sorted((other for other in everyone
                      if other is not spent and marked(other, caster.entity_id)
                      and engine._distance_actor_to_actor(caster, other) <= 30),
                     key=lambda other: (engine._distance_actor_to_actor(caster, other), other.entity_id))
    options, labels = [], {}
    for source in sources:
        # the caster is not a destination (the mark would come home to the one who owns it), a creature that already wears
        # this mark is not one (moving a mark onto it would silently end the mark it has), and the creature whose mark was just
        # spent may take a different one.
        for other in sorted((actor for actor in everyone if actor is not source and actor is not caster
                             and engine._distance_actor_to_actor(actor, source) <= engine.grid.square_size_ft + 1
                             and not (actor is not spent and marked(actor, caster.entity_id))),
                            key=lambda actor: (engine.grid.distance_ft(actor.position, source.position), actor.entity_id)):
            options.append(f"{source.entity_id}>{other.entity_id}")
            labels[options[-1]] = f"Move the Faultline Mark on {source.display_name} to {other.display_name}"
    if not options:
        return
    chosen = pick(engine, caster, "glass_transfer", "Faultline Transfer", options, labels=labels, preferred=[options[0]],
                  subject=spent, trigger=f"you spend a Faultline Mark on {spent.display_name}", optional=True,
                  automatic=_ai_owns(engine, caster))
    if not chosen or str(chosen[0]) not in labels:
        return
    source_id, _, destination_id = str(chosen[0]).partition(">")
    source, destination = engine.state.actors.get(source_id), engine.state.actors.get(destination_id)
    if source is None or destination is None:
        return
    caster.turn_flags["glass_transfer"] = engine.state.round_number
    from .. import typed_executor

    # the printed text moves the mark to "another creature": no side is named, so this places it exactly where the
    # table picked (give_mark, above, is the Faultline Marks rule and only ever marks a hostile creature).
    engine._remove_condition(source, _mark_id(caster.entity_id), T + "FAULTLINE_TRANSFER")
    typed_executor.block_mark(_ctx(engine, caster, destination, T + "FAULTLINE_TRANSFER", MARK),
                              {"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_removed"}})
    note(engine, T + "FAULTLINE_TRANSFER", caster,
         f"Faultline Transfer: the Faultline Mark moves from {source.display_name} to {destination.display_name}.")


def _ten_angle(engine: Any, caster: Any, subject: Any) -> None:
    """Ten-Angle Refraction: "When you spend a Faultline Mark, choose one ally within 30 feet who can see a Glass Surface you
    control. That ally may move 5 feet without provoking Opportunity Attacks from the marked creature. If the ally ends this
    movement behind Cover, holding a Glass Surface, or adjacent to Shattered Glass Terrain you created, the ally gains Temporary HP
    equal to your Proficiency Bonus."

    Three separate questions, three separate answers, and never the union. The ally must be able to see one of the caster's Glass
    Surfaces (the caster having one is not enough). The reward is for ending behind Cover, ending holding a Glass Surface, or ending
    beside Shattered Glass Terrain the caster made.

    "Holding a Glass Surface" is read as the ally holding one: their own tempered body, worn armor, or held weapon or shield is a
    Glass Surface only once the table has made it one (the glass_tempered record, glass_temper/Incarnation, or a Glass Domain of
    their own). Standing on a pane, or sharing an unattended pane's square, is not holding it -- a fighter walking across Glass Road
    is not carrying glass -- so the ally's own square never pays. Which object an ally is physically holding, or that an ally has
    declared their armor a Glass Surface, is a standing choice no record of a fight holds, so that last case is left to the GM and
    said out loud below rather than guessed at."""
    from . import glass_pane
    from .rider_choices import pick, step

    if not rows(engine, caster, "ten_angle"):
        return
    surfaces = _surface_cells(engine, caster)
    if not surfaces:
        return
    allies = sorted((other for other in engine.state.actors.values()
                     if other.active and other is not caster and other.team_id == caster.team_id
                     and engine._distance_actor_to_actor(caster, other) <= 30
                     and any(engine._line_of_sight_actor_to_cell(other, _square(cell)) for cell in surfaces)),
                    key=lambda other: (engine._distance_actor_to_actor(caster, other), other.entity_id))
    if not allies:
        return
    options = [other.entity_id for other in allies]
    labels = {other.entity_id: f"{other.display_name} may move 5 feet without {subject.display_name}'s Opportunity Attack"
              for other in allies}
    chosen = pick(engine, caster, "glass_ten_angle", "Ten-Angle Refraction", options, labels=labels, preferred=[options[0]],
                  subject=subject, trigger=f"you spend its Faultline Mark on {subject.display_name}", optional=True,
                  automatic=_ai_owns(engine, caster))
    if not chosen:
        return
    ally = engine.state.actors[chosen[0]]
    before = (ally.position.x, ally.position.y)
    step(engine, ally, "glass_ten_angle_step", "Ten-Angle Refraction", subject, 5, T + "TEN_ANGLE_REFRACTION",
         trigger=f"{subject.display_name}'s Faultline Mark pays {ally.display_name}'s step", ignored_oa=[subject.entity_id])
    after = (ally.position.x, ally.position.y)
    if before == after:
        return
    reasons = []
    if after in engine.grid.cover:
        reasons.append("behind Cover")
    if tempered(engine, ally):
        reasons.append("holding a Glass Surface of their own")
    if _beside(after, glass_pane.shattered_cells(engine, caster)):
        reasons.append("beside Shattered Glass Terrain you made")
    if not reasons:
        if after in surfaces:
            # the printed "holding a Glass Surface" is not met on the record, and standing on one is not holding it: this is
            # the table's call, said in plain words instead of paid silently
            note(engine, T + "TEN_ANGLE_REFRACTION", caster,
                 f"Ten-Angle Refraction: {ally.display_name} ends on one of your Glass Surfaces. Standing on glass is not holding "
                 f"it, so this pays nothing on its own; if {ally.display_name} really is holding that glass, award the Temporary HP "
                 f"yourself.")
        return
    pb = int(_row(engine, caster).get("pb", 2))
    engine._grant_temp_hp(ally, pb, T + "TEN_ANGLE_REFRACTION", caster.entity_id)
    note(engine, T + "TEN_ANGLE_REFRACTION", caster,
         f"Ten-Angle Refraction: {ally.display_name} ends {' and '.join(reasons)}, and gains {pb} Temporary HP.")


def _attacked(engine: Any, attacker: Any, target: Any, *, hit: bool) -> None:
    for caster in _casters(engine):
        if attacker.team_id == caster.team_id:
            continue
        if target is caster and tempered(engine, caster):
            give_mark(engine, caster, attacker, "GLASS_BASE_FAULTLINE_MARKS")  # "a creature attacks you while your body ... is your tempered Glass Surface"
        elif hit and target.team_id == caster.team_id and _held(caster, INCARNATION) and engine._distance_actor_to_actor(caster, attacker) <= 30:
            give_mark(engine, caster, attacker, INCARNATION_ID)  # "when a hostile creature within 30 feet hits you or an ally"


# ------------------------------------------------------------------------------------------------ movement, hiding, the Domain
@hook("event")
def glass_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED" and not payload.get("forced") and not engine.__dict__.get("_glass_moving"):
        mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        path = [p for p in payload.get("path") or [] if isinstance(p, dict)]
        if mover is not None and mover.active and len(path) >= 2 and engine.state.current_actor_id == mover.entity_id:
            engine.__dict__["_glass_moving"] = True
            try:
                _road_mark(engine, mover, path)
                _bitter_edge(engine, mover)
                _shattered_mark(engine, mover, path)  # after Bitter Edge: the move that earns the mark does not also spend it
                _domain_cross(engine, mover, path)  # Glass Domain: crossing a Glass Surface inside it earns the Domain's mark
            finally:
                engine.__dict__["_glass_moving"] = False
    elif event_type == "CONDITION_APPLIED" and str(payload.get("condition_id") or "").endswith(".hidden"):
        for target_id in kwargs.get("target_ids") or ():
            subject = engine.state.actors.get(target_id)
            if subject is not None:
                _visible_crack(engine, subject)
    elif event_type == "DAMAGE_COMMITTED" and int(payload.get("reduced_to") or 0) > 0:
        doer = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
        victims = [engine.state.actors.get(t) for t in kwargs.get("target_ids") or ()]
        if doer is not None:
            _domain_mark(engine, doer, [v for v in victims if v is not None])
    elif event_type == "ZONE_CREATED":
        created = payload.get("zone") or {}
        zone = engine.state.zones.get(str(created.get("zone_id") or ""))
        if zone is not None and not engine.__dict__.get("_glass_domain_terrain"):
            engine.__dict__["_glass_domain_terrain"] = True
            try:
                _domain_terrain(engine, zone)
            finally:
                engine.__dict__["_glass_domain_terrain"] = False


@hook("event", nested=True)
def domain_terrain_end_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A Domain that ends takes its Shattered Glass Terrain with it, whenever that ending happens.

    ``glass_events`` above is an ordinary subscriber, so it only sees the Domain's ZONE_REMOVED when the Domain ends at
    the top level of a resolution. A Domain can also end *inside* another event -- damage from a movement-triggered
    response fails its caster's Concentration, say -- and the engine only offers a nested event to subscribers that
    opted into nested delivery (combat/gate4_engine.py). Without that opt-in, terrain tied to the Domain by
    ``domain_terrain`` would keep its "lasts until the Domain ends" promise with no Domain left to end it and no
    countdown of its own, so it would last the rest of the fight.

    ``nested=True`` still delivers root events as well as nested ones, so this is the one place a Domain's end is
    handled (the ordinary branch that used to sit in ``glass_events`` is gone). It returns immediately for every event
    type that is not a zone removal, and ``_domain_terrain_end`` itself only touches patches whose own record names the
    removed zone, so nothing happens for a fight with no Glass Domain or no linked terrain.
    """
    if event_type != "ZONE_REMOVED":
        return
    _domain_terrain_end(engine, str((kwargs.get("payload") or {}).get("zone_id") or ""))


def _road_mark(engine: Any, mover: Any, path: list[dict[str, Any]]) -> None:
    """Glass Road: "When a hostile creature willingly moves across the road, you may place a Faultline Mark on it once per turn." """
    for caster in _casters(engine):
        if caster.team_id == mover.team_id:
            continue
        for zone in _zones_of(engine, caster, {T + "GLASS_ROAD"}):
            cells = {(c.x, c.y) for c in zone.affected_cells}
            if any((int(p["x"]), int(p["y"])) in cells for p in path[1:]) and mover.turn_flags.get(f"glass_road:{caster.entity_id}") != mover.turns_started:
                mover.turn_flags[f"glass_road:{caster.entity_id}"] = mover.turns_started
                give_mark(engine, caster, mover, T + "GLASS_ROAD")


def _shattered_mark(engine: Any, mover: Any, path: list[dict[str, Any]]) -> None:
    """Faultline Marks: "You may place a Faultline Mark when ... a creature willingly moves across Shattered Glass Terrain you
    created" (rider lane C13, 2026-09-30): a hostile creature's own move across your Shattered Glass Terrain, once per turn; the
    mark is your choice (asked; the built-in AI places it)."""
    from .. import zones
    from .rider_choices import pick

    for caster in _casters(engine):
        if caster.team_id == mover.team_id or marked(mover, caster.entity_id) \
                or mover.turn_flags.get(f"glass_shattered:{caster.entity_id}") == mover.turns_started:
            continue
        for zone in zones.typed_zones(engine):
            if not (zone.active and zone.owner_id == caster.entity_id
                    and "shattered glass" in " ".join(str(t).lower() for t in zone.trigger_profile.get("terrain") or [])):
                continue
            cells = {(c.x, c.y) for c in zone.affected_cells}
            if not any((int(p["x"]), int(p["y"])) in cells for p in path[1:]):
                continue
            mover.turn_flags[f"glass_shattered:{caster.entity_id}"] = mover.turns_started
            if pick(engine, caster, "glass_shattered_mark", "Faultline Mark", ["mark"], subject=mover, preferred=["mark"],
                    labels={"mark": f"Place a Faultline Mark on {mover.display_name} (it crossed your Shattered Glass Terrain)"},
                    trigger=f"{mover.display_name} moves across your Shattered Glass Terrain"):
                give_mark(engine, caster, mover, "GLASS_BASE_FAULTLINE_MARKS")
            break


def _bitter_edge(engine: Any, mover: Any) -> None:
    for caster in _casters(engine):
        if caster.team_id == mover.team_id or not marked(mover, caster.entity_id):
            continue
        with _offer(engine, caster, mover, "bitter", "Bitter Edge: PB Slashing damage and 10 feet less movement",
                        also=_also_step(engine, caster, mover)) as answer:
            if answer == "step":
                _do_step(engine, caster, mover)
                return
            if answer == "bitter":
                engine._commit_damage(mover, int(_row(engine, caster).get("pb", 2)), "SLASHING", RESPONSES_ID, caster.entity_id, None, reaction_depth=1)
                mover.movement_remaining_ft = max(0, int(mover.movement_remaining_ft) - 10)
                return


def _visible_crack(engine: Any, subject: Any) -> None:
    for caster in _casters(engine):
        if caster.team_id == subject.team_id or not marked(subject, caster.entity_id):
            continue
        with _offer(engine, caster, subject, "crack", "Visible Crack: its space is known", also=_also_step(engine, caster, subject)) as answer:
            if answer == "step":
                _do_step(engine, caster, subject)
                return
            if answer == "crack":
                for held in [c for c in subject.conditions.values() if c.condition_id.endswith(".hidden")]:
                    engine._remove_condition(subject, held.condition_id, RESPONSES_ID)
                engine._apply_condition(subject, C + "glass_revealed", RESPONSES_ID, caster.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Visible Crack: its space is known"})
                return


def _domain_zones(engine: Any, caster: Any, inside: Any) -> list[Any]:
    """The caster's own live Domains that ``inside`` stands within (Glass Domain: Court of Visible Faults)."""
    from .. import zones

    return [zone for zone in _zones_of(engine, caster, {DOMAIN_ID}) if zones._inside(engine, inside, zone)]


def _domain_cells(engine: Any, caster: Any, probe: Any) -> dict[str, set[tuple[int, int]]]:
    """The squares inside each of ``caster``'s live Glass Domains, by zone id, read through the area test itself.

    A zone's recorded ``affected_cells`` are the squares its area covers, which for a round Emanation is a block wider than
    the circle; ``probe`` (the creature the question is about) decides each square, so "inside the Domain" means what the
    engine means by it everywhere else."""
    from ..gate2_runtime_models import Position
    from .. import zones

    return {zone.zone_id: {(cell.x, cell.y) for cell in zone.affected_cells
                           if zones._inside(engine, probe, zone, position=Position(x=cell.x, y=cell.y))}
            for zone in _zones_of(engine, caster, {DOMAIN_ID})}


def _domain_mark_open(engine: Any, doer: Any, caster: Any) -> bool:
    """Whether this hostile creature's once-a-round Glass Domain mark is still available."""
    return doer.turn_flags.get(f"glass_domain:{caster.entity_id}") != engine.state.round_number


def _domain_mark_now(engine: Any, caster: Any, doer: Any, why: str) -> None:
    """The printed "you may place a Faultline Mark on that creature": asked (an Ask me owner may decline, even on someone
    else's turn), and the once-a-round chance is spent only when a mark is actually placed."""
    from .rider_choices import pick

    if doer.team_id == caster.team_id or not _domain_mark_open(engine, doer, caster):
        return
    if not pick(engine, caster, "glass_domain_mark", "Glass Domain", ["mark"], subject=doer, preferred=["mark"],
                labels={"mark": f"Place a Faultline Mark on {doer.display_name}"},
                trigger=f"{doer.display_name} {why}", optional=True, automatic=_ai_owns(engine, caster)):
        return
    doer.turn_flags[f"glass_domain:{caster.entity_id}"] = engine.state.round_number
    give_mark(engine, caster, doer, DOMAIN_ID)


def _domain_mark(engine: Any, doer: Any, victims: list[Any]) -> None:
    """Glass Domain: "the first time each round that a hostile creature inside damages an ally, crosses a Glass Surface, attacks
    through a Glass Surface, or damages a Glass Surface, you may place a Faultline Mark on that creature"."""
    for caster in _casters(engine):
        if doer.team_id == caster.team_id or not any(v.team_id == caster.team_id and v is not doer for v in victims):
            continue
        if any(_domain_zones(engine, caster, doer)):
            _domain_mark_now(engine, caster, doer, "damages an ally inside your Glass Domain")


def _domain_attacked(engine: Any, attacker: Any, victim: Any) -> None:
    """Glass Domain's "attacks through a Glass Surface" part of the same once-a-round mark.

    The blow's own path decides, and the printed clause restricts only the attacker and the glass it crosses: "the first
    time each round that a hostile creature inside [the Domain] ... attacks through a Glass Surface [inside it]". It names
    no side for the creature attacked and does not put it inside the Domain either, so a hostile attacker inside shooting
    through one of the caster's panes at an ally standing outside is the same printed trigger -- the attacker and the
    crossed surface are resolved on their own, never through the victim's team or where it stands. The crossed square must
    be both a Glass Surface the caster controls and inside the Domain (inside the Domain "your body counts as a tempered
    Glass Surface"), so glass the caster did not make, or glass outside, is not this line's mark. An ally treating their own
    worn armor, held weapon or held shield as a Glass Surface is that ally's own standing choice, which this fight does not
    record, so it stays with the players and the GM. This fires on a miss too: the printed trigger is the attack, not the
    damage."""
    if victim is None or not victim.active:
        return
    for caster in _casters(engine):
        if attacker.team_id == caster.team_id:
            continue
        surfaces = _surface_cells(engine, caster)
        if not surfaces:
            continue
        # the attacker must actually stand inside one of the caster's Domains. Reading "inside" from the Domain's own
        # squares is not enough: a live Domain has interior squares whether or not the attacker is on them, so an
        # attacker shooting in from outside would qualify on glass it never stood in. _domain_zones answers membership
        # through the same area test the rest of the fight uses, on the attacker's own position.
        domains = _domain_zones(engine, caster, attacker)
        if not domains:
            continue
        # every qualifying Domain is considered, not only the first, and only each one's own squares are glass to cross
        cells = _domain_cells(engine, caster, attacker)
        inside: set[tuple[int, int]] = set()
        for domain in domains:
            inside |= cells.get(domain.zone_id) or set()
        crossed = [cell for cell in engine.grid.ray_cells(attacker.position, victim.position)[1:-1]
                   if cell in surfaces and cell in inside]
        if crossed:
            _domain_mark_now(engine, caster, attacker, "attacks through a Glass Surface inside your Glass Domain")
            return


def _domain_cross(engine: Any, mover: Any, path: list[dict[str, Any]]) -> None:
    """Glass Domain's "crosses a Glass Surface" part: a hostile creature inside the Domain that walks over one of the caster's
    Glass Surfaces *there* earns the same once-a-round mark. Only the squares the path actually passes over count, and each must
    be both inside the Domain and glass: crossing out of the Domain, or entering it and standing on nothing, is not a crossing."""
    for caster in _casters(engine):
        if mover.team_id == caster.team_id:
            continue
        surfaces = _surface_cells(engine, caster)
        for inside in _domain_cells(engine, caster, mover).values():
            crossed = [(int(p["x"]), int(p["y"])) for p in path[1:]
                       if (int(p["x"]), int(p["y"])) in surfaces and (int(p["x"]), int(p["y"])) in inside]
            if crossed:
                _domain_mark_now(engine, caster, mover, "crosses a Glass Surface inside your Glass Domain")
                return


DOMAIN_LINK = "glass_domain_zone"   # trigger_profile[DOMAIN_LINK]: the Domain a terrain patch is tied to (its zone id)


def domain_terrain(engine: Any, zone_id: str) -> bool:
    """Tie one Shattered Glass Terrain patch to the Domain it was made inside, if there is one; True when this call tied it.

    Glass Domain: "Shattered Glass Terrain you create inside the Domain lasts until the Domain ends." The patch stops counting
    down and remembers the Domain's zone id (a string, so a committed fight replays it), and ``_domain_terrain_end`` removes it
    when that Domain ends. A patch made outside the Domain, or one that already carries a tie, is left exactly as its own printed
    duration says.

    Public because the terrain a pane break leaves is written while another event is still being handled, and the engine only
    runs hooks that opted into nested events for an event raised inside one -- so this Domain's own ZONE_CREATED handler never
    sees that patch. glass_pane asks for the tie by zone id instead, rather than leaving the terrain on a shorter clock than
    the printed rule promises."""
    from ..gate2_runtime_models import Position

    zone = engine.state.zones.get(str(zone_id))
    if zone is None or not zone.active or zone.trigger_profile.get(DOMAIN_LINK):
        return False
    owner = engine.state.actors.get(str(zone.owner_id or ""))
    if owner is None:
        return False
    if "shattered glass" not in " ".join(str(t).lower() for t in zone.trigger_profile.get("terrain") or []):
        return False
    domain = next((d for d in _zones_of(engine, owner, {DOMAIN_ID})
                   if engine.grid.distance_cells((zone.center.x, zone.center.y), (d.center.x, d.center.y)) <= int(d.radius_cells or 0)), None)
    if domain is None or domain.zone_id == zone.zone_id:
        return False
    kept = zone.model_copy(update={"duration_rounds": None, "trigger_profile": {**zone.trigger_profile, DOMAIN_LINK: domain.zone_id}})
    engine.state.zones[zone.zone_id] = kept
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id, payload={"zone": kept.model_dump(mode="json")})
    note(engine, str(zone.source_definition_id or DOMAIN_ID), owner,
         f"Glass Domain: this Shattered Glass Terrain is inside your Domain, so it lasts until the Domain ends.")
    return True


def _domain_terrain(engine: Any, zone: Any) -> None:
    """The ZONE_CREATED path into ``domain_terrain`` (the Domain's own area, and terrain a top-level action makes)."""
    domain_terrain(engine, zone.zone_id)


def _domain_terrain_end(engine: Any, zone_id: str) -> None:
    """The Domain ended: the Shattered Glass Terrain that was inside it leaves with it."""
    from .. import zones

    for zone in [z for z in zones.typed_zones(engine) if z.active and z.trigger_profile.get(DOMAIN_LINK) == zone_id]:
        zones.remove(engine, zone, "its Glass Domain ended")


# ------------------------------------------------------------------------------------------------ technique-bound parts
@effect("glass_temper")
def glass_temper(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.engine._apply_condition(ctx.actor, TEMPERED, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"label": "Tempered Glass Surface (its body, armor or held weapon)"})


@effect("glass_lens")
def glass_lens(ctx: Any, eff: dict[str, Any]) -> None:
    for target in ctx.targets or []:
        if target is not None and target.active:
            ctx.engine._apply_condition(target, LENS, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Lens of the Honest Crack: its first attack or technique marks it"})


@hook("technique_start")
def lens_on_technique(engine: Any, actor: Any, action: Any) -> bool | None:
    for lens in _held(actor, LENS):
        owner = engine.state.actors.get(lens.source_actor_id)
        engine._remove_condition(actor, LENS, T + "LENS_OF_THE_HONEST_CRACK")
        if owner is not None:
            give_mark(engine, owner, actor, T + "LENS_OF_THE_HONEST_CRACK")  # "casts a spell, spends CP, activates a supernatural feature"
    return None


@hook("row_allowed")
def polished_needs_a_surface(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Polished Warning: "If you do not have a legal Glass Surface, you cannot use this talent." """
    if str(row.get("feature_id") or "") == T + "POLISHED_WARNING" and not tempered(engine, actor):
        return False
    return None


@hook("technique_used")
def glass_used(ctx: Any) -> None:
    if str(ctx.typed.get("source") or "") == INCARNATION_ID:
        ctx.engine._apply_condition(ctx.actor, INCARNATION, INCARNATION_ID, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                    data={"label": "Incarnation of the Transparent Fault"})


@hook("would_drop")
def living_pane(engine: Any, target: Any, pending: int, source_actor_id: Any) -> int | None:
    """Living Pane Sutra: "Once per short rest, when you would be reduced to 0 HP but not killed outright, you may shatter your outer
    glass-bone shell and drop to 1 HP instead" (its body tempered; once a fight)."""
    if not rows(engine, target, "living_pane") or not tempered(engine, target) or _held(target, SPARED):
        return None
    engine._apply_condition(target, SPARED, T + "LIVING_PANE_SUTRA", target.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": "Living Pane Sutra used"})
    note(engine, T + "LIVING_PANE_SUTRA", target, f"Living Pane Sutra: {target.display_name}'s glass-bone shell shatters; it stays at 1 HP.")
    _shell_terrain(engine, target)
    return max(0, int(target.current_hp) + int(target.temporary_hp) - 1)


def _owner_action(engine: Any, owner: Any, feature_id: str) -> Any:
    """The catalog action a passive Glass talent's printed effect is recorded under.

    A passive talent (Living Pane Sutra, Clean Break) owns no action of its own, so its terrain is attributed to one of the
    owner's own Glass actions -- the Temper Glass Surface that made the body a surface, or the first one they have. Nothing is
    invented: an event needs a real source definition to name."""
    found = engine.action_catalog.get(feature_id)
    if found is not None:
        return found
    typed_sources = {str((((action.parameters or {}).get("typed") or {}).get("source")) or "")
                     for action in engine.action_catalog.values() if action.owner_id == owner.entity_id}
    for wanted in (T + "TEMPER_GLASS_SURFACE", T + "LIVING_PANE_SUTRA"):
        for source in typed_sources:
            if source == wanted:
                for action in engine.action_catalog.values():
                    if action.owner_id == owner.entity_id and \
                            str((((action.parameters or {}).get("typed") or {}).get("source")) or "") == source:
                        return action
    return next((action for action in engine.action_catalog.values() if action.owner_id == owner.entity_id), None)


def _shell_terrain(engine: Any, owner: Any) -> None:
    """Living Pane Sutra: "When you do, create Shattered Glass Terrain in each space adjacent to you."

    One patch per adjacent 5-foot square, the same Shattered Glass Terrain and the same two rounds Clean Break's printed
    square of it uses, since the shell's own line prints no other length."""
    from .. import typed_executor
    from . import glass_pane

    squares = [(owner.position.x + dx, owner.position.y + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))]
    squares = [cell for cell in squares if engine.grid.in_bounds(cell)]
    if not squares:
        return
    source = T + "LIVING_PANE_SUTRA"
    action = _owner_action(engine, owner, source)
    if action is None:
        return
    ctx = typed_executor.Context(engine, owner, action, getattr(engine, "_active_intent", None),
                                 {"numbers": {}, "source": source, "effects": [], "riders": []}, [], owner)
    before = set(engine.state.zones)
    typed_executor.run_effects(ctx, [{"type": "terrain_patch", "terrain": glass_pane.TERRAIN, "name": "Shattered Glass Terrain",
                                      "duration": {"kind": "rounds", "amount": 2}, "center": {"x": x, "y": y},
                                      "evidence": "the shell shatters and creates Shattered Glass Terrain in each space adjacent to you"}
                                     for x, y in squares])
    # "Shattered Glass Terrain you create inside the Domain lasts until the Domain ends" outranks this shell's own two
    # rounds, and the shell is written inside a damage event, so the tie is asked for by zone id (see domain_terrain)
    for zone_id in [key for key in engine.state.zones if key not in before]:
        domain_terrain(engine, zone_id)
    note(engine, str(action.source_definition_id), owner, f"Living Pane Sutra: Shattered Glass Terrain fills the {len(squares)} space(s) around {owner.display_name}.")


@hook("difficult_exempt")
def careful_feet(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """Careful Feet on Broken Light: "You ignore difficult terrain from Shattered Glass Terrain you created.\""""
    from .. import zones

    if not rows(engine, actor, "careful_feet"):
        return None
    cells: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        if zone.active and zone.owner_id == actor.entity_id and "shattered glass" in " ".join(str(t).lower() for t in zone.trigger_profile.get("terrain") or []):
            cells |= {(c.x, c.y) for c in zone.affected_cells}
    return cells or None
