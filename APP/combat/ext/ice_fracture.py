"""Ice's Fracture Marks and Fracture Responses (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Sphere
Compendium, Ice (owner's text: authority/typed_mechanics/rules_text.json, ICE_BASE_SPENDING_A_FRACTURE_MARK and the talents below).
combat/ext/ice_lattice.py places the Lattice Spaces; this module spends the marks.  Rows: feature block "lane9_ice"
(combat/rules/feature_blocks.d/riders_lane9.json); the base row also carries the Fracture Mark cap (PB; +1 with Nascent Soul: Glacier
Soul Takes Shape) as a "mark_caps" row.  A Fracture Mark "lasts until the end of your next turn" (typed_conditions.json mark_durations).

Spending a Fracture Mark: "Once per round, when a marked creature or object you can perceive performs a triggering act, you may spend its
Fracture Mark without using an Action. Choose one Fracture Response appropriate to the trigger."  How each trigger is met here:
  Catch Step       the marked creature's turn starts (before it moves): its movement this turn drops by 10 feet (20 at CL 11).
  Brittle Opening  it is hit by an attack (after_hit): 1d4 + PB (1d6 at CL 11) extra Cold damage.
  Crack Aim        it makes an attack roll (attack_bonus) or a Dexterity save (save hook): -1d4 (1d6 at CL 11).
  Shatter Space    it enters, starts or ends its turn in one of your Lattice Spaces: Dexterity save, Shard Needle damage and Prone (half and
                   no Prone on a success); that Lattice Space ends.
  Lock Grip        it attacks with a weapon (after its attack): Disadvantage on its next attack roll with it until the start of its next turn.
  Crystal Guard    a marked willing creature (your side) takes damage: -1d6 (2d6 at CL 5, 3d6 at CL 11, 4d6 at CL 17) + your key modifier.
Once per round per Ice cultivator; twice while The World Becomes a Single Crystal lasts; once more on each of your own turns while Immortal
Winter Crucible lasts.  The spender is asked (needle.ask); with no answer the table uses every response that helps its side.

Talents on top:
  Crystallize Path       N Lattice Spaces by CL (2/3/4/5) through ice_lattice's lattice_spaces; a creature not on your side that moves 10
                         feet or more across, out of or through your Lattice Spaces in one turn gains a Fracture Mark (once per creature a turn).
  Mirror-Slick Floor     that creature makes a Dexterity save or falls Prone (Advantage if it moved half its Speed or less this turn); a
                         success makes it immune until the start of your next turn.
  Ninefold Crack         1 CP: a second, different response on the same event (Crack Aim + Lock Grip on its weapon attack; Brittle Opening +
  Calculation            Shatter Space on a hit while it stands on your lattice; Catch Step + Shatter Space as its turn starts there).
  Rime Hook              after Catch Step or Shatter Space: it moves 5 feet (10 at CL 11) to an unoccupied Lattice Space (or a space next to
                         one), provoking no Opportunity Attacks.
  Frozen Meridian Bind   1 CP after Catch Step when it is on or next to your lattice: Strength save or Restrained until the end of its next turn.
  Bitter Edge            once each turn the coated wielder may add PB Cold or Piercing damage on a hit; the target gains a Fracture Mark if it
                         stands on your lattice.
  Frost-Sheathed Guard   the first creature to hit the guarded creature with a melee attack while its Temporary HP last gains a Fracture Mark.
  Diamond Rime Body      when a creature hits you with a melee attack, a Lattice Space appears under it.
  Crystal Step           arriving next to a creature with your Fracture Mark, the mark moves to another creature within 10 feet of you.
  Winter Stores the Blow Reaction, 1 CP: a creature you can see standing on your lattice takes damage -- it drops by PB + key modifier, and
                         your next Shatter Space or Shatter Bloom on a chosen under/adjacent space before the end of your next turn adds that much.
  White Step Counter     Reaction: a creature leaving a space within 10 feet of your lattice gains a Fracture Mark.
  Frozen River Reversal  Reaction, 3 CP: a marked creature moves from one of your Lattice Spaces to another -- Strength save (Charisma for a
                         teleport) or it is returned; a success: Speed -10 until the end of its next turn.
  Ice Coffin             the shell gives Cover (+2 AC) and the target repeats its Strength save at the end of each of its turns.
  Thousand-Facet Prison  the target repeats its Strength save at the end of each of its turns.
  Ice Domain             a hostile creature that moves 10 feet or more inside gains a Fracture Mark; spending a mark on a creature inside
                         puts a Lattice Space under it (ending with the Domain).
  The World Becomes a    two spends a round; the first time each hostile creature moves 5 feet or more on its turn it gains a Fracture Mark.
  Single Crystal
  Shatter Bloom          up to PB chosen Lattice Spaces within 60 feet shatter: each creature in or within 5
                         feet of one saves once -- Shard Needle damage + key modifier and Prone, half on a success.

Shared API for ice_second_pass: source_feature identifies compiled sources;
fracture_numbers returns the sealed base numbers; response_available/count_response
quote and consume the existing response limit; shatter_response delivers the
printed Shatter Space through the existing choices and save. No extra mark cost.

Judgment calls: Catch Step is decided as the marked creature's turn starts (a player is asked; the AI uses it when the creature is not
already next to your side); "safe" creatures are your side; Brittle Opening's damage is Cold; Crystal Step's mark goes to the nearest
other hostile creature; Rime Hook's space is the nearest free Lattice Space (or a free space next to one) in reach.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note, run_checkpoint
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_ice"
T = "TAL_ICE_"
BASE = "ICE_BASE_SPENDING_A_FRACTURE_MARK"
MARK = "Fracture Mark"
C = "condition:typed."
LOCK, SLICK_IMMUNE, BITTER, GUARD, RIME, CRUCIBLE = (C + "lock_grip", C + "mirror_slick_immune", C + "bitter_edge", C + "frost_guard",
                                                   C + "diamond_rime", C + "winter_crucible")
LATTICE_SOURCES = {"ICE_BASE_CRYSTALLIZE_PATH", T + "GLACIER_WALL", T + "WORLD_FANG_ICEFALL", T + "ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER",
                   T + "THE_WORLD_BECOMES_A_SINGLE_CRYSTAL"}
DOMAIN, WORLD = T + "ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER", T + "THE_WORLD_BECOMES_A_SINGLE_CRYSTAL"
STORED = C + "winter_stored_fracture"


def _take_stored(engine: Any, caster: Any, cell: tuple[int, int]) -> int:
    """Consume this owner's saved fractures once, on one damage roll for their space."""
    from .effect_durations import due

    damage = 0
    for iid, condition in list(caster.conditions.items()):
        data = condition.data or {}
        if condition.condition_id != STORED or condition.source_actor_id != caster.entity_id \
                or (data.get("x"), data.get("y")) != cell:
            continue
        zone = engine.state.zones.get(data.get("zone_id"))
        if not due(engine, condition.expires_on) and zone is not None and zone.active \
                and zone.owner_id == caster.entity_id and any((p.x, p.y) == cell for p in zone.affected_cells):
            damage += int(data.get("amount", 0))
        del caster.conditions[iid]
        engine._append_event("CONDITION_REMOVED", T + "WINTER_STORES_THE_BLOW", actor_id=caster.entity_id,
                             target_ids=(caster.entity_id,), payload={"condition_id": STORED, "instance_id": iid})
    return damage


# ------------------------------------------------------------------------------------------------ rows
@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             "key_mod": int(numbers.get("key_mod") or 0), "keeps_compiling": bool(spec.get("keeps_compiling")),
             **({"auto66": True} if spec.get("auto66") else {})}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _row(engine: Any, caster: Any) -> dict[str, Any]:
    found = rows(engine, caster, "fracture")
    return found[0] if found else {}


def _casters(engine: Any) -> list[Any]:
    return [a for a in engine.state.actors.values() if a.active and rows(engine, a, "fracture")]


def _held(actor: Any, condition_id: str) -> list[Any]:
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _mark_id(owner_id: str) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner_id)


def marked(actor: Any, owner_id: str) -> bool:
    return any(c.condition_id == _mark_id(owner_id) for c in actor.conditions.values())


def _feature(engine: Any, source: Any) -> str:
    action = engine.action_catalog.get(str(source or ""))
    return str((((action.parameters or {}).get("typed") or {}).get("source") or "")) if action is not None else ""


def _ctx(engine: Any, actor: Any, other: Any, feature: str, name: str, numbers: dict[str, Any] | None = None) -> Any:
    from .. import typed_reactions

    return typed_reactions._generic_context(engine, actor, other, {"feature_id": feature, "name": name, "effects": [], "numbers": dict(numbers or {})})


def _roll(engine: Any, actor: Any, count: int, sides: int, reason: str) -> int:
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=count, sides=sides, modifier=0), actor_id=actor.entity_id, reason=reason)
    engine._record_roll(roll)
    return int(roll.total)


