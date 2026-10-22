"""Soul Warden / Necromancer (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Soul Warden / Necromancer: Soul Fragments, Custody Status, Grave Debt, CL3 Speak with
the Dead, CL6 Soul Harvest, CL10 Raise Specter, CL14 Soul Drain and Death Custody, CL18 Lord of the Dead). No Spheres 5e or D&D 5.5e
counterpart. Ownership row: combat/rules/feature_blocks.d/riders_c8.json (Soul Harvest: the plug-in answers deaths).

Soul Fragments (tradition text): resource:named.soul_fragment, maximum PB (a new resource row). Each fragment's custody status --
Consensual, Unclaimed or Coerced -- is kept on the Warden's turn flags (``fragments``; a "_round_" key the replay records). Grave Debt
(resource:named.grave_debt) is gained where the text says so at the table.

What runs:
  * Soul Harvest (Reaction, 1 Resonance, asked): a creature within 30 feet is defeated (the table's death; summons excluded; one fragment
    per creature). A fallen ally is asked whether it gives the fragment freely (Consensual); a hostile creature known to be 5+ CL below
    you that you damaged cannot resist (Unclaimed); any other unwilling source makes a Charisma save -- failed, a Coerced fragment (and
    1 Grave Debt if it was not hostile); succeeded, none. Fragment Uses (Bonus Action, 1 fragment, you choose which): "Soul Fragment:
    Recover Resonance" (half PB rounded up, once per fight; a Coerced fragment spent this way adds 1 Grave Debt) and "Soul Fragment:
    Mend the Specter" (your specter regains 5 x PB Hit Points).
  * Raise Specter (combat/rules/summons.json, the Predatory Specter summon): Warden or Predatory is a standing free choice ("Choose
    Specter: <kind>", Predatory by default). Predatory -- "Specter: Spectral Strike" (an immediate owner Bonus Action), "Specter: Harrier of the
    Living" (a creature within 10 feet of it: no Reactions and Disadvantage on its next death save before the start of your next turn)
    and "Specter: Drink Fear" (a Frightened or Resonance Marked creature within 10 feet: WIS save; failed, 2d8 Psychic and PB Temporary
    HP for you). Warden -- "Specter: Guard the Threshold" (an ally within 10 feet of it: +2 AC, Half Cover, until the start of your next
    turn) and "Specter: Seize Intruder" (a Resonance Marked creature within 10 feet: CHA save; failed, Speed 0 until the start of your
    next turn). A specter made from a Coerced fragment that is destroyed deals you 2 x PB Psychic.
  * Soul Drain (typed options, Necrotic or Psychic; ``soul_drain``): a Constitution save (Charisma when the target bears your Resonance
    Mark and its Charisma save is better). Failed: 6d8 + Wisdom and no Hit Points regained until the end of its next turn; succeeded: half.
    Capture at the Brink (asked) when it drops a hostile creature to 0: an Unclaimed Soul Fragment without your Reaction, or Death
    Custody (a Dying creature becomes Stable; the rest is the GM's).
  * Lord of the Dead (Action, 10 Resonance + 1 Soul Fragment, a square within 30 feet): a Warden-Wraith object (AC your DC, 12 x PB HP).
    "Warden-Wraith: Warden's Scythe" (Bonus Action: a Cultivation Attack on a creature within 10 feet of it, 4d10 + Wisdom Necrotic,
    Psychic or Radiant -- asked), "Move the Warden-Wraith" (free, once a turn, 50 feet), "Dismiss the Warden-Wraith" (free). Destroyed:
    6d10 Psychic to you that nothing reduces, and no new Wraith this fight.

Plug-in surface: effects soul_drain, soul_fragment_use, soul_specter, soul_wraith; hooks compile_actions, candidate_allowed, event.
Public helpers: ``fragments``, ``gain_fragment``. Shared helpers used: spirit_traditions (context/numbers/feature_action/feature_of/
pick_creature/can_react/save/remove), menus, summons.owned_by, life_state (stabilize), typed_reactions.triggered_context, needle,
typed_executor.
"""

from __future__ import annotations

import math
from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.soul_warden_necromancer.feature."
HARVEST = TRADITION + "soul_harvest"
RAISE = TRADITION + "raise_specter"
DRAIN = TRADITION + "soul_drain_and_death_custody"
LORD = TRADITION + "lord_of_the_dead"
FRAGMENT = "resource:named.soul_fragment"
GRAVE_DEBT = "resource:named.grave_debt"
RESONANCE = "resource:core.resonance"
STATUS_KEY = "soul_fragments_round_"
SPECTER_MENU = "soul_warden.specter"
KINDS = ("Predatory Specter", "Warden Specter")
WRAITH = "object:typed.warden_wraith:"
WRAITH_GONE = "condition:typed.warden_wraith_destroyed"
_PENDING = "_soul_fragment_pending"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _pb(engine: Any, actor: Any) -> int:
    return int(_numbers(engine, actor).get("pb") or 2)


