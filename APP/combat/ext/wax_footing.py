"""Wax sphere: footing in, and movement through, the wax you made (auto lane AUTO15, round 24).

Rules text (authority/typed_mechanics/rules_text.json, the owner's Wax entries) is the source.

* **Flowing Wax Step** -- "Until the end of your turn, you ignore Difficult Terrain created by wax, mud, snow, shallow
  water, slick stone, or similar yielding surfaces" uses the per-source ``difficult_zone_exempt`` query while its typed
  state lasts, and "If you move through your own Soft Wax this turn, that movement does not provoke Opportunity Attacks from
  creatures standing in that wax" is the ``opportunity_allowed`` query below: a Soft Spread the mover made (a Mold Wax zone
  owned by them) that the reactor stands in forbids that Opportunity Attack while the state runs.
* **Court of Ten Thousand Candles** -- "Allies in the court ignore Difficult Terrain created by your Wax talents." An ally
  standing in a court its owner is running is exempt from the difficult squares of that owner's wax areas (the court itself
  and the owner's Mold Wax forms), through the ``difficult_exempt`` query every area's cost is read from.
* **Molten Snare** -- "When a creature fails a saving throw against Adhesive Pool or Wax Cage, you may spend 1 CP to make the
  wax molten and dragging. Until the start of your next turn, the creature takes fire damage equal to your Proficiency Bonus
  whenever it moves willingly or is moved through the wax." The 1 Cultivation Point is already charged by the combined Wax
  Cage + Molten Snare action, so a failed save under that combination brands the creature until the start of its owner's next
  turn; every later step it takes -- willing or dragged -- burns it for the printed fire damage.
* **Living Wax Form, Set Body** -- "You gain temporary hit points equal to twice your Cultivation Level. **While these
  temporary hit points remain**, you reduce forced movement by 10 feet", through the shared ``forced_movement_reduction``
  query every push and pull reads. A ``forced_movement`` typed row cannot carry it: that row *causes* a push
  (combat/typed_executor.py block_forced_movement only moves a subject other than its caster, and only a positive distance),
  so the printed reduction had to be a plug-in rather than data. "These temporary hit points" are the form's *own* grant, so
  ``set_body_pool`` records that grant (``TEMP_HP_GRANTED`` from this talent) and forgets it again the moment the pool is
  spent or another ability's larger pool replaces it; the reduction then reads that record instead of the aggregate pool.

Hooks used: ``difficult_exempt``, ``opportunity_allowed``, ``after_save`` (the failed save that brands a creature),
``event`` on ``MOVEMENT_COMMITTED`` (which both a willing step and a typed push/drag emit, with the path in its payload),
``event`` on ``TEMP_HP_GRANTED``/``DAMAGE_COMMITTED``/``CONDITION_APPLIED`` (Set Body's own pool) and
``forced_movement_reduction``. Nothing here
runs for a creature that owns no Wax talent: the footing questions ask about the wax an actor owns, the Set Body record is
only written by this talent's own grant, and the branding asks about a compiled combination naming Molten Snare. Shared
helpers used: ``states`` (the printed "for the duration" markers and its ``PREFIX`` state id), ``zones``
(typed_zones/_inside), ``effect_durations`` (the turn tokens Molten Snare uses) and ``spirit_traditions`` (numbers/context).
Persisted values are integers and strings only.

Two scopes the review of this module (AUTO15f1) narrowed, because the printed sentence names who created the terrain and who
is moving through it:

* "Allies in the court ignore Difficult Terrain **created by your Wax talents**". ``difficult_exempt`` can only subtract
  squares from the one merged set ``combat/zones.difficult_cells`` builds, so a square that is also hard to cross for another
  reason (map paint, another owner's area) is left out of the answer here rather than silently exempted.
* "**If you move through your own Soft Wax this turn**, that movement does not provoke Opportunity Attacks from creatures
  standing in that wax". The mover has to be in its own Soft Wax for that movement; without the check, any creature standing
  in the caster's wax lost its strike for the whole turn even while the caster walked about on open ground.

A third scope came out of the AUTO15r1 review, and it is about the pool rather than the ground. "**While these temporary hit
points remain**" names the points *this form* gained, and temporary hit points do not stack: a creature already holding more
than twice its Cultivation Level keeps the larger pool and gains none of the form's, and once the form's points are spent an
unrelated grant must not switch the reduction back on. So the form's own grant is recorded (``SET_BODY_HP``, with the pool it
put there) rather than inferred from ``temporary_hp``, and the record is dropped when that pool is spent or replaced.

Two orderings of that record came out of the AUTO15r2 review:

* The typed row grants the hit points *before* it places the form's own state (the row order is the printed one), so a second
  Set Body inside the first one's minute would record the deadline of the activation that is about to end.
  ``_restamp_set_body_pool`` puts the record back on the new form's clock when the new state lands.
* A fight saved before the record existed carries the form's state and its Temporary Hit Points but nothing saying which
  grant put them there. ``_recorded_set_body_pool`` recovers that from the fight's own recorded Temporary Hit Point grants
  (``temp_hp_grants.held_grant``, the same reader Bark-Back uses), and only when the last grant the creature *accepted* is
  this talent's own -- a smaller or equal offer raises nothing and so leaves that accepted grant standing, which is what a
  recast at a full pool or any other talent's rejected offer looks like in an old save. A save whose pool came from another
  ability, or which never ran this talent, answers 0, so it is never handed a reduction for points the form never granted.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st
from . import states, temp_hp_grants

MOLD_WAX = "TAL_WAX_MOLD_WAX"
COURT = "TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"
COURT_STATE = "wax_court"
STEP = "flowing_wax_step"
WAX_FORM = "TAL_WAX_LIVING_WAX_FORM"
SET_BODY = "living_wax_form_set_body"
SET_BODY_STATE = states.PREFIX + SET_BODY
SET_BODY_HP = "condition:typed.wax_set_body_temp_hp"
SET_BODY_REDUCTION_FT = 10
MOLTEN = "TAL_WAX_MOLTEN_SNARE"
MOLTEN_BURN = "condition:typed.wax_molten_snare"
_MOLTEN_TRIGGERS = ("TAL_WAX_WAX_CAGE", "TAL_WAX_ADHESIVE_POOL")


def _courts(engine: Any, owner: Any) -> list[Any]:
    """The candle courts ``owner`` is running right now."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == owner.entity_id and COURT in str(zone.source_definition_id)]


