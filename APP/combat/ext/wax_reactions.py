"""Wax sphere: the two "when a creature hits you" reactions (auto lane AUTO15, round 24).

Rules text (authority/typed_mechanics/rules_text.json, the owner's Wax entries) is the source.

* **Living Wax Form, Wick Body** -- "The first time each round a creature hits you with a melee attack, you may use your
  Reaction to deal fire damage equal to your Proficiency Bonus and shed bright candlelight in a 10-foot radius until the
  start of your next turn." The form is a ``state`` row on the Wick Body option (authority/typed_mechanics/
  reviewed_final.d/review_sw-water.json), so this module asks the owner of a running Wick Body, once per round, whether to
  spend the Reaction; the fire damage lands on the creature that hit them and the candlelight is a short-lived zone on the
  owner. A ranged hit is not a melee hit and does not offer it.
* **Thousand-Faced Wax Sovereign** -- "When a creature hits you with an attack, you may use your Reaction to cause one wax
  false-face to break. The attack still hits, but the attacker becomes impressed by your Wax until the end of your next
  turn." Any attack, melee or ranged, answers it: the printed sentence has no "each round", so this is not once per round the
  way Wick Body is, and the only thing that holds it back is the Reaction itself (spirit_traditions.can_react). The text
  promises no separate per-activation count and no pool of faces to spend, so neither is invented here.

Hooks used: ``hit_final`` (one confirmed hit, with the attack notice (or the declared reach) saying whether it was in
melee). Nothing here
runs for a creature that owns neither talent: both ask first whether the owner has the printed state, and the round
marker is only written when the reaction is actually taken. Shared helpers used: ``states`` (active/condition ids for the
printed "for the duration" states), ``spirit_traditions`` (row/feature_action/context/numbers/can_react), ``needle``
(ask/checkpoint_id) and ``zones``/``gate2_runtime_models`` (the candlelight zone). Nothing stored is a float or an object:
the once-per-round marker is a turn flag holding the round number, the same shape other plug-ins use.

Two clocks the review of this module (AUTO15f1) pinned down, because the printed wording names a creature or a moment the
obvious spelling would file against someone else:

* The wax mark lasts "until the end of **your** next turn" -- *your*, the wax owner's, exactly as printed
  (authority/typed_mechanics/rules_text.json, TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN: "the attacker becomes impressed by
  your Wax until the end of your next turn"). So the clock is the Wax owner's next turn and not the attacker's, which
  would have been the only other candidate: the Sovereign is answered on the attacker's turn, so an attacker clock would
  end the mark before the owner had a turn at all. ``OWNER_TURN`` ("until_end_of_your_next_turn") is the rules table's name
  for the marker's own next turn and the ordinary mark path keeps it (typed_executor.marker_expiry ->
  END_OF_MARKER_NEXT_TURN, swept by typed_executor.expire_marks), so no interception is needed for this mark. The White
  Wax Edict's sentence reads "its next turn" instead -- that *is* the creature it just stopped -- and keeps
  ``HOLDER_TURN``; the two sentences differ on purpose, so neither is spelled the other's way.
* The candlelight lasts "until the start of your next turn". A typed zone ends at its owner's turn start once
  ``round - created_round >= duration_rounds`` (combat/zones.py on_turn_start), so one round is the whole clock *only when
  the owner has already acted this round*; the exact owner-turn deadline below is what makes it the same either way.

Both printed marks are placed by the shared helper wax_edict.impressed, one implementation each: the Edict's is anchored to
the creature it marks (``holder_turn_impression``), this one to the Wax owner (the ordinary marker clock).
"""

from __future__ import annotations

from typing import Any

from . import hook, note
from . import spirit_traditions as st
from . import states
from .needle import ask, checkpoint_id
from .wax_edict import OWNER_TURN, impressed

WAX_FORM = "TAL_WAX_LIVING_WAX_FORM"
WICK_BODY = "living_wax_form_wick_body"
SOVEREIGN = "TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN"
THOUSAND = "thousand_faced_wax_sovereign"
WICK_ROUND = "wax_wick_body_round"
LIGHT_RADIUS_FT = 10