def _cl(engine: Any, creature: Any) -> int | None:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == creature.entity_id), None)
    return int(bundle["cl"]) if bundle and bundle.get("cl") else None


# ---------------------------------------------------------------------------------------------------------- fragments
def fragments(warden: Any) -> list[str]:
    """The custody status of each Soul Fragment the Warden holds (as many as the pool; unknown ones count as Unclaimed)."""
    held = list(warden.turn_flags.get(STATUS_KEY) or [])
    count = int(warden.resources.get(FRAGMENT, 0))
    return (held + ["Unclaimed"] * count)[:count]


def gain_fragment(engine: Any, warden: Any, status: str, source: str) -> bool:
    if FRAGMENT not in warden.resources or warden.resources.get(FRAGMENT, 0) >= warden.resource_maximums.get(FRAGMENT, 0):
        return False  # "subject to your maximum"
    have = fragments(warden)
    engine._gain_resource(warden, FRAGMENT, 1, source)
    warden.turn_flags[STATUS_KEY] = [*have, status]
    return True


def _spend_fragment(engine: Any, warden: Any, source: str, intent: Any, *, ask: bool = True) -> str | None:
    """Spend one fragment (asked which kind when they differ); returns its custody status."""
    from . import needle

    have = fragments(warden)
    if not have:
        return None
    kinds = list(dict.fromkeys(have))
    pick = kinds[0]
    if ask and len(kinds) > 1:
        order = sorted(kinds, key=lambda k: ("Consensual", "Unclaimed", "Coerced").index(k) if k in ("Consensual", "Unclaimed", "Coerced") else 3)
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "SOUL_FRAGMENT", warden.entity_id), warden, "choice:needle.soul_warden.which_fragment",
                            order, labels={k: f"A {k} fragment" for k in order}, preferred=order[:1], prompt="Spend which Soul Fragment?",
                            name="Soul Fragment", feature_id=HARVEST)
        pick = chosen[0] if chosen and chosen[0] in kinds else order[0]
    have.remove(pick)
    warden.turn_flags[STATUS_KEY] = have
    engine.__dict__[_PENDING] = True  # this spend already chose its fragment
    try:
        engine._spend_resource(warden, FRAGMENT, 1, source)
    finally:
        engine.__dict__.pop(_PENDING, None)
    return pick


def _grave_debt(engine: Any, warden: Any, why: str, source: str) -> None:
    if GRAVE_DEBT in warden.resources:
        engine._gain_resource(warden, GRAVE_DEBT, 1, source)
        note(engine, source, warden, f"{warden.display_name} gains 1 Grave Debt ({why}; the GM may rule it necessary).")


# ---------------------------------------------------------------------------------------------------------- Soul Harvest
def can_harvest(engine: Any, warden: Any, fallen: Any) -> bool:
    """Printed ownership, Reaction, Resonance, range, capacity and one-fragment eligibility.

    Shared by the death trigger and its AI benefit query; neither spends here.
    """
    return bool(fallen is not None and fallen.summon is None and warden is not fallen
                and st.row(engine, warden, "soul_harvest") is not None and st.can_react(warden)
                and warden.resources.get(RESONANCE, 0) >= 1 and engine._distance_actor_to_actor(warden, fallen) <= 30
                and warden.resources.get(FRAGMENT, 0) < warden.resource_maximums.get(FRAGMENT, 0)
                and fallen.entity_id not in (warden.turn_flags.get("soul_harvested_round_") or []))


@hook("ai_downed_damage_worthwhile")
def harvest_benefit(engine: Any, actor: Any, candidate: Any, action: Any, targets: tuple[Any, ...]) -> bool | None:
    """Finish two failed saves when the printed ordinary-residue rule supplies a fragment."""
    if st.row(engine, actor, "soul_harvest") is None:
        return None
    return any(can_harvest(engine, actor, target)
               and ordinary_residue(engine, actor, target)
               and int((target.turn_flags.get("life_round_record") or {}).get("bad") or 0) >= 2 for target in targets)


def ordinary_residue(engine: Any, warden: Any, fallen: Any) -> bool:
    """Shared by Soul Harvest's collection and AI benefit query: a damaged hostile at least five levels below."""
    mine, theirs = int(_numbers(engine, warden).get("cl") or 1), _cl(engine, fallen)
    damaged = any(e.event_type == "DAMAGE_COMMITTED" and e.actor_id == warden.entity_id
                  and fallen.entity_id in (e.target_ids or ()) for e in engine.events)
    return fallen.team_id != warden.team_id and theirs is not None and theirs + 5 <= mine and damaged