def _dc(engine: Any, actor: Any) -> int:
    for action in engine.action_catalog.values():
        if action.owner_id == actor.entity_id:
            numbers = ((action.parameters or {}).get("typed") or {}).get("numbers") or {}
            if numbers.get("save_dc"):
                return int(numbers["save_dc"])
    return 10


def give_mark(engine: Any, caster: Any, subject: Any, source: str) -> None:
    """A Fracture Mark from ``caster`` on ``subject`` through typed_executor's own block_mark (its cap, its duration)."""
    from ..typed_executor import block_mark

    if subject is None or not subject.active:
        return
    row = _row(engine, caster)
    block_mark(_ctx(engine, caster, subject, source, "Fracture Mark", {"pb": row.get("pb", 2), "cl": row.get("cl", 1)}),
               {"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "until_removed"}})


# ------------------------------------------------------------------------------------------------ Lattice Spaces
def lattice_zones(engine: Any, owner_id: str) -> list[Any]:
    from .. import zones

    return [z for z in zones.typed_zones(engine) if z.active and z.owner_id == owner_id
            and (z.trigger_profile.get("lattice_space") or _feature(engine, z.source_definition_id) in LATTICE_SOURCES)]


def lattice_cells(engine: Any, owner_id: str) -> set[tuple[int, int]]:
    return {(cell.x, cell.y) for zone in lattice_zones(engine, owner_id) for cell in zone.affected_cells}


def _cells_of(engine: Any, actor: Any) -> set[tuple[int, int]]:
    return {tuple(cell) for cell in engine._actor_cells(actor)}


def on_lattice(engine: Any, owner_id: str, actor: Any) -> bool:
    return bool(_cells_of(engine, actor) & lattice_cells(engine, owner_id))


def _near_lattice(engine: Any, owner_id: str, actor: Any, feet: int = 5) -> bool:
    reach = feet // engine.grid.square_size_ft
    cells = lattice_cells(engine, owner_id)
    return any(max(abs(x - lx), abs(y - ly)) <= reach for x, y in _cells_of(engine, actor) for lx, ly in cells)


def _end_space(engine: Any, owner_id: str, cell: tuple[int, int]) -> None:
    """One Lattice Space ends: a one-space zone goes; a larger lattice loses that cell."""
    from .. import zones

    for zone in lattice_zones(engine, owner_id):
        cells = [(c.x, c.y) for c in zone.affected_cells]
        if cell not in cells:
            continue
        if _feature(engine, zone.source_definition_id) == WORLD:
            return  # The World Becomes a Single Crystal: "you may choose not to end the Lattice Space if that space is part of the ... area"
        from .ice_second_pass import preserve_space
        if preserve_space(engine, zone, cell):
            return
        if len(cells) <= 1:
            zones.remove(engine, zone, "SHATTERED")
        else:
            zone.trigger_profile["footprint_is_authoritative"] = True
            ended = tuple(c for c in zone.affected_cells if (c.x, c.y) == cell)
            run_checkpoint("zone_cells_destroyed", engine, zone, ended)
            zone.affected_cells = tuple(c for c in zone.affected_cells if (c.x, c.y) != cell)
            engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=owner_id, payload={"zone": zone.model_dump(mode="json")})
        return


def _shard_dice(cl: int) -> int:
    return 1 if cl <= 4 else 2 if cl <= 10 else 3 if cl <= 16 else 4


# ------------------------------------------------------------------------------------------------ spending
def _free_crucible_mark(engine: Any, caster: Any) -> bool:
    return bool(any(c.data.get("second_pass") for c in _held(caster, CRUCIBLE))
                and engine.state.current_actor_id == caster.entity_id
                and caster.turn_flags.get("ice_crucible_free_turn") != caster.turns_started)


def _spend_limit(engine: Any, caster: Any, *, spends_mark: bool = True) -> int:
    from .. import zones
    limit = 2 if any(z.owner_id == caster.entity_id and _feature(engine, z.source_definition_id) == WORLD
                     for z in zones.typed_zones(engine) if z.active) else 1
    # Historical sealed Crucible rows retain their previous bookkeeping. New
    # rows own a separate per-owner-turn free MARK spend, never a round debit.
    if spends_mark and _held(caster, CRUCIBLE) and not any(c.data.get("second_pass") for c in _held(caster, CRUCIBLE)) \
            and engine.state.current_actor_id == caster.entity_id and caster.turn_flags.get("ice_crucible_spent") != engine.state.round_number:
        limit += 1
    return limit


def _can_spend(engine: Any, caster: Any, *, spends_mark: bool = True) -> bool:
    used = caster.turn_flags.get("ice_spent_round") or ""
    count = int(used.split(":")[1]) if used.startswith(f"{engine.state.round_number}:") else 0
    return caster.active and (count < _spend_limit(engine, caster, spends_mark=spends_mark)
                             or spends_mark and _free_crucible_mark(engine, caster))


def _count_spend(engine: Any, caster: Any, *, spends_mark: bool = True) -> None:
    used = caster.turn_flags.get("ice_spent_round") or ""
    count = int(used.split(":")[1]) if used.startswith(f"{engine.state.round_number}:") else 0
    if spends_mark and _free_crucible_mark(engine, caster):
        caster.turn_flags["ice_crucible_free_turn"] = caster.turns_started
        note(engine, T + "IMMORTAL_WINTER_CRUCIBLE", caster,
             "Immortal Winter Crucible: this Fracture Mark spend uses your free allowance for this turn; your round limit is unchanged.")
        return
    if spends_mark and count >= 1 and _held(caster, CRUCIBLE) and not any(c.data.get("second_pass") for c in _held(caster, CRUCIBLE)) \
            and engine.state.current_actor_id == caster.entity_id:
        caster.turn_flags["ice_crucible_spent"] = engine.state.round_number
    caster.turn_flags["ice_spent_round"] = f"{engine.state.round_number}:{count + 1}"


RESPONSES = {"catch": "Catch Step", "brittle": "Brittle Opening", "crack": "Crack Aim", "shatter": "Shatter Space", "lock": "Lock Grip",
             "guard": "Crystal Guard"}


def _offer(engine: Any, caster: Any, subject: Any, response: str, *, want: bool = True, second: tuple[str, ...] = ()) -> list[str]:
    """Whether ``caster`` spends ``subject``'s mark on ``response`` now (and, with Ninefold Crack Calculation, which second response).
    Returns the responses to apply ([] when it does not spend)."""
    free_guard = response == 'guard' and subject is caster and any(
        (c.data or {}).get('auto66') for c in _held(caster,RIME)) and caster.turn_flags.get('ice_rime_guard_round') != engine.state.round_number
    if not marked(subject, caster.entity_id) or (not free_guard and not _can_spend(engine, caster)):
        return []
    if _row(engine,caster).get('auto66'):
        from ..target_knowledge import located
        if not located(engine,caster,subject):
            return []
    label = f"Spend {subject.display_name}'s Fracture Mark: {RESPONSES[response]}"
    intent = getattr(engine, "_active_intent", None)
    picked = ask(engine, intent, checkpoint_id(engine, "FRACTURE", caster.entity_id, subject.entity_id, response), caster,
                 CHOICE + "fracture_response", [response], labels={response: label}, allow_decline=True, target_id=subject.entity_id,
                 default="first" if want else "decline", prompt=f"{subject.display_name} (Fracture Mark): {RESPONSES[response]}?")
    if not picked:
        return []
    engine._remove_condition(subject, _mark_id(caster.entity_id), BASE)
    if free_guard:
        caster.turn_flags['ice_rime_guard_round'] = engine.state.round_number
    else:
        _count_spend(engine, caster)
    note(engine, BASE, caster, f"Fracture Response: {RESPONSES[response]} on {subject.display_name}.")
    chosen = [response]
    ninefold = rows(engine, caster, "ninefold")
    from .d20_rewrite import pool_id

    cp = pool_id(caster, "cp")
    others = [r for r in second if r != response]
    if ninefold and others and cp is not None and caster.resources.get(cp, 0) >= 1:
        again = ask(engine, intent, checkpoint_id(engine, "NINEFOLD", caster.entity_id, subject.entity_id), caster,
                    CHOICE + "ninefold", others, labels={r: f"Ninefold Crack Calculation (1 CP): also {RESPONSES[r]}" for r in others},
                    allow_decline=True, target_id=subject.entity_id, prompt="Ninefold Crack Calculation: a second response?")
        if again:
            engine._spend_resource(caster, cp, 1, T + "NINEFOLD_CRACK_CALCULATION")
            chosen.append(again[0])
    _after_spend(engine, caster, subject)
    return chosen


def _after_spend(engine: Any, caster: Any, subject: Any) -> None:
    """Ice Domain: "when you spend a Fracture Mark inside the Domain, you may create one Lattice Space in the Domain without using an Action\""""
    from .. import zones

    for zone in zones.typed_zones(engine):
        if zone.active and zone.owner_id == caster.entity_id and _feature(engine, zone.source_definition_id) == DOMAIN and zones._inside(engine, subject, zone):
            from .choice_prompt import action_context

            intent = getattr(engine, "_active_intent", None)
            picked = ask(engine, intent, checkpoint_id(engine, "DOMAIN_LATTICE", caster.entity_id, subject.entity_id), caster,
                         CHOICE + "domain_lattice", ["create"], allow_decline=True, target_id=subject.entity_id,
                         labels={"create": f"Create one Lattice Space: a 5-foot ice space at {subject.display_name}. "
                                           "Use Shatter Space to shatter it under a marked creature for damage and a chance to knock it Prone. "
                                           "No Action or resource cost; ends when your Ice Domain ends."},
                         name="Ice Domain: Palace of Written Winter", feature_id=T + "ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER",
                         prompt=f"Ice Domain: after spending {subject.display_name}'s Fracture Mark, create a Lattice Space "
                                f"(a 5-foot ice space) at {subject.display_name}? A Fracture Mark lets you use an Ice response "
                                "against that creature: Shatter Space can break the ice when a marked creature enters it, "
                                "starts its turn there, or ends its turn there. The creature makes a Dexterity saving throw: "
                                "on a failure it takes damage and falls Prone; on a success it takes half damage and stays standing. "
                                "You must mark the creature again after spending its mark. "
                                "No Action or resource cost to create the space; it ends when your Ice Domain ends.",
                         prompt_context={**action_context(engine, engine.state.actors.get(getattr(intent, "actor_id", "")),
                                                         getattr(engine, "_active_action_source_id", "") or "", subject), "cost": "None"})
            if picked:
                _lattice_at(engine, caster, subject, T + "ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER", domain=zone.zone_id)
            return


def _lattice_at(engine: Any, owner: Any, where: Any, source: str, domain: str | None = None) -> None:
    from ..typed_executor import run_effects

    row = _row(engine, owner)
    run_effects(_ctx(engine, owner, where, source, "Lattice Space", {"pb": row.get("pb", 2), "key_mod": row.get("key_mod", 0), "cl": row.get("cl", 1)}),
                [{"type": "lattice_spaces", "formula": "none", "flat": 1, "duration": {"kind": "one_minute"},
                  **({"ends_with": domain} if domain else {})}])


def _apply(engine: Any, caster: Any, subject: Any, responses: list[str], *, pending: int = 0) -> int:
    """Run the chosen responses; returns damage to take off (Crystal Guard)."""
    row = _row(engine, caster)
    cl, pb, key = int(row.get("cl", 1)), int(row.get("pb", 2)), int(row.get("key_mod", 0))
    cut = 0
    for response in responses:
        if response == "catch":
            feet = 20 if cl >= 11 else 10
            subject.movement_remaining_ft = max(0, int(subject.movement_remaining_ft) - feet)
            note(engine, BASE, subject, f"Catch Step: {subject.display_name}'s Speed drops by {feet} feet this turn.")
            _meridian_bind(engine, caster, subject)
            _rime_hook(engine, caster, subject)
        elif response == "brittle":
            dtype = 'COLD'
            if row.get('auto66'):
                selected = ask(engine,getattr(engine,'_active_intent',None),
                    checkpoint_id(engine,'brittle_type',caster.entity_id,subject.entity_id),caster,
                    CHOICE+'brittle_type',['COLD','PIERCING'],labels={'COLD':'Cold','PIERCING':'Piercing'},
                    name='Brittle Opening', prompt=f'Brittle Opening: choose Cold or Piercing for the extra damage to {subject.display_name}. Your Fracture Mark is spent; no extra action or resource cost.')
                dtype = selected[0] if selected else 'COLD'
            extra = _roll(engine, caster, 1, 6 if cl >= 11 else 4, "BRITTLE_OPENING") + pb
            engine._commit_damage(subject, extra, dtype, BASE, caster.entity_id, None, reaction_depth=1)
        elif response == "shatter":
            _shatter(engine, caster, subject, cl, pb)
        elif response == "lock":
            engine._apply_condition(subject, LOCK, BASE, caster.entity_id, expires_on=_token("start", subject),
                                    data={"label": "Lock Grip: Disadvantage on its next attack roll with its weapon"})
        elif response == "guard":
            dice = 1 if cl < 5 else 2 if cl < 11 else 3 if cl < 17 else 4
            cut = _roll(engine, caster, dice, 6, "CRYSTAL_GUARD") + key
            note(engine, BASE, subject, f"Crystal Guard: the damage drops by {cut}.")
    return cut


def _token(edge: str, actor: Any, ahead: int = 1) -> str:
    from .effect_durations import token

    return token(edge, actor.entity_id, int(actor.turns_started) + ahead)


def _shatter(engine: Any, caster: Any, subject: Any, cl: int, pb: int) -> None:
    from ..typed_executor import run_effects

    cells = sorted(_cells_of(engine, subject) & lattice_cells(engine, caster.entity_id))
    if not cells:
        return
    intent = getattr(engine, "_active_intent", None)
    options = {f"{x},{y}": (x, y) for x, y in cells}
    chosen = ask(engine, intent, checkpoint_id(engine, "SHATTER_SPACE", caster.entity_id, subject.entity_id), caster,
                 CHOICE + "shatter_space", list(options), labels={key: f"Lattice Space ({key})" for key in options},
                 target_id=subject.entity_id,
                 prompt=f"Shatter Space: {subject.display_name} triggers your Fracture Response; choose its occupied Lattice Space")
    cell = options[chosen[0]]
    chosen_type = ask(engine, intent, checkpoint_id(engine, "SHATTER_TYPE", caster.entity_id, subject.entity_id), caster,
                      CHOICE + "shatter_type", ["COLD", "PIERCING"], labels={"COLD": "Cold", "PIERCING": "Piercing"},
                      target_id=subject.entity_id,
                      prompt=f"Shatter Space: choose Cold or Piercing damage against {subject.display_name}")
    ctx = _ctx(engine, caster, subject, BASE, "Shatter Space", {"save_dc": _dc(engine, caster), "cl": cl, "pb": pb})
    ctx.intent = intent
    run_effects(ctx, [{"type": "save", "ability": "DEX", "on_fail": [
        {"type": "damage", "dice": {"count": _shard_dice(cl), "sides": 8},
         "flat": _take_stored(engine, caster, cell), "damage_types": chosen_type, "applies_to": "target"},
        {"type": "condition", "condition": "prone", "applies_to": "target"}],
        "on_success": [{"type": "half_damage"}]}])
    _end_space(engine, caster.entity_id, cell)
    _rime_hook(engine, caster, subject)


def _meridian_bind(engine: Any, caster: Any, subject: Any) -> None:
    from .d20_rewrite import pool_id
    from .escape_options import escape_option

    cp = pool_id(caster, "cp")
    if not rows(engine, caster, "meridian_bind") or cp is None or caster.resources.get(cp, 0) < 1 or not _near_lattice(engine, caster.entity_id, subject):
        return
    # "Cost: 1 CP" on a No Action reaction: the owner chooses whether to pay it.
    intent = getattr(engine, "_active_intent", None)
    picked = ask(engine, intent, checkpoint_id(engine, "MERIDIAN_BIND_PAY", caster.entity_id, subject.entity_id), caster,
                 CHOICE + "meridian_bind", ["use"],
                 labels={"use": f"Frozen Meridian Bind (1 CP): {subject.display_name} must succeed on a Strength save or be Restrained"},
                 allow_decline=True, target_id=subject.entity_id, name="Frozen Meridian Bind",
                 prompt=f"Frozen Meridian Bind: after Catch Step, pay 1 CP to freeze {subject.display_name} in place? "
                        f"{subject.display_name} must succeed on a Strength save against your Ice Save DC or be Restrained by ice "
                        "until the end of its next turn; a Restrained creature can repeat that save as its Action. "
                        "On a successful save it is not Restrained. The restraint ends early if the creature later succeeds on a repeat save.")
    if not picked:
        return
    engine._spend_resource(caster, cp, 1, T + "FROZEN_MERIDIAN_BIND")
    dc = _dc(engine, caster)
    roll = engine._roll_save(subject, "STR", dc, T + "FROZEN_MERIDIAN_BIND")
    if roll is not None and int(roll.total) < dc:
        engine._apply_condition(subject, C + "restrained", T + "FROZEN_MERIDIAN_BIND", caster.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                                data={"label": "Frozen Meridian Bind: Restrained by ice"})
        escape_option(_ctx(engine, caster, subject, T + "FROZEN_MERIDIAN_BIND", "Frozen Meridian Bind", {"save_dc": dc}),
                      {"guards": ["restrained"], "kind": "save", "abilities": ["STR"], "name": "Frozen Meridian Bind"})
        note(engine, T + "FROZEN_MERIDIAN_BIND", subject, f"Frozen Meridian Bind: {subject.display_name} is Restrained by ice.")


def _rime_hook(engine: Any, caster: Any, subject: Any) -> None:
    """Rime Hook: "move the marked target 5 feet (10 at CL 11) to an unoccupied space that is part of your Frost Lattice or adjacent to
    it. This forced movement does not provoke Opportunity Attacks.\""""
    from ..gate2_runtime_models import Position

    found = rows(engine, caster, "rime_hook")
    if not found or not subject.active:
        return
    if found[0].get('auto66'):
        if subject.position.z:
            return  # Ground-only Lattice Spaces cannot certify an aerial destination.
        from .rider_movement import forced_route
        from .needle import cell_id
        feet = 10 if int(found[0]['cl']) >= 11 else 5
        cells = lattice_cells(engine,caster.entity_id)
        reachable = engine.grid.reachable(subject.position,movement_ft=feet,
            occupied_cells=engine._occupied_cells_except(subject.entity_id),footprint=engine._footprint(subject))
        paths = {cell_id(cell):path for cell,(path,cost) in reachable.items() if cost > 0
                 and any(max(abs(cell.x-x),abs(cell.y-y))<=1 for x,y in cells)}
        if not paths:
            return
        picked = ask(engine,getattr(engine,'_active_intent',None),checkpoint_id(engine,'rime_hook',caster.entity_id,subject.entity_id),
            caster,CHOICE+'rime_hook',sorted(paths),labels={key:'Move to '+key.removeprefix('cell:') for key in paths},
            allow_decline=True,name='Rime Hook', prompt=f'Rime Hook: move {subject.display_name} up to {feet} feet to a free space on or beside your lattice, without Opportunity Attacks? No action or resource cost.')
        if picked:
            forced_route(engine,subject,paths[picked[0]],T+'RIME_HOOK',caster)
        return
    reach = (10 if int(found[0]["cl"]) >= 11 else 5) // engine.grid.square_size_ft
    cells = lattice_cells(engine, caster.entity_id)
    occupied = engine._occupied_cells_except(subject.entity_id)
    here = subject.position
    options = sorted(((max(abs(x - here.x), abs(y - here.y)), x, y) for x in range(here.x - reach, here.x + reach + 1)
                      for y in range(here.y - reach, here.y + reach + 1)
                      if (x, y) != (here.x, here.y) and engine.grid.in_bounds((x, y)) and (x, y) not in occupied
                      and ((x, y) in cells or any(max(abs(x - lx), abs(y - ly)) <= 1 for lx, ly in cells))), key=lambda r: (-((r[1], r[2]) in cells), r[0], r[1], r[2]))
    if not options:
        return
    _, x, y = options[0]
    start = subject.position
    subject.position = Position(x=x, y=y)
    engine._append_event("MOVEMENT_COMMITTED", T + "RIME_HOOK", actor_id=subject.entity_id,
                         payload={"destination": subject.position.model_dump(mode="json"), "path": [start.model_dump(mode="json"), subject.position.model_dump(mode="json")],
                                  "cost_ft": 0, "forced": True})
    note(engine, T + "RIME_HOOK", subject, f"Rime Hook: {subject.display_name} is dragged across the lattice.")


# ------------------------------------------------------------------------------------------------ the triggers
@hook("after_hit")
def on_hit(ctx: Any, target: Any, kind: str) -> None:
    engine, attacker = ctx.engine, ctx.actor
    for caster in _casters(engine):
        if caster.team_id == target.team_id or not marked(target, caster.entity_id):
            continue
        second = ("shatter",) if on_lattice(engine, caster.entity_id, target) else ()
        chosen = _offer(engine, caster, target, "brittle", second=second)
        if chosen:
            _apply(engine, caster, target, chosen)
    from ..attack_notifications import is_melee_hit
    melee = is_melee_hit(ctx)
    for guard in _held(target, GUARD):
        eligible = target.temporary_hp > 0
        if (guard.data or {}).get("grant_sequence"):
            from .temp_hp_grants import grant_at_hit
            grant = grant_at_hit(ctx, target)
            eligible = bool(grant and grant[0] == guard.source_definition_id
                            and grant[1] == guard.data["grant_sequence"])
        if melee and eligible and not (guard.data or {}).get("used"):
            owner = engine.state.actors.get(guard.source_actor_id)
            if owner is not None and (guard.data.get("grant_sequence") or attacker.team_id != owner.team_id):
                from .retained_updates import record_instance_update

                guard.data["used"] = 1  # "the first creature that hits the target"
                record_instance_update(engine, target, "condition", guard.instance_id, guard)
                give_mark(engine, owner, attacker, T + "FROST_SHEATHED_GUARD")
    if melee and _held(target, RIME) and attacker.active:
        rime = _held(target,RIME)[0]
        where = attacker
        if (rime.data or {}).get('auto66'):
            options = {target.entity_id:target,attacker.entity_id:attacker}
            selected = ask(engine,ctx.intent,checkpoint_id(engine,'rime_body_space',target.entity_id,attacker.entity_id),target,
                CHOICE+'rime_body_space',list(options),labels={key:f'Create a Lattice Space under {a.display_name}' for key,a in options.items()},
                allow_decline=True,name='Diamond Rime Body',prompt=f'Diamond Rime Body: {attacker.display_name} hit you in melee. Create a Lattice Space under you or that attacker? No action or resource cost; the space lasts 1 minute.')
            if not selected:
                where = None
            else:
                where = options[selected[0]]
        if where is not None:
            _lattice_at(engine, target, where, T + "DIAMOND_RIME_BODY")
    for edge in _held(attacker, BITTER):
        if kind in ("weapon", "unarmed") and attacker.turn_flags.get("ice_bitter_edge") != attacker.turns_started \
                and engine.state.current_actor_id == attacker.entity_id and target.active:
            data = edge.data or {}
            coated = data.get("strike")
            action = getattr(ctx, "action", None)
            # "You coat one weapon, natural weapon, or unarmed strike": only the coated strike is iced.
            if coated:
                from .weapon_actions import strike_identity

                if strike_identity(action) != str(coated).split('#', 1)[0]:
                    continue
            # "it may deal extra Cold or Piercing damage": the wielder's owner chooses the type.
            dtype = "COLD"
            if coated:
                selected = ask(engine, getattr(engine, "_active_intent", None),
                               checkpoint_id(engine, "bitter_type", attacker.entity_id, target.entity_id), attacker,
                               CHOICE + "bitter_type", ["COLD", "PIERCING"], labels={"COLD": "Cold", "PIERCING": "Piercing"},
                               target_id=target.entity_id, name="Bitter Edge", allow_decline=True,
                               prompt=f"Bitter Edge: {attacker.display_name}'s coated strike hits {target.display_name}. "
                                      f"Deal {int(data.get('pb') or 2)} extra Cold or Piercing damage, or decline? "
                                      "No extra action or CP; declining keeps this turn's use and adds no Fracture Mark. "
                                      "A Fracture Mark on your lattice lets its creator spend it for an Ice response until the end of their next turn.")
                if not selected:
                    continue
                dtype = selected[0]
            attacker.turn_flags["ice_bitter_edge"] = attacker.turns_started
            engine._commit_damage(target, int(data.get("pb") or 2), dtype, T + "BITTER_EDGE", edge.source_actor_id, None, reaction_depth=1)
            owner = engine.state.actors.get(edge.source_actor_id)
            if owner is not None and on_lattice(engine, owner.entity_id, target):
                give_mark(engine, owner, target, T + "BITTER_EDGE")


@hook("attack_bonus")
def crack_aim_attack(ctx: Any, actor: Any) -> int | None:
    engine = ctx.engine
    total = 0
    for caster in _casters(engine):
        if caster.team_id == actor.team_id or not marked(actor, caster.entity_id):
            continue
        weapon = ctx.typed.get("weapon") is not None
        at_us = ctx.target is None or ctx.target.team_id == caster.team_id
        chosen = _offer(engine, caster, actor, "crack", want=at_us, second=("lock",) if weapon else ())
        if chosen:
            cl = int(_row(engine, caster).get("cl", 1))
            total -= _roll(engine, caster, 1, 6 if cl >= 11 else 4, "CRACK_AIM")
            if "lock" in chosen:
                _apply(engine, caster, actor, ["lock"])
    return total or None


@hook("attack_mode")
def lock_grip_mode(ctx: Any, target: Any) -> str | None:
    if _held(ctx.actor, LOCK) and ctx.typed.get("weapon") is not None:
        ctx.engine._remove_condition(ctx.actor, LOCK, BASE)
        return "DISADVANTAGE"
    return None


@hook("save")
def crack_aim_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability).upper()[:3] != "DEX":
        return None
    engine = ctx.engine
    for caster in _casters(engine):
        if caster.team_id == subject.team_id or ctx.actor.team_id != caster.team_id or not marked(subject, caster.entity_id):
            continue
        if _offer(engine, caster, subject, "crack"):
            cl = int(_row(engine, caster).get("cl", 1))
            return {"bonus": -_roll(engine, caster, 1, 6 if cl >= 11 else 4, "CRACK_AIM"), "modes": []}
    return None