def _wax_areas(engine: Any, owner: Any) -> list[Any]:
    """The wax areas ``owner`` made: the courts and the Mold Wax forms (Soft Spread / Set Shape)."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine)
            if zone.owner_id == owner.entity_id and (COURT in str(zone.source_definition_id) or MOLD_WAX in str(zone.source_definition_id))]


def _soft_wax(engine: Any, owner: Any) -> list[Any]:
    """The Soft Spread areas ``owner`` made -- the "own Soft Wax" the printed opportunity-attack line names."""
    from .. import zones

    # Persistent profiles keep the base mechanic name; the saved source action
    # retains the selected option. Never infer Soft Wax from every Mold form.
    return [zone for zone in _wax_areas(engine, owner) if MOLD_WAX in str(zone.source_definition_id)
            and "Soft Spread" in str(getattr(engine.action_catalog.get(zone.source_definition_id),
                                             "display_name", "") or zone.trigger_profile.get("name") or "")]


def _running(engine: Any, actor: Any, state_name: str) -> bool:
    return states.active(engine, actor, state_name) is not None


# ----------------------------------------------------------------------------------------------- allies stand easier in a court
def _only_the_wax_is_hard(engine: Any, owner: Any, cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """The part of ``cells`` that nothing but ``owner``'s own wax makes hard to cross.

    ``difficult_exempt`` is a square list, and ``combat/zones.difficult_cells`` merges map paint and every area into one set
    before subtracting it, so the "created by your Wax talents" scope has to be decided here: a square that carries map paint
    or another owner's Difficult Terrain area keeps its cost for the ally as well.
    """
    from .. import zones

    elsewhere: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        if zone.owner_id == owner.entity_id or not zone.trigger_profile.get("difficult"):
            continue
        elsewhere |= {(cell.x, cell.y) for cell in zone.affected_cells}
    costs = getattr(engine.grid, "base_movement_cost", None) or {}
    painted = {cell for cell in cells if int(costs.get(cell) or 1) > 1}
    return cells - elsewhere - painted


@hook("difficult_exempt")
def court_footing(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """"Allies in the court ignore Difficult Terrain created by your Wax talents" (Formations' query, same shape)."""
    from .. import zones

    if not actor.active:
        return None
    for owner_id, owner in sorted(engine.state.actors.items()):
        if owner is actor or not owner.active or not _running(engine, owner, COURT_STATE):
            continue
        if any(actor.team_id == owner.team_id and zones._inside(engine, actor, zone) for zone in _courts(engine, owner)):
            out = _only_the_wax_is_hard(engine, owner, {(cell.x, cell.y) for zone in _wax_areas(engine, owner)
                                                        for cell in zone.affected_cells})
            return out or None
    return None


# -------------------------------------------------------------------------------------- no Opportunity Attack from wax you stand in
@hook("opportunity_allowed")
def soft_wax_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"If you move through your own Soft Wax this turn, that movement does not provoke Opportunity Attacks from creatures
    standing in that wax" (Flowing Wax Step). Both halves of the printed line are checked: the mover is inside its own Soft
    Wax -- it is moving through that wax -- and the creature that would strike is standing in the same wax."""
    from .. import zones

    if not (mover.active and reactor.active and _running(engine, mover, STEP)):
        return None
    wax = _soft_wax(engine, mover)
    if any(zones._inside(engine, mover, zone) and zones._inside(engine, reactor, zone) for zone in wax):
        return False
    return None


@hook("difficult_zone_exempt")
def flowing_surface(engine: Any, actor: Any, zone: Any) -> bool | None:
    """Flowing Wax Step excuses yielding surfaces, including cultivated wax.

    Ask about each source separately: overlapping rubble, thorns or rigid walls
    retain their movement cost. Unlabelled ground is not guessed to be yielding.
    """
    if not _running(engine, actor, STEP):
        return None
    profile = zone.trigger_profile
    words = " ".join([str(profile.get("name") or ""), str((profile.get("visual") or {}).get("material") or ""),
                      *[str(t) for t in profile.get("terrain") or []]]).lower()
    return True if any(word in words for word in ("wax", "mud", "snow", "shallow water", "slick stone", "yielding")) else None


# ----------------------------------------------------------------------------------- Living Wax Form, Set Body: heavy footing
def _set_body_pool(holder: Any) -> int:
    """The Temporary Hit Points Set Body itself put there, or 0 when the pool is not (or is no longer) the form's.

    The record is written by ``set_body_pool`` below from this talent's own ``TEMP_HP_GRANTED``, never from the aggregate
    pool: an unrelated grant must not read as the form's hit points, and a bigger pool the form never replaced is not them.
    """
    row = next((row for row in holder.conditions.values() if row.condition_id == SET_BODY_HP), None)
    return int((row.data or {}).get("amount") or 0) if row is not None else 0


def _recorded_set_body_pool(engine: Any, holder: Any) -> int:
    """The Set Body pool of a fight saved before the record above existed, recovered from the fight's own log.

    Such a save carries the form's state and its Temporary Hit Points but nothing naming the grant that put them there, so
    the record reads nothing and the printed reduction is lost. This asks the recorded Temporary Hit Point grants instead
    -- ``temp_hp_grants.held_grant``, the one reader of whose points a pool is -- and answers only when the LAST grant the
    creature actually accepted is this talent's own. Temporary Hit Points do not stack, so a smaller or equal offer is
    rejected and the creature keeps the grant it already held: reading the newest receipt instead would throw that
    accepted Set Body grant away, and a recast at a full pool adds nothing at all, so the printed reduction would lapse
    mid-fight in exactly the old saves this answers. A save whose pool came from another ability, or which never ran this
    talent, answers 0, so no saved fight is handed a reduction for points the form never granted.
    """
    grant = temp_hp_grants.held_grant(engine.events, holder.entity_id)
    if grant is None or WAX_FORM not in grant[0]:
        return 0
    return int(grant[1])


@hook("forced_movement_reduction")
def set_body_footing(ctx: Any, subject: Any) -> int:
    """"You gain temporary hit points equal to twice your Cultivation Level. **While these temporary hit points remain**, you
    reduce forced movement by 10 feet" (Living Wax Form, Set Body). The reduction runs only for the form's own state, only
    while the Temporary Hit Points *this form* granted are the pool, and only while some of them are left."""
    if subject is None or not subject.active:
        return 0
    if not _running(ctx.engine, subject, SET_BODY):
        return 0
    if not (_set_body_pool(subject) or _recorded_set_body_pool(ctx.engine, subject)):
        return 0
    return SET_BODY_REDUCTION_FT if int(getattr(subject, "temporary_hp", 0) or 0) > 0 else 0


@hook("event")
def set_body_pool(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Which Temporary Hit Points are Set Body's own ("while **these** temporary hit points remain").

    The record is written when this talent's own grant actually puts points in the pool (Temporary Hit Points do not stack,
    so a creature already holding more gains none of the form's and has none of them to hold on to), and dropped again as soon as
    the form's points are no longer what the creature is holding: spent by damage, or replaced by another ability's larger
    pool. An unrelated smaller grant neither creates the record nor keeps it alive on its own.
    """
    if event_type == "CONDITION_APPLIED":
        _restamp_set_body_pool(engine, kwargs)
        return
    if event_type not in ("TEMP_HP_GRANTED", "DAMAGE_COMMITTED"):
        return
    payload = kwargs.get("payload") or {}
    from_form = event_type == "TEMP_HP_GRANTED" and WAX_FORM in str(kwargs.get("source_definition_id") or "")
    grew = int(payload.get("after") or 0) > int(payload.get("before") or 0)
    for tid in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(tid)
        if holder is None or not holder.active:
            continue
        if from_form and holder.entity_id == kwargs.get("actor_id"):
            if not _set_body_pool(holder) and not grew:
                continue  # the form's grant added none of its own points: it has none to hold on to
            _record_set_body_pool(engine, holder, int(payload.get("after") or 0))
        elif grew or int(holder.temporary_hp or 0) <= 0:
            _forget_set_body_pool(engine, holder, "the form's Temporary Hit Points are no longer what it is holding")


def _restamp_set_body_pool(engine: Any, kwargs: dict[str, Any]) -> None:
    """Put the record back on the clock of the Set Body that was just cast.

    The typed row grants the Temporary Hit Points before it places the form's own state (the printed row order), so a second
    Set Body inside the first one's minute records the deadline of the activation that is about to end -- and the 10-foot
    reduction then stops a minute early while the form itself carries on. When the new state lands, move the record onto it.
    """
    payload = kwargs.get("payload") or {}
    if str(payload.get("condition_id") or "") != SET_BODY_STATE or WAX_FORM not in str(kwargs.get("source_definition_id") or ""):
        return
    for tid in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(tid)
        if holder is None or not holder.active:
            continue
        form = states.active(engine, holder, SET_BODY)
        row = next((row for row in holder.conditions.values() if row.condition_id == SET_BODY_HP), None)
        if form is None or row is None or row.expires_on == form.expires_on:
            continue
        amount = int((row.data or {}).get("amount") or 0)
        engine._remove_condition(holder, SET_BODY_HP, WAX_FORM)
        _record_set_body_pool(engine, holder, amount, announce=False)


def _set_body_deadline(engine: Any, holder: Any) -> str:
    """When Set Body's own record ends: with the form, whose printed duration is 1 minute.

    The grant lands before the form's own state row is applied (the row order in the record is the hit points first), so the
    form's clock is read when it is there and the printed one-minute clock otherwise -- the same one the state row itself
    gets, so the record can never outlive the form.
    """
    form = states.active(engine, holder, SET_BODY)
    if form is not None and form.expires_on:
        return str(form.expires_on)
    from .. import typed_executor

    return str(typed_executor.clock_expiry(engine, "one_minute", None) or "UNTIL_REMOVED")


def _record_set_body_pool(engine: Any, holder: Any, amount: int, *, announce: bool = True) -> None:
    """Note that ``amount`` Temporary Hit Points on ``holder`` are the Living Wax Form's own, on the form's own clock."""
    if amount <= 0:
        return
    engine._remove_condition(holder, SET_BODY_HP, WAX_FORM)  # one record: a second Set Body refreshes this one
    engine._apply_condition(holder, SET_BODY_HP, WAX_FORM, holder.entity_id, expires_on=_set_body_deadline(engine, holder),
                            data={"amount": int(amount), "label": f"Living Wax Form: {int(amount)} of your own Temporary Hit "
                                                                   "Points; while they remain you are hard to move"})
    if announce:  # a re-stamped record is the same record, so it does not greet the player twice
        note(engine, WAX_FORM, holder, f"Living Wax Form (Set Body): your own {int(amount)} Temporary Hit Points are holding; "
                                       f"while they remain you reduce forced movement by {SET_BODY_REDUCTION_FT} feet.")


def _forget_set_body_pool(engine: Any, holder: Any, why: str) -> None:
    """Drop the Set Body record: the printed reduction needs *its* points, and these are not them any more."""
    if _set_body_pool(holder):
        engine._remove_condition(holder, SET_BODY_HP, WAX_FORM)
        note(engine, WAX_FORM, holder, f"Living Wax Form (Set Body): {why}, so it no longer reduces forced movement.")


# ---------------------------------------------------------------------------------------------- Molten Snare: the wax that burns
@hook("after_save")
def molten_snare(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """A failed Adhesive Pool or Wax Cage save under the paid Molten Snare combination brands the creature until the start
    of its owner's next turn."""
    engine, owner = ctx.engine, ctx.actor
    from .effect_durations import token

    typed = (getattr(ctx.action, "parameters", None) or {}).get("typed") or {}
    modifiers = [typed.get("modifier")] if isinstance(typed.get("modifier"), dict) else list(typed.get("modifier") or [])
    if not any(str(row.get("id") or "") == MOLTEN for row in modifiers if isinstance(row, dict)):
        return
    source = str(typed.get("source") or "")
    if not failed or subject is None or not subject.active or subject.team_id == owner.team_id:
        return
    if not any(source.startswith(trigger) for trigger in _MOLTEN_TRIGGERS):
        return
    numbers = st.numbers(engine, owner)
    engine._apply_condition(subject, MOLTEN_BURN, ctx.source, owner.entity_id,
                            expires_on=token("start", owner.entity_id, int(owner.turns_started) + 1),
                            data={"label": "Molten Snare: moving through this wax burns it",
                                  "fire_damage": int(numbers.get("pb") or 2)})
    note(engine, MOLTEN, owner, f"Molten Snare: {subject.display_name} is branded by the molten wax; every step it takes burns it.")


@hook("event")
def molten_burn(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Fire damage equal to your Proficiency Bonus for every step the branded creature takes, willing or dragged."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    creature = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if creature is None or not creature.active or len((kwargs.get("payload") or {}).get("path") or []) < 2:
        return
    held = next((row for row in creature.conditions.values()
                 if row.condition_id == MOLTEN_BURN and engine.state.actors.get(row.source_actor_id) is not None
                 and engine.state.actors[row.source_actor_id].active), None)
    if held is None:
        return
    owner = engine.state.actors[held.source_actor_id]
    action = st.feature_action(engine, owner, MOLTEN)
    ctx = st.context(engine, owner, action, [creature], numbers=st.numbers(engine, owner))
    from .. import typed_executor

    typed_executor.run_effects(ctx, [{"type": "damage", "applies_to": "target", "flat": 0, "formula": "pb",
                                      "damage_types": ["fire"],
                                      "evidence": "Molten Snare: fire damage equal to your Proficiency Bonus whenever it moves through the wax"}])
    note(engine, MOLTEN, owner, f"Molten Snare: {creature.display_name} burns for moving through the molten wax.",
         (creature,))