@hook("event", nested=True)
def soul_harvest(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Trigger: A meaningful creature dies within 30 feet, an undead or spirit is destroyed within 30 feet" (Reaction, 1 Resonance)."""
    from . import needle

    if getattr(engine, "_ext_event_depth", 0) > 1 and engine.state.rules.get("zero_hp") != "dying_2024":
        return

    if event_type == "RESOURCE_SPENT":
        _fragment_spent_by_cost(engine, kwargs)
        return
    if event_type != "ENTITY_DEFEATED":
        return
    fallen = engine.state.actors.get(kwargs.get("actor_id") or "")
    if fallen is None or fallen.summon is not None:
        _specter_destroyed(engine, fallen)
        return  # "You cannot gain fragments from ... allied summons"
    for warden in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not can_harvest(engine, warden, fallen):
            continue
        harvested = list(warden.turn_flags.get("soul_harvested_round_") or [])
        if fallen.entity_id in harvested:
            continue  # "A creature can provide only one fragment to you from the same death"
        if not needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "SOUL_HARVEST", fallen.entity_id), warden, "choice:needle.soul_warden.harvest",
                          ["harvest"], labels={"harvest": f"Soul Harvest (Reaction, 1 Resonance): catch a fragment from {fallen.display_name}"},
                          preferred=["harvest"], allow_decline=True, prompt=f"{fallen.display_name} falls within 30 feet.", name="Soul Harvest",
                          feature_id=HARVEST, target_id=fallen.entity_id):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, warden, HARVEST, independent=True):
            warden.reaction_available = False
            engine._spend_resource(warden, RESONANCE, 1, HARVEST)
            warden.turn_flags["soul_harvested_round_"] = [*harvested, fallen.entity_id]
            engine._append_event("REACTION_RESOLVED", HARVEST, actor_id=warden.entity_id, target_ids=(fallen.entity_id,),
                                 payload={"checkpoint": "CREATURE_DIED", "reaction_name": "Soul Harvest"})
            status = _harvest_status(engine, warden, fallen)
            if status is not None:
                gain_fragment(engine, warden, status, HARVEST)
                if status == "Coerced" and fallen.team_id == warden.team_id:
                    _grave_debt(engine, warden, "a Coerced fragment from a nonhostile creature", HARVEST)
            return


def _harvest_status(engine: Any, warden: Any, fallen: Any) -> str | None:
    from . import needle

    if fallen.team_id == warden.team_id and needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "SOUL_HARVEST_GIVE", fallen.entity_id), fallen,
                                                       "choice:needle.soul_warden.give", ["give"], labels={"give": f"Give {warden.display_name} your fragment freely"},
                                                       preferred=["give"], allow_decline=True, prompt="Soul Harvest", name="Soul Harvest", feature_id=HARVEST):
        return "Consensual"
    if ordinary_residue(engine, warden, fallen):
        return "Unclaimed"  # "cannot prevent collection of ordinary residue"
    sub = st.context(engine, warden, st.feature_action(engine, warden, HARVEST), [fallen], _numbers(engine, warden))
    if st.save(sub, fallen, "cha"):
        return "Coerced"  # "Failed Save: You capture one fragment, not the complete soul."
    note(engine, HARVEST, warden, f"{fallen.display_name}'s soul resists: no fragment (the GM tells you whether it is departing, claimed, reincarnating, concealed or bound).",
         (fallen,))
    return None


def _fragment_spent_by_cost(engine: Any, kwargs: dict[str, Any]) -> None:
    """A fragment paid as a printed cost (Raise Specter, Lord of the Dead) leaves the custody list too; a specter made from a Coerced one
    is remembered."""
    payload = kwargs.get("payload") or {}
    warden = engine.state.actors.get(kwargs.get("actor_id") or "")
    if warden is None or payload.get("resource_id") != FRAGMENT or engine.__dict__.get(_PENDING):
        return
    have = list(warden.turn_flags.get(STATUS_KEY) or [])
    if not have:
        return
    order = sorted(have, key=lambda k: ("Consensual", "Unclaimed", "Coerced").index(k) if k in ("Consensual", "Unclaimed", "Coerced") else 3)
    spent = order[0]
    have.remove(spent)
    warden.turn_flags[STATUS_KEY] = have
    if st.feature_of(engine.action_catalog.get(str(engine.events[-1].source_definition_id if engine.events else ""))) == RAISE:
        warden.turn_flags["specter_coerced_round_"] = spent == "Coerced"


def _specter_destroyed(engine: Any, fallen: Any) -> None:
    """"If created from a Coerced fragment, you take Psychic damage equal to 2 x Proficiency Bonus as the custody breaks.\""""
    if fallen is None or fallen.summon is None or fallen.summon.get("source") != RAISE:
        return
    warden = engine.state.actors.get(str(fallen.summon.get("owner") or ""))
    if warden is not None and warden.active and warden.turn_flags.get("specter_coerced_round_"):
        warden.turn_flags["specter_coerced_round_"] = False
        engine._commit_damage(warden, 2 * _pb(engine, warden), "PSYCHIC", RAISE, warden.entity_id, engine._active_intent, reaction_depth=1)