@hook("after_miss")
def lock_grip_after(ctx: Any, target: Any) -> None:
    engine, attacker = ctx.engine, ctx.actor
    if ctx.typed.get("weapon") is None:
        return
    for caster in _casters(engine):
        if caster.team_id != attacker.team_id and marked(attacker, caster.entity_id):
            chosen = _offer(engine, caster, attacker, "lock", want=False)
            if chosen:
                _apply(engine, caster, attacker, chosen)


@hook("damage_pending")
def crystal_guard(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    if pending <= 0:
        return None
    for caster in _casters(engine):
        if caster.team_id == target.team_id and marked(target, caster.entity_id):
            chosen = _offer(engine, caster, target, "guard")
            if chosen:
                cut = _apply(engine, caster, target, chosen)
                from .attack_reduction import remember
                return remember(engine, target, pending, max(0, pending - cut), [(cut, ())])
    left = _winter_stores(engine, target, pending)
    return left


def _stored_space_options(engine: Any, caster: Any, target: Any) -> list[tuple[int, int]]:
    """Winter Stores the Blow: "One Lattice Space under or adjacent to the creature gains a stored fracture."

    Both the space it lands under and the single ring beside it qualify. Ordered with the
    creature's own cells first so the printed "under" reading is the default pick.
    """
    lattice = lattice_cells(engine, caster.entity_id)
    under = sorted(_cells_of(engine, target) & lattice)
    beside = sorted((cell for cell in lattice if cell not in under
                     and any(max(abs(cell[0] - x), abs(cell[1] - y)) <= 1 for x, y in _cells_of(engine, target))),
                    key=lambda cell: (min(max(abs(cell[0] - x), abs(cell[1] - y)) for x, y in _cells_of(engine, target)), cell))
    return under + beside


def _nearest_free_cell(engine: Any, actor: Any, cell: tuple[int, int]) -> Any:
    """Nearest legal ground placement, checking the mover's complete footprint.

    Frozen River Reversal: "...returned to the space where the triggering movement began,
    or the nearest unoccupied space if that space is occupied." Returns None when no
    map placement is legal, so the caller can report that no return is possible.
    """
    from ..gate2_runtime_models import Position

    occupied = engine._occupied_cells_except(actor.entity_id)
    footprint = engine._footprint(actor)
    # Deterministic distance/coordinate ordering; search the whole finite map,
    # so an occupied first ring cannot hide a legal placement farther away.
    candidates = sorted((max(abs(x - cell[0]), abs(y - cell[1])), x, y)
                        for x in range(engine.grid.width) for y in range(engine.grid.height))
    for _, x, y in candidates:
        if engine.grid.placement_legal((x, y), footprint=footprint, occupied_cells=occupied):
            return Position(x=x, y=y)
    return None


def _winter_stores(engine: Any, target: Any, pending: int) -> int | None:
    from .. import typed_reactions
    from .d20_rewrite import pool_id


    for caster in _casters(engine):
        found = rows(engine, caster, "winter_stores")
        # "Trigger: A creature you can see takes damage while standing on one of your Lattice Spaces":
        # any visible creature, not only allies.
        if not found or not typed_reactions._can_react(engine, caster):
            continue
        from ..target_knowledge import can_see

        if not on_lattice(engine, caster.entity_id, target) or not can_see(engine, caster, target):
            continue
        cells = _stored_space_options(engine, caster, target)
        cp = pool_id(caster, "cp")
        if not cells or cp is None or caster.resources.get(cp, 0) < 1:
            continue
        intent = getattr(engine, "_active_intent", None)
        reduction = max(0, int(found[0]["pb"]) + int(found[0]["key_mod"]))
        cut = min(pending, reduction)
        from .choice_costs import Payment
        payment = Payment(cp, 1)
        picked = ask(engine, intent, checkpoint_id(engine, "WINTER_STORES", caster.entity_id, target.entity_id), caster,
                     CHOICE + "winter_stores", ["use"], labels={"use": "Winter Stores the Blow (Reaction, 1 CP)"}, allow_decline=True,
                     target_id=target.entity_id, payment=payment, name="Winter Stores the Blow",
                     feature_id=T + "WINTER_STORES_THE_BLOW",
                     prompt=f"Winter Stores the Blow: {target.display_name} takes {pending} damage on your lattice. "
                            f"Spend your Reaction and 1 CP (cultivation point) to reduce it by {cut} "
                            f"(up to {reduction}) and store {cut} extra damage for one Shatter Space or Shatter Bloom "
                            "damage roll before the end of your next turn?")
        if not picked:
            continue
        with activation(engine, caster, T + "WINTER_STORES_THE_BLOW"):
            options = {f"cell:{x},{y}": (x, y) for x, y in cells}
            chosen = ask(engine, intent, checkpoint_id(engine, "WINTER_STORES_SPACE", caster.entity_id, target.entity_id), caster,
                         CHOICE + "winter_stores_space", list(options),
                         labels={key: f"Lattice Space {key.removeprefix('cell:')}" for key in options},
                         target_id=target.entity_id, name="Winter Stores the Blow",
                         feature_id=T + "WINTER_STORES_THE_BLOW",
                         prompt_context={"paying_pool": cp, "cost": "No additional cost; the same Reaction and " + payment.quote()},
                         prompt=f"Winter Stores the Blow: which Lattice Space under or beside {target.display_name} stores the impact? "
                                f"Your next Shatter Space or Shatter Bloom on that space adds {cut} damage to one roll "
                                "against one creature before the end of your next turn. This uses the same Reaction and 1 CP.")
            cell = options[chosen[0]]
            payment.pay(engine, caster, T + "WINTER_STORES_THE_BLOW")
            caster.reaction_available = False
            engine._append_event("REACTION_WINDOW_OPENED", T + "WINTER_STORES_THE_BLOW", actor_id=caster.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "DAMAGE_PENDING"})
            zone = next(z for z in lattice_zones(engine, caster.entity_id)
                        if any((p.x, p.y) == cell for p in z.affected_cells))
            previous = set(caster.conditions)
            engine._apply_condition(caster, STORED, T + "WINTER_STORES_THE_BLOW", caster.entity_id,
                                    expires_on=_token("end", caster),
                                    data={"amount": int(cut), "x": int(cell[0]), "y": int(cell[1]),
                                          "zone_id": str(zone.zone_id)})
            stored_id = next(iid for iid in caster.conditions if iid not in previous
                             and caster.conditions[iid].condition_id == STORED)
            note(engine, T + "WINTER_STORES_THE_BLOW", target, f"Winter Stores the Blow: the lattice stores {cut} of the impact.")
            from .attack_reduction import remember
            return remember(engine, target, pending, pending - cut, [(reduction, ())],
                            feature=f"{STORED}|{caster.entity_id}|{stored_id}", source=T + "WINTER_STORES_THE_BLOW",
                            reactor_id=caster.entity_id)
    return None