def _light(engine: Any, owner: Any, source: str) -> None:
    """Bright candlelight around ``owner`` until the start of its next turn (a zone, so sight and light read it).

    The clock is the owner's next turn *start*, counted in turns and not in rounds: ``duration_rounds`` is compared against
    the round number (combat/zones.py on_turn_start), so one round is the whole clock only when the owner has already taken
    its turn this round. A hit before the owner's own slot left the light burning through that turn as well. The exact
    owner-turn deadline lives in combat/ext/effect_durations.py (the ``start_of_owner_turn`` zone profile), the start-side
    twin of the ``end_after_owner_turn`` a typed zone already carries.
    """
    from .. import zones
    from ..gate2_runtime_models import Position, ZoneState
    from .effect_durations import next_owner_turn

    zone_id = f"zone:wax:wax_light:{owner.entity_id}:{engine.state.event_sequence + 1}"
    cells = tuple(Position(x=cell[0], y=cell[1]) if isinstance(cell, tuple) else cell
                  for cell in engine.grid.footprint_cells(owner.position, engine._footprint(owner.entity_id)))
    engine.state.zones[zone_id] = ZoneState(
        zone_id=zone_id, source_definition_id=source, owner_id=owner.entity_id, center=owner.position,
        radius_cells=LIGHT_RADIUS_FT // engine.grid.square_size_ft, affected_cells=cells, concentration_link=False,
        duration_rounds=None, created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "name": "Wax Candlelight", "difficult": None,
                         "visual": {"material": "wax", "light": {"radius_ft": LIGHT_RADIUS_FT, "level": "bright"}},
                         "follows_owner": True, "start_of_owner_turn": next_owner_turn(owner),
                         "triggers": [], "inside": [], "numbers": {}})
    engine._append_event("ZONE_CREATED", source, actor_id=owner.entity_id,
                         payload={"zone": engine.state.zones[zone_id].model_dump(mode="json")})
    zones.sync_inside(engine, source)


@hook("hit_final")
def wax_reactions(ctx: Any, target: Any, kind: str) -> None:
    """Both printed reactions to a confirmed hit on the owner (see the module docstring)."""
    engine, attacker, owner = ctx.engine, ctx.actor, target
    if owner is None or not owner.active or attacker is None or attacker is owner:
        return
    notice = getattr(ctx, "attack_notice", None)
    if notice is not None and not notice.hit:
        return
    # A typed attack's context carries no AttackNotice; its own rule for the same question (combat/typed_executor.py
    # block_attack) is the reach it was declared with: none or five feet or less is a melee hit.
    reach = ctx.typed.get("range_ft")
    melee = notice.melee if notice is not None else reach is None or int(reach) <= 5
    wick = states.active(engine, owner, WICK_BODY) is not None and melee
    sovereign = states.active(engine, owner, THOUSAND) is not None
    if not wick and not sovereign:
        return
    if wick and owner.turn_flags.get(WICK_ROUND) == engine.state.round_number:
        wick = False  # "the first time each round"
    if not wick and not sovereign:
        return
    if not st.can_react(owner):
        return
    numbers = st.numbers(engine, owner)
    ability = st.feature_action(engine, owner, WAX_FORM if wick else SOVEREIGN)
    if wick:
        label = "Wick Body: the attacker burns for fire damage equal to your Proficiency Bonus and your wax flares bright"
        prompt = (f"{attacker.display_name} hit {owner.display_name} in melee. Wick Body: spend your Reaction to burn it for "
                  f"{numbers.get('pb', 2)} fire damage?")
        options = [{"type": "damage", "applies_to": "target", "flat": 0, "formula": "pb", "damage_types": ["fire"],
                    "evidence": "Living Wax Form, Wick Body: fire damage equal to your Proficiency Bonus"}]
        name, feature = "Wick Body", WAX_FORM
    else:
        label = "Thousand-Faced Wax Sovereign: one wax false-face breaks and the attacker is impressed by your wax"
        prompt = f"{attacker.display_name} hit {owner.display_name}. Thousand-Faced Wax Sovereign: spend your Reaction to break a false-face?"
        options = impressed(owner, OWNER_TURN)
        name, feature = "Thousand-Faced Wax Sovereign", SOVEREIGN
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, "wax_reaction", ctx.source), owner,
                 "choice:needle.wax_reaction", ["react"],
                 labels={"react": label}, prompt=prompt, allow_decline=True, name=name, feature_id=feature,
                 target_id=attacker.entity_id)
    if not chosen:
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, feature, independent=True):
        owner.reaction_available = False
        st.run_action(engine, owner, ability, attacker, ctx.intent, options)
        if wick:
            owner.turn_flags[WICK_ROUND] = int(engine.state.round_number)
            _light(engine, owner, feature)
        note(engine, feature, owner,
             f"{name}: {attacker.display_name} {'burns' if wick else 'is impressed by your wax'}.",
             (attacker,))