@effect("soul_fragment_use")
def fragment_use(ctx: Any, row: dict[str, Any]) -> None:
    from .. import summons

    engine, warden = ctx.engine, ctx.actor
    use = row.get("use")
    status = _spend_fragment(engine, warden, HARVEST, ctx.intent)
    if status is None:
        return
    if use == "resonance":
        warden.turn_flags["fragment_resonance_round_"] = True  # "You can do this only once per scene."
        engine._gain_resource(warden, RESONANCE, math.ceil(_pb(engine, warden) / 2), HARVEST)
        if status == "Coerced":
            _grave_debt(engine, warden, "a Coerced fragment consumed for personal recovery", HARVEST)
    else:
        specter = next((c for c in summons.owned_by(engine, warden.entity_id) if c.active and (c.summon or {}).get("source") == RAISE), None)
        if specter is not None:
            _te().run_effects(st.context(engine, warden, ctx.action, [specter], ctx.numbers, ctx.intent),
                              [{"type": "healing", "applies_to": "target", "flat": 5 * _pb(engine, warden), "evidence": "regain Hit Points equal to 5 x Proficiency Bonus"}])


# ---------------------------------------------------------------------------------------------------------- Raise Specter
def specter_of(engine: Any, warden: Any) -> Any:
    from .. import summons

    return next((c for c in summons.owned_by(engine, warden.entity_id) if c.active and (c.summon or {}).get("source") == RAISE), None)


def _kind(engine: Any, warden: Any) -> str:
    from . import menus

    picked = menus.picks(engine, warden, SPECTER_MENU)
    return picked[0] if picked else "Predatory Specter"


@effect("soul_specter")
def specter_expression(ctx: Any, row: dict[str, Any]) -> None:
    engine, warden = ctx.engine, ctx.actor
    mode = row.get("mode")
    target = next(iter(_te()._default_subject(ctx, row, harmful=mode in ("harrier", "drink", "seize", "strike"))), None)
    if target is None or not target.active:
        return
    until = {"kind": "until_start_of_your_next_turn"}
    if mode == "strike":
        specter = specter_of(engine, warden)
        if specter is None:
            return
        from ..action_geometry import activate
        record = {"id": specter.entity_id, "label": "Specter", "position": specter.position.model_dump(mode="json")}
        from . import needle
        damage = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "SPECTRAL_STRIKE", target.entity_id), warden,
            "choice:needle.soul_warden.strike_damage", ["necrotic", "psychic"],
            labels={"necrotic": "Necrotic damage", "psychic": "Psychic damage"}, preferred=["necrotic"],
            prompt=f"Which damage will your Spectral Strike deal to {target.display_name}?", name="Raise Specter", feature_id=RAISE,
            prompt_context={"affected_id": target.entity_id})
        with activate(engine, warden, ctx.source, record):
            _te().run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation", "on_hit": [
                {"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 10},
                 "formula": "key_ability_modifier", "damage_types": [(damage or ["necrotic"])[0]]}]}])
    elif mode == "harrier":
        if target.team_id == warden.team_id:
            from . import needle
            consent = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HARRIER_CONSENT", target.entity_id), target,
                "choice:needle.soul_warden.harrier_consent", ["accept"], labels={"accept": "Accept Harrier of the Living"},
                preferred=[], default="decline", allow_decline=True, automatic_options=[],
                name="Harrier of the Living", feature_id=RAISE,
                prompt=f"Accept Harrier of the Living from {warden.display_name}? You will lose Reactions and have Disadvantage on your next death saving throw.",
                target_id=target.entity_id)
            if not consent:
                return
        _te().run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "cannot take Reactions"},
                                {"type": "disadvantage", "applies_to": "target", "on": "the next death saving throw it makes", "duration": until,
                                 "evidence": "Disadvantage on the next death saving throw it makes before the start of your next turn"}])
    elif mode == "drink":
        if st.save(ctx, target, "wis"):
            _te().run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["psychic"],
                                     "evidence": "it takes 2d8 Psychic damage"}])
            engine._grant_temp_hp(warden, _pb(engine, warden), RAISE, warden.entity_id)  # "you gain Temporary Hit Points equal to your Proficiency Bonus"
    elif mode == "guard":
        engine._apply_condition(target, "condition:typed.specter_cover", ctx.source, warden.entity_id,
            expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Half Cover: +2 AC and Dexterity saves"})
        engine._apply_condition(target, "condition:typed.specter_guard", ctx.source, warden.entity_id,
            expires_on="START_OF_SOURCE_NEXT_TURN", data={"rule": {"save_against": {"mode": "ADVANTAGE",
                "against": ["possession", "soul_displacement"], "abilities": [], "next": True}},
                "label": "Advantage on the next saving throw against possession or soul displacement"})
    elif mode == "seize":
        if st.save(ctx, target, "cha"):
            _te().run_effects(ctx, [{"type": "speed", "applies_to": "target", "becomes": 0, "duration": until, "evidence": "its Speed becomes 0"}])
            engine._apply_condition(target, "condition:typed.specter_seized", ctx.source, warden.entity_id,
                expires_on="START_OF_SOURCE_NEXT_TURN", data={"rule": {"no_possession": True},
                "label": "Cannot possess another creature until the start of the Warden's next turn"})


# ---------------------------------------------------------------------------------------------------------- Soul Drain and Death Custody
@effect("soul_drain")
def soul_drain(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, warden = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active:
        return
    kind = str(row.get("kind") or "necrotic")
    from .creature_kinds import matches
    may_use_charisma = _te().bears_mark(target, warden.entity_id, "Resonance") or matches(target, ["spirit", "incorporeal undead", "possessed"])
    ability = "cha" if may_use_charisma and target.saving_throws.get("CHA", 0) > target.saving_throws.get("CON", 0) else "con"
    damage = {"type": "damage", "applies_to": "target", "pressure_kind": "drain", "dice": {"count": 6, "sides": 8}, "formula": "key_ability_modifier", "damage_types": [kind],
              "evidence": f"The target takes 6d8 + Wisdom modifier {kind.title()} damage"}
    _te().run_effects(ctx, [{"type": "save", "ability": ability, "dc": "technique_save_dc", "applies_to": "target",
                             "on_fail": [{"type": "condition", "condition": "no_cp_regain", "applies_to": "target",
                                                   "duration": {"kind": "until_end_of_next_turn"},
                                                   "condition_data": {"rule": {"no_cp_regain": True}, "label": "Soul Drain: cannot regain Cultivation Points until its next turn ends"},
                                                   "evidence": "Until the end of its next turn, it cannot restore Cultivation Points."}, damage,
                                         {"type": "healing_reduction", "applies_to": "target", "duration": {"kind": "until_end_of_next_turn"},
                                                  "evidence": "Until the end of its next turn, it cannot regain Hit Points"}],
                             "on_success": [{"type": "half_damage", "applies_to": "target", "evidence": "It takes half damage"}],
                             "evidence": "Constitution save; a spirit, incorporeal undead, possessed or Resonance Marked creature uses Charisma if higher."}])
    if target.team_id == warden.team_id or (target.active and target.current_hp > 0):
        return
    # Capture at the Brink: "If Soul Drain reduces a qualifying hostile creature to 0 Hit Points, choose one"
    options = {**({"fragment": "Create one Soul Fragment (Unclaimed) without using your Reaction"} if warden.resources.get(FRAGMENT, 0) < warden.resource_maximums.get(FRAGMENT, 0) else {}),
               "custody": f"Place {target.display_name} under Death Custody (stable at 0 Hit Points until the scene ends)"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "CAPTURE_AT_THE_BRINK", target.entity_id), warden, "choice:needle.soul_warden.brink",
                        list(options), labels=options, preferred=list(options)[:1], allow_decline=True, prompt="Capture at the Brink",
                        name="Soul Drain and Death Custody", feature_id=DRAIN, target_id=target.entity_id)
    if not chosen:
        return
    if chosen[0] == "fragment":
        gain_fragment(engine, warden, "Unclaimed", DRAIN)
        warden.turn_flags["soul_harvested_round_"] = [*(warden.turn_flags.get("soul_harvested_round_") or []), target.entity_id]
    else:
        from . import life_state

        life_state.stabilize(engine, target, DRAIN)
        note(engine, DRAIN, warden, f"{target.display_name} is under Death Custody: it cannot die, depart or be seized by a lower effect before the scene ends "
                                    "(the GM records the outcome you choose).", (target,))


# ---------------------------------------------------------------------------------------------------------- Lord of the Dead
def wraith_of(engine: Any, warden: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id.startswith(WRAITH) and o.owner_id == warden.entity_id and not o.destroyed), None)