@hook("reaction_reduction_carried")
def winter_stores_carried(engine: Any, target: Any, feature: str, amount: int) -> None:
    """A paid attack budget credits only the fracture created by that reaction.

    The existing shared carry hook transports a string receipt containing its
    owner and condition instance. Removed/consumed fractures are never recreated;
    other fractures, owners and reaction budgets remain untouched.
    """
    if not feature.startswith(STORED + "|"):
        return
    _, owner_id, instance_id = feature.split("|", 2)
    caster = engine.state.actors.get(owner_id)
    stored = caster.conditions.get(instance_id) if caster is not None else None
    if stored is None or stored.condition_id != STORED or stored.source_actor_id != owner_id:
        return
    stored.data["amount"] = int(stored.data.get("amount", 0)) + int(amount)
    note(engine, T + "WINTER_STORES_THE_BLOW", target,
         f"Winter Stores the Blow: prevent {amount} more damage to {target.display_name}. "
         f"This lattice space now adds {stored.data['amount']} damage to one roll of "
         f"{caster.display_name}'s next Shatter Space or Shatter Bloom before the end of their next turn. "
         "No further cost.")


@hook("turn_start")
def turn_start(engine: Any, actor: Any) -> None:
    for caster in _casters(engine):
        if caster.team_id == actor.team_id or not marked(actor, caster.entity_id):
            continue
        there = on_lattice(engine, caster.entity_id, actor)
        engaged = any(a.active and a.team_id == caster.team_id and engine._distance_actor_to_actor(a, actor) <= 5 for a in engine.state.actors.values())
        if there:
            chosen = _offer(engine, caster, actor, "shatter", second=("catch",))
        else:
            chosen = _offer(engine, caster, actor, "catch", want=not engaged)
        if chosen:
            _apply(engine, caster, actor, chosen)