def _near(engine: Any, obj: Any, creature: Any, feet: int) -> bool:
    """Within ``feet`` of the Large (10-foot) Wraith: the 2 x 2 squares from the square it was placed on."""
    size = engine.grid.square_size_ft
    return any(min(abs(x - ox) for ox in (obj.position.x, obj.position.x + 1)) <= feet // size
               and min(abs(y - oy) for oy in (obj.position.y, obj.position.y + 1)) <= feet // size for x, y in engine._actor_cells(creature))


@effect("soul_wraith")
def wraith(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState
    from . import needle

    engine, warden = ctx.engine, ctx.actor
    mode = row.get("mode") or "create"
    obj = wraith_of(engine, warden)
    spot = getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
    if mode == "create":
        if spot is None:
            return
        if obj is not None:
            engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "dismissed": True}}), LORD, warden.entity_id)
        numbers = ctx.numbers or _numbers(engine, warden)
        hp = 12 * int(numbers.get("pb") or 2)
        engine._update_object(RuntimeObjectState(object_id=f"{WRAITH}{warden.entity_id}:{engine.state.event_sequence}", object_kind="WARDEN_WRAITH", position=spot,
                                                 unattended=False, flammable=False, owner_id=warden.entity_id, ac=int(numbers.get("save_dc") or 10), current_hp=hp,
                                                 maximum_hp=hp, damage_immunities=("POISON",), component={"label": f"{warden.display_name}'s Warden-Wraith (Large)", "resist": ["PSYCHIC", "NECROTIC", "RADIANT"]}),
                              LORD, warden.entity_id)
        return
    if obj is None:
        return
    if mode == "move":
        warden.turn_flags["wraith_moved"] = True
        if spot is not None:
            engine._update_object(obj.model_copy(update={"position": spot}), LORD, warden.entity_id)
    elif mode == "dismiss":
        engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "dismissed": True}}), LORD, warden.entity_id)
    elif mode == "scythe":
        target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
        if target is None:
            return
        kinds = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "WARDENS_SCYTHE", target.entity_id), warden, "choice:needle.soul_warden.scythe",
                           ["necrotic", "psychic", "radiant"], labels={"necrotic": "Necrotic", "psychic": "Psychic", "radiant": "Radiant"}, preferred=["necrotic"],
                           prompt="Warden's Scythe: damage type?", name="Lord of the Dead", feature_id=LORD)
        _te().run_effects(ctx, [{"type": "attack", "attack_kind": "cultivation_ranged", "count": 1, "applies_to": "target",
                                 "on_hit": [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 10}, "formula": "key_ability_modifier",
                                             "damage_types": [(kinds or ["necrotic"])[0]], "evidence": "4d10 + Wisdom modifier damage"},
                                            {"type": "if_creature_kind", "kinds": ["spirit", "undead"], "effects": [
                                                {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"},
                                                 "evidence": "A spirit or undead hit cannot take Reactions until the start of your next turn."}]}]}])


@hook("event")
def wraith_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If the Warden-Wraith is destroyed, you take 6d10 Psychic damage that ignores Resistance ... You cannot use Lord of the Dead again
    until you complete a Full Cultivation Session.\""""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(WRAITH) or (obj.get("component") or {}).get("dismissed"):
        return
    if not (obj.get("destroyed") or (obj.get("current_hp") is not None and int(obj.get("current_hp") or 0) <= 0)):
        return
    warden = engine.state.actors.get(str(obj.get("owner_id") or ""))
    stored = engine.state.objects.get(str(obj.get("object_id")))
    if stored is not None:
        engine._update_object(stored.model_copy(update={"component": {**(stored.component or {}), "dismissed": True}}), LORD, stored.owner_id)
    if warden is None:
        return
    engine._apply_condition(warden, WRAITH_GONE, LORD, warden.entity_id, expires_on="UNTIL_REMOVED", data={"label": "The Warden-Wraith was destroyed this fight"})
    if not warden.active:
        return
    from ..gate2_runtime_models import DiceSpec

    roll = engine.roller.roll(DiceSpec(count=6, sides=10, modifier=0), actor_id=warden.entity_id, reason=f"DAMAGE:{LORD}")
    engine._record_roll(roll)
    engine.__dict__["_damage_unreduced"] = warden.entity_id
    try:
        engine._commit_damage(warden, int(roll.total), "PSYCHIC", LORD, warden.entity_id, engine._active_intent, reaction_depth=1)
    finally:
        if engine.__dict__.get("_damage_unreduced") == warden.entity_id:
            engine.__dict__.pop("_damage_unreduced", None)


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def warden_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from . import menus

    owned, out = info["owned_ids"], []

    def button(key: str, name: str, economy: Any, target: str, range_ft: int | None, rows: list[dict[str, Any]], text: str, source: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.soul_warden.{key}", display_name=name, owner_id=info["actor_id"], economy=economy,
                                resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": rows},
                                            "expected_damage": 0, "soul_warden": key, "description": text})

    if HARVEST in owned:
        out.append(button("resonance", "Soul Fragment: Recover Resonance", EconomyKind.BONUS_ACTION, "SELF", None, [{"type": "soul_fragment_use", "applies_to": "self", "use": "resonance"}],
                          "Soul Harvest -- Fragment Use (Bonus Action, 1 Soul Fragment, once per fight): recover Resonance equal to half your Proficiency Bonus, rounded up.", HARVEST))
        if RAISE in owned:
            out.append(button("mend", "Soul Fragment: Mend the Specter", EconomyKind.BONUS_ACTION, "SELF", None, [{"type": "soul_fragment_use", "applies_to": "self", "use": "mend"}],
                              "Soul Harvest -- Fragment Use (Bonus Action, 1 Soul Fragment): your specter regains 5 x your Proficiency Bonus Hit Points.", HARVEST))
    if RAISE in owned:
        menu = {"type": "menu", "id": SPECTER_MENU, "name": "Specter", "count": 1, "label": "Choose the specter you raise", "options": list(KINDS),
                "default": ["Predatory Specter"]}
        out.extend(menus.toggle_actions(info, menu, carry=True))
        for key, name, target, text in (("harrier", "Specter: Harrier of the Living", "ANY_CREATURE",
                                         "Predatory Specter (Bonus Action): a creature within 10 feet of it cannot take Reactions and has Disadvantage on its next death saving throw before the start of your next turn."),
                                        ("drink", "Specter: Drink Fear", "HOSTILE_ENTITY",
                                         "Predatory Specter (Bonus Action): a Frightened or Resonance Marked creature within 10 feet of it makes a Wisdom save; failed, it takes 2d8 Psychic damage and you gain Temporary Hit Points equal to your Proficiency Bonus."),
                                        ("guard", "Specter: Guard the Threshold", "ALLY_OR_SELF",
                                         "Warden Specter (Bonus Action): an ally within 10 feet gains Half Cover (+2 AC and Dexterity saves) and Advantage on its next save against possession or soul displacement until the start of your next turn."),
                                        ("seize", "Specter: Seize Intruder", "HOSTILE_ENTITY",
                                         "Warden Specter (Bonus Action): a spirit, incorporeal undead, possessed creature or creature bearing your Resonance Mark within 10 feet makes a Charisma save. On a failure, its Speed becomes 0 and it cannot possess another creature until the start of your next turn.")):
            out.append(button(f"specter.{key}", name, EconomyKind.BONUS_ACTION, target, 1000,
                              [{"type": "soul_specter", "applies_to": "target", "mode": key, **({"harmful": True} if key in ("harrier", "drink", "seize") else {})}], text,
                              RAISE + ":expression"))  # not RAISE itself: the compiler turns an action sourced to a summon feature into the summon
    if LORD in owned:
        out.extend([
            button("scythe", "Warden-Wraith: Warden's Scythe", EconomyKind.BONUS_ACTION, "HOSTILE_ENTITY", 120, [{"type": "soul_wraith", "applies_to": "target", "mode": "scythe", "harmful": True}],
                   "Lord of the Dead (Bonus Action): a Cultivation Attack on a creature within 10 feet of the Warden-Wraith, 4d10 + your Wisdom modifier Necrotic, Psychic or Radiant damage.", LORD),
            button("wraith_move", "Move the Warden-Wraith", EconomyKind.NONE, "SELF", None, [{"type": "soul_wraith", "applies_to": "self", "mode": "move", "picks_destination": True, "distance_ft": 120}],
                   "Lord of the Dead (free, once on each of your turns): the Warden-Wraith moves up to 50 feet.", LORD),
            button("wraith_dismiss", "Dismiss the Warden-Wraith", EconomyKind.NONE, "SELF", None, [{"type": "soul_wraith", "applies_to": "self", "mode": "dismiss"}],
                   "Lord of the Dead (free): the Warden-Wraith departs.", LORD),
        ])
    return out or None


@hook("candidate_allowed")
def warden_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    params = action.parameters or {}
    key = str(params.get("soul_warden") or "")
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    feature = st.feature_of(action)
    if any(isinstance(r, dict) and r.get("type") == "command_summons" and r.get("group") == "predatory_specter"
           for r in ((params.get("typed") or {}).get("effects") or [])) and _kind(engine, actor) != "Predatory Specter":
        return False  # a Warden Specter makes no Spectral Strike
    if feature == LORD and not key:
        return False if any(c.condition_id == WRAITH_GONE and c.source_actor_id == actor.entity_id for c in actor.conditions.values()) else None
    if not key:
        return None
    if key in ("resonance", "mend"):
        if actor.resources.get(FRAGMENT, 0) < 1:
            return False
        if key == "resonance":
            return False if actor.turn_flags.get("fragment_resonance_round_") else None
        return None if specter_of(engine, actor) is not None else False
    if key.startswith("specter."):
        mode = key.split(".", 1)[1].split(".", 1)[0]
        specter = specter_of(engine, actor)
        wanted = "Warden Specter" if mode in ("guard", "seize") else "Predatory Specter"
        if specter is None or _kind(engine, actor) != wanted or target is None or engine._distance_actor_to_actor(specter, target) > (5 if mode == "strike" else 10):
            return False
        from . import ai_controlled
        if mode == "harrier" and target.team_id == actor.team_id and ai_controlled(engine, actor):
            return False
        from ..targeting import line_of_effect
        if not line_of_effect(engine, specter, target=target):
            return False
        if mode == "drink" and not (any(str(c.condition_id).endswith(".frightened") for c in target.conditions.values())
                                    or _te().bears_mark(target, actor.entity_id, "Resonance")):
            return False
        from .creature_kinds import matches
        if mode == "seize" and not (_te().bears_mark(target, actor.entity_id, "Resonance")
                                   or matches(target, ["spirit", "incorporeal undead", "possessed"])):
            return False
        return None
    obj = wraith_of(engine, actor)
    if key.startswith("wraith") or key == "scythe":
        if obj is None:
            return False
        if key == "scythe" and (target is None or not _near(engine, obj, target, 10)):
            return False
        if key == "wraith_move":
            spot = getattr(candidate, "destination", None)
            if actor.turn_flags.get("wraith_moved") or (spot is not None and engine.grid.distance_ft(obj.position, spot) > 50):
                return False
    return None


@hook("compile_action")
def immediate_spectral_strike(action, info):
    """The owner's Bonus Action resolves a strike now, rather than commands a later turn."""
    typed = action.parameters.get("typed") or {}
    if not any(row.get("type") == "command_summons" and row.get("group") == "predatory_specter"
               for row in typed.get("effects", [])):
        return action
    return action.model_copy(update={"display_name": "Specter: Spectral Strike", "target_kind": "HOSTILE_ENTITY",
        "range_ft": 1000, "parameters": {"soul_warden": "specter.strike", "expected_damage": 13,
            "typed": {**typed, "source": RAISE + ":expression", "effects": [
                {"type": "soul_specter", "mode": "strike", "applies_to": "target", "harmful": True}], "riders": []},
            "description": "Bonus Action: your Predatory Specter makes a Cultivation Attack against a creature within 5 feet of it. On a hit, deal 2d10 + Wisdom modifier Necrotic or Psychic damage, your choice."}})