@hook("turn_end")
def turn_end(engine: Any, actor: Any) -> None:
    for caster in _casters(engine):
        if caster.team_id != actor.team_id and marked(actor, caster.entity_id) and on_lattice(engine, caster.entity_id, actor):
            chosen = _offer(engine, caster, actor, "shatter")
            if chosen:
                _apply(engine, caster, actor, chosen)


def _moved(engine: Any, mover_id: Any, payload: dict[str, Any]) -> None:
    mover = engine.state.actors.get(str(mover_id or ""))
    if mover is None or not mover.active:
        return
    path = [(int(p["x"]), int(p["y"])) for p in payload.get("path") or [] if isinstance(p, dict)]
    if len(path) < 2:
        return
    steps = len(path) - 1
    feet_step = engine.grid.square_size_ft
    source = str(engine.events[-1].source_definition_id) if engine.events else ""
    for caster in _casters(engine):
        if caster.team_id == mover.team_id:
            continue
        cells = lattice_cells(engine, caster.entity_id)
        across = sum(feet_step for a, b in zip(path, path[1:]) if a in cells or b in cells)
        key = f"ice_lattice_ft:{caster.entity_id}"
        turn = f"{engine.state.round_number}:{engine.state.current_actor_id}"
        seen = str(mover.turn_flags.get(key) or "")
        total = (int(seen.split("|")[1]) if seen.startswith(turn + "|") else 0) + across
        done = seen.endswith("|marked") and seen.startswith(turn + "|")
        mover.turn_flags[key] = f"{turn}|{total}" + ("|marked" if done else "")
        if across and total >= 10 and not done and rows(engine, caster, "crystallize") and not marked(mover, caster.entity_id):
            mover.turn_flags[key] = f"{turn}|{total}|marked"  # "once per creature per turn"
            give_mark(engine, caster, mover, "ICE_BASE_CRYSTALLIZE_PATH")
            _mirror_slick(engine, caster, mover)
        _domain_and_world(engine, caster, mover, path, steps * feet_step)
        returned = _river_reversal(engine, caster, mover, path, bool(payload.get("teleport")))  # its Reaction first: it needs the mark
        # Reversal may return to a fallback cell, so the triggering endpoint is stale.
        if not returned and on_lattice(engine, caster.entity_id, mover) and marked(mover, caster.entity_id) and source != T + "RIME_HOOK":
            chosen = _offer(engine, caster, mover, "shatter", second=("catch",) if engine.state.current_actor_id == mover.entity_id else ())
            if chosen:
                _apply(engine, caster, mover, chosen)
        _white_step(engine, caster, mover, path)


def _mirror_slick(engine: Any, caster: Any, mover: Any) -> None:
    from ..typed_executor import run_effects

    if not rows(engine, caster, "mirror_slick") or any(c.source_actor_id == caster.entity_id for c in _held(mover, SLICK_IMMUNE)):
        return
    speed = engine._effective_speed(mover) if hasattr(engine, "_effective_speed") else 30
    moved = max(0, speed - int(mover.movement_remaining_ft))
    dc = _dc(engine, caster)
    roll = engine._roll_save(mover, "DEX", dc, T + "MIRROR_SLICK_FLOOR", extra_mode="ADVANTAGE" if moved <= speed // 2 else None)
    if roll is not None and int(roll.total) < dc:
        run_effects(_ctx(engine, caster, mover, T + "MIRROR_SLICK_FLOOR", "Mirror-Slick Floor"), [{"type": "condition", "condition": "prone", "applies_to": "target"}])
    else:
        engine._apply_condition(mover, SLICK_IMMUNE, T + "MIRROR_SLICK_FLOOR", caster.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Immune to Mirror-Slick Floor until the start of the Ice cultivator's next turn"})


def _domain_and_world(engine: Any, caster: Any, mover: Any, path: list[tuple[int, int]], feet: int) -> None:
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.active or zone.owner_id != caster.entity_id:
            continue
        feature = _feature(engine, zone.source_definition_id)
        inside = {(c.x, c.y) for c in zone.affected_cells}
        if feature == DOMAIN:
            ft = sum(engine.grid.square_size_ft for a, b in zip(path, path[1:]) if a in inside and b in inside)
            if ft >= 10 and not marked(mover, caster.entity_id):
                give_mark(engine, caster, mover, DOMAIN)  # "a hostile creature that moves at least 10 feet inside the Domain gains a Fracture Mark"
        elif feature == WORLD and feet >= 5 and engine.state.current_actor_id == mover.entity_id \
                and mover.turn_flags.get("ice_world_marked") != mover.turns_started:
            mover.turn_flags["ice_world_marked"] = mover.turns_started  # "the first time each hostile creature moves at least 5 feet on its turn"
            give_mark(engine, caster, mover, WORLD)


def _white_step(engine: Any, caster: Any, mover: Any, path: list[tuple[int, int]]) -> None:
    from .. import typed_reactions

    if not rows(engine, caster, "white_step") or not typed_reactions._can_react(engine, caster):
        return
    reach = 10 // engine.grid.square_size_ft
    start = path[0]
    if not any(max(abs(start[0] - lx), abs(start[1] - ly)) <= reach for lx, ly in lattice_cells(engine, caster.entity_id)):
        return
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "WHITE_STEP", caster.entity_id, mover.entity_id), caster,
                 CHOICE + "white_step", ["use"], labels={"use": "White Step Counter (Reaction): it gains a Fracture Mark"}, allow_decline=True,
                 target_id=mover.entity_id, default="decline" if marked(mover, caster.entity_id) else "first",
                 prompt=f"{mover.display_name} leaves the ground near your lattice: White Step Counter?")
    if not picked:
        return
    with activation(engine, caster, T + "WHITE_STEP_COUNTER"):
        caster.reaction_available = False
        engine._append_event("REACTION_WINDOW_OPENED", T + "WHITE_STEP_COUNTER", actor_id=caster.entity_id, target_ids=(mover.entity_id,),
                             payload={"checkpoint": "MOVED"})
        give_mark(engine, caster, mover, T + "WHITE_STEP_COUNTER")


def _river_reversal(engine: Any, caster: Any, mover: Any, path: list[tuple[int, int]], teleport: bool) -> bool:
    """Return True only when the failed-save return actually moved the creature."""
    from .. import typed_reactions
    from .d20_rewrite import pool_id

    if not rows(engine, caster, "river_reversal") or not marked(mover, caster.entity_id) or not typed_reactions._can_react(engine, caster):
        return False
    cells = lattice_cells(engine, caster.entity_id)
    cp = pool_id(caster, "cp")
    if path[0] not in cells or path[-1] not in cells or path[0] == path[-1] or cp is None or caster.resources.get(cp, 0) < 3:
        return False
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "RIVER_REVERSAL", caster.entity_id, mover.entity_id), caster,
                 CHOICE + "river_reversal", ["use"], labels={"use": "Frozen River Reversal (Reaction, 3 CP)"}, allow_decline=True,
                 target_id=mover.entity_id, name="Frozen River Reversal",
                 prompt=f"Frozen River Reversal: {mover.display_name} {'teleported' if teleport else 'moved'} across your lattice. "
                        f"Spend your Reaction and 3 CP (cultivation points) to require a {'Charisma' if teleport else 'Strength'} save? "
                        "On failure, return it to where it began or the nearest legal unoccupied space. "
                        "On success, its Speed drops by 10 feet until the end of its next turn.")
    if not picked:
        return False
    with activation(engine, caster, T + "FROZEN_RIVER_REVERSAL"):
        engine._spend_resource(caster, cp, 3, T + "FROZEN_RIVER_REVERSAL")
        caster.reaction_available = False
        engine._append_event("REACTION_WINDOW_OPENED", T + "FROZEN_RIVER_REVERSAL", actor_id=caster.entity_id, target_ids=(mover.entity_id,),
                             payload={"checkpoint": "MOVED"})
        dc = _dc(engine, caster)
        roll = engine._roll_save(mover, "CHA" if teleport else "STR", dc, T + "FROZEN_RIVER_REVERSAL")
        if roll is not None and int(roll.total) < dc:
            # "...is returned to the space where the triggering movement began, or the nearest unoccupied space if that space is occupied."
            destination = _nearest_free_cell(engine, mover, path[0])
            if destination is None:
                note(engine, T + "FROZEN_RIVER_REVERSAL", mover,
                     f"Frozen River Reversal: {mover.display_name} fails the save, but no legal unoccupied space is open on this map, so the return does not happen.")
                return False
            here = mover.position
            mover.position = destination
            engine._append_event("MOVEMENT_COMMITTED", T + "FROZEN_RIVER_REVERSAL", actor_id=mover.entity_id,
                                 payload={"destination": destination.model_dump(mode="json"), "path": [here.model_dump(mode="json"), destination.model_dump(mode="json")],
                                          "cost_ft": 0, "forced": True})
            if (destination.x, destination.y) == path[0]:
                note(engine, T + "FROZEN_RIVER_REVERSAL", mover, f"Frozen River Reversal: {mover.display_name} is returned to where it began.")
            else:
                note(engine, T + "FROZEN_RIVER_REVERSAL", mover,
                     f"Frozen River Reversal: where {mover.display_name} began cannot fit it, so it is returned to the nearest legal unoccupied space "
                     f"({destination.x},{destination.y}).")
            return True
        else:
            engine._add_modifier(mover, T + "FROZEN_RIVER_REVERSAL", "speed_ft", "ADD", -10, "SELF", expires_on="END_OF_HOLDER_NEXT_TURN")
        return False