def immediate_specter(engine, specter):
    owner = engine.state.actors.get((specter.summon or {}).get("owner"))
    return owner if owner is not None and any(engine.action_catalog.get(aid) is not None
        and engine.action_catalog[aid].parameters.get("soul_warden") == "specter.strike"
        for aid in owner.action_ids) else None


@hook("summon_turn_policy")
def specter_has_no_turn(engine, actor):
    if (actor.summon or {}).get("source") == RAISE and immediate_specter(engine, actor) is not None:
        return {"skip": True}
    return None


@hook("turn_end")
def specter_end_movement(engine, owner, *, nominal=False):
    if nominal:
        return
    specter = specter_of(engine, owner)
    if specter is None or immediate_specter(engine, specter) is not owner:
        return
    from . import needle, granted_movement
    from ..target_knowledge import located
    # The grant is based on current Speed, including live Speed modifiers.
    speed = int(engine._effective_speed(specter))
    if speed <= 0:
        return
    choices = granted_movement.choices(engine, specter, speed)
    if not choices:
        return
    by_id = {needle.cell_id(c.destination): c for c in choices if c.destination is not None}
    foes = [c for c in engine.state.actors.values() if c.active and c.team_id != owner.team_id and located(engine, owner, c)]
    preferred = sorted(by_id, key=lambda key: (min((engine.grid.distance_ft(by_id[key].destination, f.position)
        for f in foes), default=0), key))[:1] if foes else []
    picked = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "SPECTER_MOVE", specter.entity_id), owner,
        "choice:needle.soul_warden.move", list(by_id), labels={key: "Move specter to " + key[5:] for key in by_id},
        preferred=preferred, default="decline" if not preferred else "first", allow_decline=True,
        prompt=f"Your turn ends. Move your specter up to {speed} feet, or leave it in place.", name="Raise Specter", feature_id=RAISE)
    if picked:
        granted_movement.move(engine, specter, by_id[picked[0]], engine._active_intent, speed, [], name="Raise Specter")