@hook("event")
def ice_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "MOVEMENT_COMMITTED" and not engine.__dict__.get("_ice_in_move"):
        engine.__dict__["_ice_in_move"] = True
        try:
            _moved(engine, kwargs.get("actor_id"), kwargs.get("payload") or {})
        finally:
            engine.__dict__["_ice_in_move"] = False
    elif event_type == "ZONE_REMOVED" or event_type == "CONCENTRATION_ENDED":
        _domain_ended(engine)
    elif event_type == "CONDITION_APPLIED" and str((kwargs.get("payload") or {}).get("condition_id") or "").startswith(_mark_id("")[:-1]):
        _mark_cap(engine, str((kwargs.get("payload") or {}).get("condition_id")))


def _mark_cap(engine: Any, condition_id: str) -> None:
    """"You can maintain a number of Fracture Marks equal to your Proficiency Bonus" (+1 with Nascent Soul: Glacier Soul Takes Shape): a
    new one past the limit ends the oldest."""
    owner = next((a for a in engine.state.actors.values() if _mark_id(a.entity_id) == condition_id), None)
    row = _row(engine, owner) if owner is not None else {}
    if not row:
        return
    cap = int(row.get("pb", 2)) + (1 if rows(engine, owner, "nascent") else 0)
    placed = sorted(((c.applied_sequence, bearer) for bearer in engine.state.actors.values() for c in bearer.conditions.values()
                     if c.condition_id == condition_id), key=lambda r: r[0])
    for _, bearer in placed[:max(0, len(placed) - cap)]:
        engine._remove_condition(bearer, condition_id, BASE)


def _domain_ended(engine: Any) -> None:
    """"When the Domain ends, all temporary Lattice Spaces created by it end.\""""
    from .. import zones

    for zone in list(engine.state.zones.values()):
        ends_with = zone.trigger_profile.get("ends_with")
        if zone.active and ends_with and not (engine.state.zones.get(ends_with) and engine.state.zones[ends_with].active):
            zones.remove(engine, zone, "DOMAIN_ENDED")


# ------------------------------------------------------------------------------------------------ technique-bound conditions
@hook("technique_used")
def ice_used(ctx: Any) -> None:
    source = str(ctx.typed.get("source") or "")
    engine = ctx.engine
    if source == T + "DIAMOND_RIME_BODY":
        owned = any(r.get('auto66') for r in rows(engine,ctx.actor,'diamond_rime'))
        engine._apply_condition(ctx.actor, RIME, source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"label": "Diamond Rime Body: on a melee hit, choose a Lattice Space under you or the attacker" if owned else "Diamond Rime Body: a melee hit puts a Lattice Space under the attacker",
                                      **({'auto66':1} if owned else {})})
    elif source == T + "IMMORTAL_WINTER_CRUCIBLE" and not any(c.data.get("second_pass") for c in _held(ctx.actor, CRUCIBLE)):
        engine._apply_condition(ctx.actor, CRUCIBLE, source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data={"label": "Immortal Winter Crucible: one more Lattice Space each time; a Fracture Mark spent on your turn is free"})
    elif source == T + "CRYSTAL_STEP":
        _crystal_step(engine, ctx.actor)


def _aimed(ctx: Any) -> list[Any]:
    found = [t for t in ctx.targets or [] if t is not None]
    if not found and ctx.intent is not None and ctx.actor.entity_id in (getattr(ctx.intent, "target_ids", ()) or ()):
        found = [ctx.actor]
    return found


def _melee_strikes(engine: Any, holder: Any) -> list[tuple[str, str]]:
    """Eligible weapons / natural / unarmed strikes as (persistent identity, name).

    Bitter Edge: "You coat one weapon, natural weapon, or unarmed strike". Uses the shared
    compiled-weapon query so any character with several strikes is asked which one is iced.
    The historical helper name remains for callers; printed weapons include ranged ones.
    """
    from .weapon_actions import strike_identity, weapon_attacks

    found = {}
    for action, _typed, _attack, _kind in weapon_attacks(list(engine.action_catalog.values()), holder.entity_id):
        found.setdefault(strike_identity(action), str(action.display_name))
    return sorted(found.items(), key=lambda pair: pair[1])


@effect("ice_bitter_edge")
def bitter_edge(ctx: Any, eff: dict[str, Any]) -> None:
    engine = ctx.engine
    intent = getattr(engine, "_active_intent", None)
    for subject in _aimed(ctx) or [ctx.actor]:
        for old in _held(subject, BITTER):
            engine._remove_condition(subject, BITTER, ctx.source)
        pb = int(ctx.numbers.get("pb") or 2)
        strikes = _melee_strikes(engine, subject)
        if not strikes:
            note(engine, ctx.source, subject, f"Bitter Edge: {subject.display_name} has no eligible weapon, natural weapon, or unarmed strike to coat.")
            continue
        data: dict[str, Any] = {"pb": pb}
        if len(strikes) > 1:
            options = {source: name for source, name in strikes}
            picked = ask(engine, intent, checkpoint_id(engine, "bitter_coat", ctx.actor.entity_id, subject.entity_id),
                         ctx.actor, CHOICE + "bitter_coat", list(options),
                         labels={source: f"Coat {name}" for source, name in options.items()},
                         target_id=subject.entity_id, name="Bitter Edge",
                         prompt=f"Bitter Edge: which one of {subject.display_name}'s weapon, natural weapon, or unarmed strikes do you coat "
                                f"with hard ice for 1 minute? Once on each of {subject.display_name}'s turns that strike "
                                "may deal extra Cold or Piercing damage equal to your Proficiency Bonus when it hits a creature. No extra action or CP.")
            if picked:
                data["strike"] = picked[0]
                data["label"] = f"Bitter Edge: {options[picked[0]]} may add {pb} Cold or Piercing damage on a hit once each turn for 1 minute; no extra action or CP"
        elif len(strikes) == 1:
            data["strike"] = strikes[0][0]
            data["label"] = f"Bitter Edge: {strikes[0][1]} may add {pb} Cold or Piercing damage on a hit once each turn for 1 minute; no extra action or CP"
        engine._apply_condition(subject, BITTER, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED",
                                data=data)


@effect("ice_frost_guard")
def frost_guard(ctx: Any, eff: dict[str, Any]) -> None:
    for subject in _aimed(ctx) or [ctx.actor]:
        for old in _held(subject, GUARD):  # "A creature can benefit from only one Frost-Sheathed Guard at a time."
            ctx.engine._remove_condition(subject, GUARD, ctx.source)
        data = {"label": "Frost-Sheathed Guard: the first creature to hit it in melee gains a Fracture Mark"}
        if eff.get("grants_hp"):
            from .temp_hp_grants import held_grant
            amount = int(ctx.numbers.get("pb") or 2) + int(ctx.numbers.get("key_mod") or 0)
            ctx.engine._grant_temp_hp(subject, amount, ctx.source, ctx.actor.entity_id)
            grant = held_grant(ctx.engine.events, subject.entity_id)
            # A rejected equal/lower offer cannot turn another ability's pool
            # into this guard. The previous guard was already replaced above.
            if not grant or grant[0] != ctx.source:
                continue
            data["grant_sequence"] = grant[2]
        ctx.engine._apply_condition(subject, GUARD, ctx.source, ctx.actor.entity_id, expires_on=ctx.expires_on() or "UNTIL_REMOVED", data=data)


@effect("ice_coffin")
def ice_coffin(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor

    dc = int(ctx.numbers.get("save_dc") or 10)
    for subject in ctx.targets or []:
        if subject is None or not subject.active:
            continue
        if eff.get("prison"):
            ctx.engine._apply_condition(subject, C + "restrained", ctx.source, ctx.actor.entity_id,
                                        expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "CONCENTRATION_END",
                                        data={"repeat_save": {"ability": "STR", "dc": dc, "when": "end"}, "label": "Thousand-Facet Prison: Restrained"})
            continue
        ctx.engine._apply_condition(subject, C + "restrained", ctx.source, ctx.actor.entity_id,
                                    expires_on=typed_executor.effect_expiry(ctx, eff, subject, condition=True) or "CONCENTRATION_END",
                                    data={"repeat_save": {"ability": "STR", "dc": dc, "when": "end"}, "ice_coffin": True,
                                          "label": "Ice Coffin: Restrained in a shell of ice (Cover against attacks)"})


@hook("ac")
def coffin_cover(engine: Any, target: Any) -> int | None:
    shelled = any((c.data or {}).get("ice_coffin") for c in _held(target, C + "restrained"))
    return 2 if shelled else None  # "Cover against attacks from outside the shell": Half Cover


@hook("candidate_allowed")
def crystal_step_lattice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Bind Crystal Step's origin and landing in menus and the shared picker.

    Printed: "Teleport from one of your Lattice Spaces you occupy to another
    of your Lattice Spaces ..." A destinationless chooser checks the origin;
    the shared teleport picker checks each concrete landing through this same
    documented hook. Other actions retain their existing admission rules.
    """
    if action is None or _feature(engine, action.source_definition_id) != T + "CRYSTAL_STEP":
        return None
    if not on_lattice(engine, actor.entity_id, actor):
        return False
    destination = candidate.destination
    return destination is None or (destination.x, destination.y) in lattice_cells(engine, actor.entity_id)


@hook("candidate_allowed")
def coffin_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Ice Coffin's target: "One creature with a Fracture Mark that is on or adjacent to one of your Lattice Spaces." """
    if action is None or _feature(engine, action.source_definition_id) != T + "ICE_COFFIN":
        return None
    return all(t in engine.state.actors and marked(engine.state.actors[t], actor.entity_id) and _near_lattice(engine, actor.entity_id, engine.state.actors[t])
               for t in candidate.target_ids or ())


@effect("ice_shatter_bloom")
def shatter_bloom(ctx: Any, eff: dict[str, Any]) -> None:
    engine, caster = ctx.engine, ctx.actor
    pb, cl, key = int(ctx.numbers.get("pb") or 2), int(ctx.numbers.get("cl") or 1), int(ctx.numbers.get("key_mod") or 0)
    reach = 60 // engine.grid.square_size_ft
    here = caster.position
    cells = [c for c in lattice_cells(engine, caster.entity_id) if max(abs(c[0] - here.x), abs(c[1] - here.y)) <= reach]
    foes = [a for a in engine.state.actors.values() if a.active and a.team_id != caster.team_id]

    def near(cell: tuple[int, int], actor: Any) -> bool:
        return any(max(abs(x - cell[0]), abs(y - cell[1])) <= 1 for x, y in _cells_of(engine, actor))

    friends = [a for a in engine.state.actors.values() if a.active and a.team_id == caster.team_id]
    from .needle import CHOICE, ask, checkpoint_id

    ordered = sorted(cells, key=lambda c: (-(sum(near(c, f) for f in foes) - sum(near(c, f) for f in friends)), c))
    options = {f"{x},{y}": (x, y) for x, y in ordered}
    preferred = [key for key, cell in options.items() if any(near(cell, f) for f in foes)][:pb]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BLOOM_SPACES", caster.entity_id), caster,
                 CHOICE + "bloom_spaces", list(options), labels={key: f"Lattice Space ({key})" for key in options},
                 preferred=preferred, minimum=0, maximum=pb, allow_decline=True,
                 prompt=f"Shatter Bloom: {caster.display_name} shatters up to {pb} Lattice Spaces; nearby allies are affected too")
    chosen = [options[key] for key in picked]
    if not chosen:
        return
    picked_type = ask(engine, ctx.intent, checkpoint_id(engine, "BLOOM_TYPE", caster.entity_id), caster,
                      CHOICE + "bloom_type", ["COLD", "PIERCING"], labels={"COLD": "Cold", "PIERCING": "Piercing"},
                      preferred=["COLD"], prompt=f"Shatter Bloom: choose the damage type for creatures beside {caster.display_name}'s chosen spaces")
    damage_type = picked_type[0]
    dc = int(ctx.numbers.get("save_dc") or _dc(engine, caster))
    hit: set[str] = set()
    for cell in chosen:
        for creature in [a for a in engine.state.actors.values() if a.active and near(cell, a) and a.entity_id not in hit]:
            hit.add(creature.entity_id)  # "only one shattering space from this talent each time you use it"
            import dataclasses
            from ..typed_executor import run_effects

            bonus = _take_stored(engine, caster, cell)
            inner = dataclasses.replace(ctx, target=creature, targets=[creature], damage_cache={},
                                        typed={**ctx.typed, "numbers": {**ctx.numbers, "save_dc": dc}})
            run_effects(inner, [{"type": "save", "ability": "DEX", "on_fail": [
                {"type": "damage", "dice": {"count": _shard_dice(cl), "sides": 8},
                 "formula": "key_ability_modifier", "flat": bonus, "damage_types": [damage_type], "applies_to": "target"},
                {"type": "condition", "condition": "prone", "applies_to": "target"}],
                "on_success": [{"type": "half_damage"}]}])
        _end_space(engine, caster.entity_id, cell)
    ctx.rider(f"Shatter Bloom: {len(chosen)} Lattice Space(s) shatter.")


@hook("candidate_allowed")
def shatter_bloom_ready(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or _feature(engine, action.source_definition_id) != T + "SHATTER_BLOOM":
        return None
    reach = 60 // engine.grid.square_size_ft
    cells = [c for c in lattice_cells(engine, actor.entity_id) if max(abs(c[0] - actor.position.x), abs(c[1] - actor.position.y)) <= reach]
    return any(a.active and a.team_id != actor.team_id and any(max(abs(x - cx), abs(y - cy)) <= 1 for x, y in _cells_of(engine, a) for cx, cy in cells)
               for a in engine.state.actors.values())  # only with a hostile creature in or beside one of your Lattice Spaces


def _crystal_step(engine: Any, caster: Any) -> None:
    """Crystal Step: "If you appear adjacent to a creature with a Fracture Mark, you may immediately move that mark to another creature
    within 10 feet of you."

    The donor, the recipient and the whole optional transfer are the owner's decisions
    ("you may immediately move that mark"); the table asks rather than picking the nearest hostile.
    """
    from .needle import cell_id

    intent = getattr(engine, "_active_intent", None)
    beside = [a for a in engine.state.actors.values() if a.active and marked(a, caster.entity_id) and engine._distance_actor_to_actor(a, caster) <= 5]
    if not beside:
        return
    others = [a for a in engine.state.actors.values() if a.active and a.team_id != caster.team_id and a not in beside
              and not marked(a, caster.entity_id) and engine._distance_actor_to_actor(a, caster) <= 10]
    if not others:
        return
    donors = {a.entity_id: a for a in sorted(beside, key=lambda a: a.display_name)}
    chosen_donor = ask(engine, intent, checkpoint_id(engine, "CRYSTAL_STEP_DONOR", caster.entity_id), caster,
                       CHOICE + "crystal_step_donor", list(donors),
                       labels={key: f"{donors[key].display_name}'s Fracture Mark" for key in donors},
                       allow_decline=True, target_id=caster.entity_id, name="Crystal Step",
                       prompt="Crystal Step: after sliding to a new lattice space, you may move one Fracture Mark to another creature "
                              "within 10 feet of you. Move a mark, or decline to keep it where it is?")
    if not chosen_donor:
        return
    donor = donors[chosen_donor[0]]
    recipients = {a.entity_id: a for a in sorted(others, key=lambda a: a.display_name)}
    chosen_recipient = ask(engine, intent, checkpoint_id(engine, "CRYSTAL_STEP_TARGET", caster.entity_id, donor.entity_id), caster,
                           CHOICE + "crystal_step_target", list(recipients),
                           labels={key: f"{recipients[key].display_name} (within 10 feet)" for key in recipients},
                           allow_decline=True, target_id=donor.entity_id, name="Crystal Step",
                           prompt=f"Crystal Step: which creature within 10 feet of you gains {donor.display_name}'s Fracture Mark?")
    if not chosen_recipient:
        return
    recipient = recipients[chosen_recipient[0]]
    engine._remove_condition(donor, _mark_id(caster.entity_id), T + "CRYSTAL_STEP")
    give_mark(engine, caster, recipient, T + "CRYSTAL_STEP")
    note(engine, T + "CRYSTAL_STEP", caster, f"Crystal Step: the Fracture Mark moves from {donor.display_name} to {recipient.display_name}.")


def source_feature(engine, source):
    """Shared compiled source query for ice_second_pass's lifecycle handlers."""
    return _feature(engine, source)


def fracture_numbers(engine, owner):
    """Shared sealed Ice numbers for Ice aftermath and free responses."""
    return dict(_row(engine, owner))


def response_available(engine, owner):
    """Shared pure response-budget query for World-Fang Icefall."""
    return _can_spend(engine, owner, spends_mark=False)


def count_response(engine, owner):
    """Shared response-budget consumption after a chosen free Icefall response."""
    _count_spend(engine, owner, spends_mark=False)


def shatter_response(engine, owner, target, cl, pb, *, at=None):
    """Shared Shatter Space delivery; caller owns mark/payment/limit eligibility."""
    if at is None:
        _shatter(engine, owner, target, cl, pb)
        return
    # Movement-triggered responses resolve at the qualifying path checkpoint,
    # even though the committed movement event already records its final point.
    # Do not emit a second movement event or leave the actor at the checkpoint.
    previous = target.position
    target.position = at
    try:
        _shatter(engine, owner, target, cl, pb)
    finally:
        # Preserve a real nested relocation (such as Rime Hook); otherwise
        # restore the endpoint of the movement that triggered this response.
        if target.position == at:
            target.position = previous