@hook("flight")
def specter_flight(engine, actor):
    if (actor.summon or {}).get("source") == RAISE and immediate_specter(engine, actor) is not None:
        return {"fly_speed_ft": 40, "flight_hover": 1}
    return None


@hook("save_effects")
def guarded_spirit_save(ctx, subject, ability, fail_effects, success_effects, categories):
    if not set(categories) & {"possession", "soul_displacement"}:
        return None
    held = next((c for c in subject.conditions.values() if c.condition_id == "condition:typed.specter_guard"), None)
    if held is None:
        return None
    st.remove(ctx.engine, subject, held, "CONSUMED")
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("effect_allowed")
def seized_cannot_possess(ctx, row):
    limits = {"possession": "no_possession", "incorporeal": "no_incorporeal"}
    if any(c.data.get("rule", {}).get(limits[tag]) for tag in row.get("spiritual_categories", [])
           if tag in limits for c in ctx.actor.conditions.values()):
        return False
    return None


@hook('effect_origins')
def specter_expression_origins(engine, actor, action):
    if action.parameters.get('soul_warden') != 'specter.strike':
        return None
    specter = specter_of(engine, actor)
    return [{'id': specter.entity_id, 'label': 'Specter', 'position': specter.position.model_dump(mode='json')}] if specter else None


@hook('cover')
def specter_half_cover(engine, attacker, target):
    return 2 if target is not None and any(
        c.condition_id == 'condition:typed.specter_cover' for c in target.conditions.values()) else None


@hook('effect_cover')
def specter_effect_cover(engine, source, target, ray):
    return specter_half_cover(engine, source, target)


@hook('save_bonus_details')
def specter_cover_save(engine, target, ability, dc, source_id, intent):
    if ability != 'DEX' or specter_half_cover(engine, None, target) is None:
        return None
    context = engine.d20_context() or {}
    origins = context.get('effect_origin_cells') or []
    if not origins:
        return None
    bonus = engine.cover_from(origins, context.get('source_actor_id'), target)['bonus']
    return {'bonus': bonus, 'contributions': {'cover': bonus}} if bonus else None


@hook('event')
def specter_arrival_has_no_reaction(engine, event_type, kwargs):
    if event_type != 'SUMMON_APPEARED':
        return
    for aid in kwargs.get('target_ids') or ():
        actor = engine.state.actors.get(aid)
        if actor is not None and (actor.summon or {}).get('source') == RAISE and immediate_specter(engine, actor):
            actor.reaction_available = actor.action_available = actor.bonus_action_available = False
            actor.movement_remaining_ft = 0
