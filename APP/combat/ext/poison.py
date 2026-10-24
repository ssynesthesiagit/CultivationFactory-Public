"""Poison (rider lane 10, 2026-09-29): Venom-Sovereign Incarnation and its Virulent Presence. Rules text: the owner's Sphere Compendium,
"Poison" (authority/typed_mechanics/rules_text.json). Dose Marks and Toxin Burden stack through combat/ext/stacking_marks.py.

  Venom-Sovereign Incarnation  "Deliver the Dose deals 6d10 Poison or Acid damage instead of its normal damage; your Poison talents ignore
                  ordinary Resistance to Poison and Acid damage." (1 minute; while its Poison immunity from it lasts)
  Virulent Presence  "While Venom-Sovereign Incarnation is active, when an enemy starts its turn within 20 feet of you, it makes a Constitution
                  saving throw. Failed Save: Choose one: 4d8 Poison or Acid damage; Poisoned until the start of its next turn; no Reactions until
                  the start of its next turn; healing halved until the start of its next turn. Successful Save: The enemy takes half of 4d8 ...,
                  or suffers no effect if you chose a non-damaging option. A creature is affected only once per turn." (a standing pick)
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

SOVEREIGN = "tianxia.talent.poison.venom_sovereign_incarnation"
PRESENCE = "tianxia.talent.poison.virulent_presence"
DELIVER = "POISON_BASE_DELIVER_THE_DOSE"
MENU = "poison_virulent_presence"


def _active(actor: Any) -> bool:
    return any(SOVEREIGN in str(m.source_definition_id) for m in actor.modifiers.values()) or \
        any(SOVEREIGN in str(c.source_definition_id) for c in actor.conditions.values())


def _poison_source(source: Any) -> bool:
    text = str(source or "")
    return "POISON_BASE" in text or ".poison." in text


@hook("attack_damage")
def sovereign_dose(ctx: Any, dice: Any) -> Any | None:
    from ..gate2_runtime_models import DiceSpec

    if isinstance(dice, DiceSpec) and DELIVER in str(ctx.source) and _active(ctx.actor):
        return DiceSpec(count=6, sides=10, modifier=dice.modifier)
    return None


@hook("resistance_ignored")
def sovereign_pierces(engine: Any, kind: str, typed: Any, source_actor_id: Any, target: Any = None) -> bool | None:
    actor = engine.state.actors.get(str(source_actor_id or ""))
    if actor is None or str(kind).upper() not in ("POISON", "ACID") or not _active(actor):
        return None
    source = next((action_id for action_id in actor.action_ids if action_id in engine.action_catalog
                   and ((engine.action_catalog[action_id].parameters or {}).get("typed")) is typed), None)
    return True if _poison_source(source) else None


@hook("turn_start")
def virulent_presence(engine: Any, actor: Any) -> None:
    from . import menus
    from .rider_choices import pick, intent_for
    from ..typed_executor import Context, run_effects

    if not actor.active:
        return
    for sovereign in engine.state.actors.values():
        if not sovereign.active or sovereign.team_id == actor.team_id or not _active(sovereign):
            continue
        rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(sovereign.entity_id, [])
        if not any(str(row.get("feature_id") or "") == PRESENCE for row in rows) or engine.grid.distance_ft(sovereign.position, actor.position) > 20:
            continue
        action = engine.action_catalog.get(next((a for a in sovereign.action_ids if SOVEREIGN in a), ""))
        if action is None:
            continue
        picked = pick(engine, sovereign, MENU, "Virulent Presence (Poison)",
                      ["4d8 damage", "Poisoned", "No Reactions", "Healing halved"], subject=actor,
                      trigger=f"{actor.display_name} starts its turn", optional=False,
                      preferred=menus.picks(engine, sovereign, MENU) or ["4d8 damage"])[0]
        damage = {"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["poison", "acid"]}
        fail = {"4d8 damage": [damage],
                "Poisoned": [{"type": "condition", "applies_to": "target", "condition": "poisoned", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                "No Reactions": [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}],
                "Healing halved": [{"type": "healing_reduction", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN",
                                    "evidence": "healing the enemy receives is halved"}]}.get(picked, [])
        success = [{"type": "half_damage"}] if picked == "4d8 damage" else []
        note(engine, f"passive:{PRESENCE}", sovereign, f"Virulent Presence: {actor.display_name} starts its turn near {sovereign.display_name}.", (actor.entity_id,))
        typed = dict((action.parameters or {}).get("typed") or {})
        run_effects(Context(engine, sovereign, action, intent_for(engine), typed, [actor], actor, {}),
                    [{"type": "save", "ability": "con", "on_fail": fail, "on_success": success}])


@hook("compile_block")
def poison_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "poison":
        return None
    result = {**row, "block": "poison", "kind": spec.get("kind"), 'numbers': dict(numbers),
              'choice_owner': True}
    if spec.get('hit_delivery_policy') == 1:
        result['hit_delivery_policy'] = 1
    return [result]


DEEPEN = "tianxia.talent.poison.deepen_the_burden"


@hook("compile_actions")
def deepen_action(info: dict[str, Any]) -> list[Any] | None:
    """Deepen the Burden: "When a creature has at least 2 Dose Marks from you, you may spend 1 CP and convert 2 Dose Marks into 1 Toxin Burden.
    The target makes a Constitution saving throw. Failed Save: The Toxin Burden remains until the target finishes a long rest ... Successful
    Save: The Dose Marks are spent, but the Toxin Burden fades at the end of the current scene." -- no Action (none is printed), against a
    creature within Deliver the Dose's 60 feet carrying two of your Dose Marks (combat/ext/stacking_marks.py); a scene is the fight."""
    if DEEPEN not in (info.get("owned_ids") or ()):
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    effects = [{"type": "spend_mark", "mark": "Dose Mark", "count": 2, "applies_to": "target"},
               {"type": "save", "ability": "con", "on_fail": [{"type": "mark", "mark": "Toxin Burden", "applies_to": "target", "duration": {"kind": "until_removed"}}],
                "on_success": [{"type": "mark", "mark": "Toxin Burden", "applies_to": "target", "duration": {"kind": "until_removed"}}]}]
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.poison_deepen_the_burden", display_name="Deepen the Burden",
                             owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
                             costs=((pool, 1),),
                             parameters={"typed": {"source": DEEPEN, "effects": effects, "numbers": info.get("numbers") or {}, "duration": {"kind": "instant"}, "riders": []},
                                         "expected_damage": 0,
                                         "description": "Convert 2 of your Dose Marks on a creature into 1 Toxin Burden (1 CP, no Action)."})]


MIASMA = 'tianxia.talent.poison.miasma_form'
STRIKE = 'tianxia.talent.poison.venomous_strike'
NEXT_CHECK = 'condition:typed.poison_next_check'


def miasma_active(actor):
    return actor.active and actor.concentration is not None and MIASMA in actor.concentration.source_definition_id and any(MIASMA in str(item.source_definition_id)
        for item in [*actor.conditions.values(), *actor.modifiers.values()])


def owned_row(engine, actor, kind):
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, 'poison', kind)


def turn_stamp(engine):
    return int(engine.state.round_number) * 1000 + int(engine.state.current_slot_index)


@hook('flight')
def venom_flight(engine, actor):
    if not actor.active:
        return None
    speed = 40 if _active(actor) else 30 if miasma_active(actor) else 0
    return {'fly_speed_ft': speed, 'flight_hover': 1} if speed else None


PHYSICAL_DAMAGE = frozenset({'BLUDGEONING', 'PIERCING', 'SLASHING'})


@hook('damage_defenses')
def miasma_physical_resistance(engine, target, damage_type, typed, source_actor_id):
    from ..zone_sources import mundane_rows
    if not miasma_active(target) or str(damage_type).upper() not in PHYSICAL_DAMAGE:
        return None
    if mundane_rows(typed.get('effects') or [], typed.get('mundane')) is True:
        return [{'kind': 'resistance', 'damage_types': [str(damage_type).upper()]}]
    return None  # unknown provenance is never invented from a physical type


@hook('defense_description')
def miasma_physical_description(engine, target):
    """Miasma Form's Resistance to nonmagical physical damage, as the Defences card names it.

    Same Miasma gate the damage hook reads. Whether the damage was nonmagical is read from the
    packet combat carries, which the card has none of, so it reads as a plain qualifier. Pure: the card never
    pays the Stamina upkeep or ends the concentration."""
    if not miasma_active(target):
        return None
    return [{'feature_id': MIASMA, 'damage_types': sorted(PHYSICAL_DAMAGE),
             'note': 'only against nonmagical damage'}]


@hook('escape_mode')
def miasma_escape(engine, actor, grips):
    return 'ADVANTAGE' if miasma_active(actor) else None


@effect('poison_next_check')
def next_check(ctx, spec):
    if ctx.target is None:
        return
    from ..typed_executor import condition_save_data, effect_expiry
    deadline = ctx.target.display_name if spec.get('expires_on') == 'START_OF_TARGET_NEXT_TURN' else ctx.actor.display_name
    ctx.engine._apply_condition(ctx.target, NEXT_CHECK, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, {**spec, 'expires_on': spec.get('expires_on', 'START_OF_SOURCE_NEXT_TURN')}, ctx.target, condition=True),
        data={**condition_save_data(ctx, spec), 'rule': {'check_mode': {'ALL': 'DISADVANTAGE'}},
              'label': f'Poison: Disadvantage on the next ability check before {deadline} starts their next turn'})


@hook('event')
def spend_next_check(engine, event_type, kwargs):
    if event_type != 'CHECK_ROLLED' or (kwargs.get('payload') or {}).get('by_sense'):
        return
    actor = engine.state.actors.get(kwargs.get('actor_id') or '')
    if actor is None:
        return
    from .condition_ownership import remove_instance
    for instance in list(actor.conditions.values()):
        if instance.condition_id == NEXT_CHECK:
            remove_instance(engine, actor, instance.instance_id, instance.source_definition_id)
    from .benefit_suppression import consume_suppressed_conditions
    consume_suppressed_conditions(engine, actor, NEXT_CHECK)


@effect('poison_delivery_save', forge_rejection=(
    "Deliver the Dose needs its own hit and Constitution save to grant a Dose Mark "
    "and next-check Disadvantage; a forged delivery cannot carry those consequences."))
def delivery_save(ctx, spec):
    """Only one actual hit each turn invokes Deliver's Constitution save."""
    from ..typed_executor import run_effects
    if ctx.typed.get('source') != DELIVER or ctx.target is None:
        return
    stamp = turn_stamp(ctx.engine)
    if ctx.actor.turn_flags.get('poison_delivery_save_turn') == stamp:
        return
    ctx.actor.turn_flags['poison_delivery_save_turn'] = stamp
    ctx.damage_cache['_poison_delivery_save'] = 1
    try:
        run_effects(ctx, spec.get('effects') or [])
    finally:
        ctx.damage_cache.pop('_poison_delivery_save', None)


@hook('save_final')
def dose_followups(ctx, target, ability, named, failed):
    """Owned Numbing/Paralytic choices use the actual final delivery save."""
    if ctx.typed.get('source') != DELIVER or not ctx.damage_cache.get('_poison_delivery_save') or not target.active:
        return
    from dataclasses import replace
    from ..typed_executor import run_effects
    for kind in ('numbing', 'paralytic'):
        row = owned_row(ctx.engine, ctx.actor, kind)
        if row and row.get('spec'):
            run_effects(replace(ctx, target=target, targets=[target]),
                [{**row['spec'], 'failed': int(failed), 'kind': kind}])


@hook('compile_actions')
def seal_dose_specs(info):
    """Carry reviewed branches into the owned row of the saved bundle."""
    from copy import deepcopy
    for row in info.get('passives') or []:
        if row.get('block') == 'poison' and row.get('kind') in {'numbing', 'paralytic'}:
            effects = (info['mechanics'].get(row['feature_id']) or {}).get('effects') or []
            spec = next((e for e in effects if e.get('type') == 'poison_dose_followup'), None)
            if spec:
                row['spec'] = deepcopy(spec)


@effect('poison_dose_followup')
def dose_followup(ctx, spec):
    from dataclasses import replace
    from .choice_costs import payable
    from .d20_rewrite import pool_id
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import run_effects
    kind, target = spec.get('kind'), ctx.target
    row = owned_row(ctx.engine, ctx.actor, kind)
    if row is None or target is None or not ctx.damage_cache.get('_poison_delivery_save') or ctx.typed.get('source') != DELIVER:
        return
    failed = bool(spec.get('failed'))
    effects = spec.get('on_fail' if failed else 'on_success') or []
    pool = pool_id(ctx.actor, 'cp')
    if not effects or pool is None:
        return
    delivery_paid = False
    for event in reversed(ctx.engine.events):
        if event.event_type == 'INTENT_ACCEPTED':
            break
        if (event.event_type == 'RESOURCE_SPENT' and event.actor_id == ctx.actor.entity_id
                and event.source_definition_id == ctx.action.source_definition_id
                and event.payload.get('resource_id') == pool and event.payload.get('amount', 0) > 0):
            delivery_paid = True
    price = max(1, int(spec['cost_cp']) - (int(spec.get('paid_delivery_discount', 0)) if delivery_paid else 0))
    payment = payable(ctx.actor, pool, price)
    if payment is None:
        return
    name, details = spec['name'], spec['failed_label' if failed else 'success_label']
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'poison_' + kind, target.entity_id),
        ctx.actor, CHOICE + 'poison_' + kind, ['APPLY'], allow_decline=True, target_id=target.entity_id,
        name=name, feature_id=row['feature_id'], payment=payment,
        labels={'APPLY': f'{details} until your next turn starts'},
        prompt=f'{name}: {target.display_name} {"failed" if failed else "succeeded on"} the Deliver the Dose save. Spend {payment.quote()} for {details} until your next turn starts?')
    if chosen:
        payment.pay(ctx.engine, ctx.actor, row['feature_id'])
        run_effects(replace(ctx, effect_source=row['feature_id']), effects)


@hook('after_hit_choice')
def venomous_strike(ctx, target, kind):
    """Printed hits, with expanded provenance sealed into new owned bundles."""
    row = owned_row(ctx.engine, ctx.actor, 'strike')
    if row is None or target is None or not target.active:
        return
    delivery = ctx.typed.get('source') == DELIVER
    if not delivery and row.get('hit_delivery_policy') == 1:
        from .weapon_hits import weapon_identity
        coat = _coating(ctx.actor)
        physical = weapon_identity(ctx)
        delivery = bool(kind in ('weapon', 'unarmed', 'natural') and coat is not None
                        and physical == (coat.data or {}).get('weapon'))
        # Natural weapons are a separately printed trigger. The compiler's
        # canonical physical identity distinguishes them from plain unarmed
        # packets, including when a technique delivers that same weapon.
        delivery = delivery or (kind in ('weapon', 'unarmed', 'natural') and '.natural.' in physical)
        # The attack's own sealed source must identify Poison cultivation. A
        # Poison owner holding an ordinary fist, or an unrelated Acid attack,
        # does not carry Poison cultivation merely by knowing this talent.
        delivery = delivery or (kind in ('unarmed', 'natural') and
                                any(_poison_source(ctx.typed.get(key)) for key in ('source', 'forged_from')))
    if not delivery:
        return
    stamp = turn_stamp(ctx.engine)
    if ctx.actor.turn_flags.get('poison_strike_turn') == stamp:
        return
    from dataclasses import replace
    from .choice_costs import payable
    from .d20_rewrite import pool_id
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import run_effects
    pool = pool_id(ctx.actor, 'cp')
    payment = payable(ctx.actor, pool, 1) if pool else None
    if payment is None:
        return
    count = 3 if int(ctx.numbers.get('cl') or 1) >= 15 else 2 if int(ctx.numbers.get('cl') or 1) >= 10 else 1
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'venomous_strike', target.entity_id),
        ctx.actor, CHOICE + 'venomous_strike', ['STRIKE'], allow_decline=True, target_id=target.entity_id,
        name='Venomous Strike', feature_id=STRIKE, payment=payment,
        labels={'STRIKE': f'+{count}d6 Poison or Acid damage and a Constitution save'},
        prompt=f'Venomous Strike: {ctx.action.display_name} hits {target.display_name}. Spend {payment.quote()} to add {count}d6 Poison or Acid damage and force a Constitution save? On a failure, the target is Poisoned until its next turn starts; on a success, its next ability check before then has Disadvantage. Once per turn.')
    if not picked:
        return
    payment.pay(ctx.engine, ctx.actor, STRIKE)
    ctx.actor.turn_flags['poison_strike_turn'] = stamp
    sub = replace(ctx, target=target, targets=[target], typed={**ctx.typed, 'source': STRIKE}, effect_source=STRIKE)
    run_effects(sub, [{'type': 'damage', 'dice': {'count': count, 'sides': 6}, 'damage_types': ['poison', 'acid'], 'applies_to': 'target'},
        {'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
         'on_success': [{'type': 'poison_next_check', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}])



# ---------------------------------------------------------------------------
# AUTO123: the printed combat clauses the ported AUTO44 work left open. Every one is an owned Poison row resolved through the
# documented seams only -- compile_actions for a printed economy and price, after_hit for a hit rider, after_hit_choice for an
# optional paid rider, save_bonus for a printed disadvantage and after_save_resolved for a save-success reward. No new core
# seam, no lock file, and each hook returns early unless the actor owns the row.
COATED = 'tianxia.talent.poison.coated_weapon'
WOUND = 'tianxia.talent.poison.venom_in_the_wound'
BODY = 'tianxia.talent.poison.venom_body_method'
THOUSAND = 'tianxia.talent.poison.thousand_poison_immunity'
COATING = 'condition:typed.poison_coating'
# blood_riders.blood_actions grants this action only to Blood sphere owners.
BLOOD_ACTION = '.blood_thread_willing'
# "a Toxin Effect" is a source-bound affliction. Only a save whose own condition set names a toxin is a poison save; an
# unrelated save (Stun, Fear, a plain Concentration save) never pays a toxin rider out.
TOXIN_NAMES = ('poisoned', 'toxineffect', 'ingrainedtoxin', 'toxinburden', 'meridianvenom', 'daovenom', 'venom', 'poison')
# Venom Body Method's "Once per round" and Thousand-Poison Immunity's "Once per short rest". Both are kept in the engine's
# turn-flag clock under its "once_per_round:" namespace, the documented set of keys that _system_start_turn retains (it
# clears the per-turn namespaces and keeps only "_round_" keys and "once_per_round:" ones), so neither limit silently
# becomes available again at the start of the owner's next turn. Body's holds the round it last paid in; Thousand's holds
# "spent" once the optional use is taken -- a fight contains no short rest to refresh it.
BODY_ROUND_KEY = "once_per_round:poison_body_temp_hp"
THOUSAND_KEY = "once_per_round:poison_thousand_temp_hp"


def _owns(engine: Any, actor: Any, feature_id: str) -> bool:
    """Ownership through the repository's one shared query (ext/fight_ownership.owns_feature), so a passive Poison row is
    recognised in every recorded form -- passive id, compiled row, or an action's typed source."""
    from .fight_ownership import owns_feature
    return owns_feature(engine, actor, feature_id)


def _coating(actor: Any) -> Any | None:
    return next((c for c in actor.conditions.values() if c.condition_id == COATING), None)


def _clear_coating(engine: Any, actor: Any, source: str) -> None:
    from .condition_ownership import remove_instance
    for iid, row in list(actor.conditions.items()):
        if row.condition_id == COATING:
            remove_instance(engine, actor, iid, source)


def _poison_save(ctx: Any, named: Any) -> bool:
    """True only for a save actually made against poison or a Toxin Effect."""
    for name in set(named or ()):
        slug = str(name).lower().replace(' ', '').replace('_', '')
        if any(word in slug for word in TOXIN_NAMES):
            return True
    source = f"{ctx.typed.get('source') or ''} {getattr(ctx.action, 'source_definition_id', '') or ''}".lower()
    return 'poison' in source


@hook('compile_actions')
def coated_weapon_action(info: dict[str, Any]) -> list[Any] | None:
    """Coated Weapon -- "Action Type: Bonus Action / Range: Touch / Target: One weapon, natural weapon, unarmed strike, or set
    of up to 10 pieces of ammunition / Duration: 1 minute / Cost: 1 CP. You coat the target with venom ... The coating ends
    after 1 minute or after it has applied a Dose Mark a number of times equal to your Proficiency Bonus."

    The coat lives on the owner as a tracked condition carrying the printed charge count and the printed 1-minute deadline
    (ten rounds), so neither half of that sentence can last the rest of the fight by accident.
    """
    if COATED not in (info.get('owned_ids') or ()):
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    pool = RESOURCE_IDS.get(str(info.get('primary') or 'qi'), 'resource:core.qi')
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.poison_coat_weapon", display_name="Coat a Weapon",
                             owner_id=info['actor_id'], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED",
                             target_kind="SELF", range_ft=0, costs=((pool, 1),),
                             parameters={"typed": {"source": COATED, "effects": [{"type": "poison_coating", "applies_to": "self"}],
                                                  "numbers": info.get('numbers') or {}, "duration": {"kind": "minutes", "amount": 1},
                                                  "riders": []},
                                         "expected_damage": 0,
                                         "description": "Coat a weapon you hold with venom for 1 minute (1 CP, Bonus Action). Once per turn, a hit with the coated weapon adds Poison or Acid damage equal to your Proficiency Bonus and forces a Constitution save."})]


@effect('poison_coating')
def apply_coating(ctx: Any, spec: dict[str, Any]) -> None:
    """Printed target: "One weapon, natural weapon, unarmed strike, or set of up to 10 pieces of ammunition" -- so the coated
    item is named by whoever holds it, and a caster with more than one thing in hand is asked which one gets the venom. Only
    the items actually held are offered, and the coating is bound to that item's identity for the hit rider below."""
    from .needle import ask, checkpoint_id, CHOICE
    from .weapon_hits import available_weapons
    me = ctx.actor
    held = available_weapons(ctx.engine, me)
    options = sorted(held)
    if not options:
        ctx.rider("Coated Weapon: you hold no weapon, natural weapon or unarmed strike to coat.")
        return
    picked = options[0]
    if len(options) > 1:
        # ask() answers with the chosen ids as a list; an empty answer (an automatic actor that declines to choose) keeps
        # the first item rather than inventing one.
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'POISON_COATED_WEAPON', me.entity_id),
            me, CHOICE + 'poison_coated_weapon', options, allow_decline=False, name='Coated Weapon', feature_id=COATED,
            labels={key: held[key].display_name for key in options},
            prompt='Coated Weapon: which weapon, natural weapon or unarmed strike do you coat with venom for 1 minute?')
        picked = list(chosen)[0] if chosen else picked
    _clear_coating(ctx.engine, me, ctx.source)
    charges = max(1, int(ctx.numbers.get('pb') or 2))
    ctx.engine._apply_condition(me, COATING, ctx.source, me.entity_id,
        expires_on=f"END_OF_SOURCE_TURN_AT:{int(me.turns_started) + 10}",  # "1 minute": ten rounds of the owner's own turns
        data={'weapon': picked, 'charges': charges, 'printed_charges': charges, 'weapon_name': held[picked].display_name,
              'label': _coat_label(held[picked].display_name, charges)})


def _coat_label(item_name: str, charges: int) -> str:
    """The pill the sheet shows. It states the printed frequency (once per turn, not "each hit this turn"), what the
    venom does, what a Dose Mark is and what it leads to, the remaining charges after every application, and the
    1-minute lifetime -- the same explanation of the marks the Venom in the Wound prompt gives."""
    return (f"Coated: {item_name}. Once per turn, a hit with this weapon deals extra Poison or Acid damage equal to your "
            f"Proficiency Bonus and forces a Constitution save; "
            f"if the save fails the creature gains a Dose Mark (one poison step toward a Toxin Burden, a heavy poisoning "
            f"that lasts until a long rest), and that Dose Mark spends one of the coating's "
            f"uses. Uses left before the venom runs out: {charges}. The coating fades after 1 minute.")


@hook('after_hit')
def coated_weapon_hit(ctx: Any, target: Any, kind: str) -> None:
    """"Once per turn when the coated attack hits, it deals additional Poison or Acid damage equal to your Proficiency Bonus.
    The target then makes a Constitution saving throw. Failed Save: The target gains 1 Dose Mark."""
    me = ctx.actor
    coat = _coating(me)
    if coat is None or target is None or not target.active or kind not in ('weapon', 'unarmed', 'natural'):
        return
    if str(ctx.typed.get('source') or '') == COATING:
        return
    from .weapon_hits import weapon_identity
    if kind in ('weapon', 'unarmed') and weapon_identity(ctx) != (coat.data or {}).get('weapon'):
        return
    stamp = turn_stamp(ctx.engine)
    if me.turn_flags.get('poison_coating_turn') == stamp:
        return
    me.turn_flags['poison_coating_turn'] = stamp
    from dataclasses import replace
    from ..typed_executor import run_effects
    from .stacking_marks import count as mark_count
    pb = int(ctx.numbers.get('pb') or 2)
    note(ctx.engine, f"passive:{COATED}", me, f"Coated Weapon: {me.display_name}'s coated attack hits {target.display_name} "
        f"({pb} Poison or Acid damage, then a Constitution save).", (target.entity_id,))
    sub = replace(ctx, target=target, targets=[target], effect_source=COATED)
    # "damage equal to your Proficiency Bonus" is paid once. A typed amount's flat and its formula are *separate* additive
    # terms (combat/typed_amounts.dice_terms sums both into the roll modifier), so naming the Proficiency Bonus as both
    # would roll it twice and deal double the printed bonus.
    before = mark_count(ctx.engine, me, target, 'Dose Mark')
    run_effects(sub, [{'type': 'damage', 'flat': pb, 'damage_types': ['poison', 'acid'], 'applies_to': 'target'},
                      {'type': 'save', 'ability': 'con',
                       'on_fail': [{'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target'}],
                       'on_success': []}])
    # "ends after it has applied a Dose Mark a number of times equal to your Proficiency Bonus": only a Dose Mark this
    # owner actually placed on this creature spends a charge, so the owner's mark count is compared across the save. A
    # stored mark's id carries its owner (condition:typed.mark.dose_mark.<owner>), and a target that was already marked
    # keeps its stack whether this save succeeded or failed.
    if mark_count(ctx.engine, me, target, 'Dose Mark') <= before:
        return
    spent = dict(coat.data or {})
    left = max(0, int(spent.get('charges', 1)) - 1)
    # The remaining count is re-applied through the engine's own condition seam rather than edited in place: a stored
    # instance is rebuilt during replay from its CONDITION_APPLIED event, so an in-place data edit would leave the
    # recorded and the recomputed state disagreeing and the save would no longer load. This is the same remove-then-
    # re-apply shape combat/ext/stacking_marks uses for a counted mark.
    _clear_coating(ctx.engine, me, COATED)
    if left:
        ctx.engine._apply_condition(me, COATING, coat.source_definition_id, me.entity_id,
            expires_on=coat.expires_on,
            data={**spent, 'charges': left, 'label': _coat_label(str(spent.get('weapon_name') or ''), left)})


@hook('damage_dealt')
def venom_in_the_wound(ctx: Any, target: Any, amount: Any) -> None:
    """"When you damage a creature that is Bloodied, below half Hit Points, or suffering a wound-based condition, you may spend
    2 CP to make the poison ride the injury. The target makes a Constitution saving throw. Failed Save: The target gains 1
    Toxin Burden. Successful Save: The target gains 1 Dose Mark."

    The engine reports this hook only for damage it actually committed -- hit points lost plus Temporary HP absorbed -- for
    the attack path and for damage resolved by a save alike (combat/typed_executor._notify_damage_dealt). A hit that a
    Resistance or immunity kept at 0 therefore never offers the printed rider, which "when you damage" excludes, and a
    save-based poison effect offers it exactly as the printed words allow. The Blood rider is a printed Disadvantage,
    applied by the save_mode hook below only while that creature is actually bleeding."""
    me = ctx.actor
    if target is None or not target.active or int(amount or 0) <= 0 or not _owns(ctx.engine, me, WOUND):
        return
    if str(ctx.typed.get('source') or '') in (WOUND, COATED):
        return
    if not _wounded(target):
        return
    from dataclasses import replace
    from .choice_costs import payable
    from .d20_rewrite import pool_id
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import run_effects
    pool = pool_id(me, 'cp')
    payment = payable(me, pool, 2) if pool else None
    if payment is None:
        return
    blow = getattr(ctx.action, 'display_name', '') or 'your attack'
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'poison_venom_in_the_wound', target.entity_id),
        me, CHOICE + 'poison_venom_in_the_wound', ['RIDE'], allow_decline=True, target_id=target.entity_id,
        name='Venom in the Wound', feature_id=WOUND, payment=payment,
        labels={'RIDE': f'{payment.quote()}: {target.display_name} makes a Constitution save; a failure gives 1 Toxin Burden'},
        prompt=f"Venom in the Wound: {blow} deals {int(amount)} damage to {target.display_name}, who is wounded (Bloodied, "
               f"below half Hit Points, or already suffering a wound). Spend {payment.quote()} to have the poison ride that "
               f"injury? {target.display_name} then makes a Constitution save: a failure leaves 1 Toxin Burden (a heavy "
               f"poisoning that lasts until a long rest), a success leaves 1 Dose Mark (a poison step toward a Toxin Burden).")
    if not chosen:
        return
    payment.pay(ctx.engine, me, WOUND)
    sub = replace(ctx, target=target, targets=[target], typed={**ctx.typed, 'source': WOUND}, effect_source=WOUND)
    run_effects(sub, [{'type': 'save', 'ability': 'con',
                       'on_fail': [{'type': 'mark', 'mark': 'Toxin Burden', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}],
                       'on_success': [{'type': 'mark', 'mark': 'Dose Mark', 'applies_to': 'target'}]}])


def _wounded(target: Any) -> bool:
    """"Bloodied, below half Hit Points, or suffering a wound-based condition"."""
    if target.current_hp * 2 < target.maximum_hp:
        return True
    return any(word in str(row.condition_id).lower() for row in target.conditions.values() for word in ('bleeding', 'wound', 'bloodied'))


def _bleeding(target: Any) -> bool:
    return any(str(row.condition_id).endswith('bleeding') for row in target.conditions.values())


def _wound_provenance(engine: Any, source_id: Any, mode_context: Any) -> bool:
    """The printed Blood benefit applies only to Venom in the Wound's own save.

    ``venom_in_the_wound`` runs that save with ``effect_source=WOUND``.
    Blood ownership is proved by the saved, owner-bound willing Blood Thread
    action: ``blood_riders.blood_actions`` grants it only to sphere owners.
    A Blood talent's sphere metadata alone does not prove sphere ownership.
    Forged Poison + Blood provenance remains deferred because this fight has
    no authority receipt for it. Ordinary poison saves receive no penalty.
    """
    if str(source_id or '') != WOUND:
        return False
    context = mode_context if isinstance(mode_context, dict) else {}
    attacker = engine.state.actors.get(str(context.get('source_actor_id') or context.get('triggering_actor_id') or ''))
    if attacker is None or not _owns(engine, attacker, WOUND):
        return False
    from .fight_ownership import owns_granted_action
    return owns_granted_action(engine, attacker, BLOOD_ACTION)


@hook('save_mode')
def wound_bleeding_disadvantage(engine: Any, target: Any, ability: Any, dc: Any, source_id: Any,
                                mode_context: Any) -> str | None:
    """"If you have the Blood sphere or are using a forged Poison + Blood technique, the target has Disadvantage on the saving
    throw if it is currently bleeding."

    Disadvantage is a d20 *mode*, not an integer modifier. combat/gate2_engine._roll_save adds every ``save_bonus`` return
    into the roll's modifier -- a signed -1 there is one less on the single die -- while this ``save_mode`` seam is the one
    that rolls two d20s and keeps the lower. Native saves pass the ability upper-cased, so the comparison is case-folded.
    Provenance is deliberately narrow; see :func:`_wound_provenance`."""
    if target is None or str(ability or '').upper() != 'CON' or not _bleeding(target):
        return None
    return 'DISADVANTAGE' if _wound_provenance(engine, source_id, mode_context) else None


def _own_pb(engine: Any, actor: Any) -> int:
    """The saving creature's *own* Proficiency Bonus. ``ctx.numbers`` is built from the triggering action and so belongs to
    whoever provoked the save: a high-level poisoner would otherwise pay a low-level victim's Temporary HP, and the
    reverse would underpay. The public numbers helper (ext/spirit_traditions.numbers) reads this creature's own compiled
    values, and its runtime Proficiency Bonus is preferred because that is what its sheet was built with."""
    from . import spirit_traditions as st
    return int(getattr(actor, 'proficiency_bonus', 0) or 0) or int(st.numbers(engine, actor).get('pb') or 2)


def _grant_temp_hp(ctx: Any, me: Any, amount: int, feature: str) -> None:
    from dataclasses import replace
    from ..typed_executor import run_effects
    note(ctx.engine, f"passive:{feature}", me, f"{me.display_name} succeeds against poison: {amount} Temporary HP.",
         (me.entity_id,))
    run_effects(replace(ctx, target=me, targets=[me], effect_source=feature),
                [{'type': 'temp_hp', 'flat': amount, 'formula': 'none', 'applies_to': 'target'}])


def _venom_body_reward(ctx: Any, me: Any) -> None:
    """Venom Body Method's "Once per round" benefit. Mandatory rather than optional, and tracked in the round clock that
    survives the owner's turn start, so a save that lands before and after that start still pays only once."""
    round_now = int(ctx.engine.state.round_number)
    if me.turn_flags.get(BODY_ROUND_KEY) == round_now:
        return
    me.turn_flags[BODY_ROUND_KEY] = round_now
    _grant_temp_hp(ctx, me, _own_pb(ctx.engine, me), BODY)


def _thousand_reward(ctx: Any, me: Any) -> None:
    """Thousand-Poison Immunity's "Once per short rest ... you may gain Temporary HP equal to twice your Proficiency Bonus".

    "may" makes this a player-owned decision, so it is asked through the same Needle choice the other optional Poison
    riders use -- on the creature's own turn and on an enemy's alike, because the save can resolve during either. Declining
    spends nothing, so a player can hold the once-per-rest use in reserve; taking it marks the clock spent for the fight,
    which contains no short rest to refresh it."""
    if me.turn_flags.get(THOUSAND_KEY) == 'spent':
        return
    from .choice_prompt import action_context
    from .needle import ask, checkpoint_id, CHOICE
    amount = _own_pb(ctx.engine, me) * 2
    # The save this reward answers can resolve during somebody else's action, so the prompt names that action too:
    # on an enemy's turn a player sees only the choice, and "succeeded against poison" alone would not say what caused it.
    blow = str(getattr(ctx.action, 'display_name', '') or '') or 'a poison attack'
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'poison_thousand_temp_hp', me.entity_id),
        me, CHOICE + 'poison_thousand_temp_hp', ['TEMPORARY_HP'], allow_decline=True, target_id=me.entity_id,
        name='Thousand-Poison Immunity', feature_id=THOUSAND,
        prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, me),
        labels={'TEMPORARY_HP': f'{amount} Temporary HP, which absorb damage until they are gone'},
        prompt=f'Thousand-Poison Immunity: {me.display_name} succeeded on a saving throw against poison from {blow}. Take '
               f'{amount} Temporary HP now? Temporary HP absorb damage before your own Hit Points. You may take this only '
               f'once per short rest, so you can decline and save it for later.')
    if not chosen:
        return
    me.turn_flags[THOUSAND_KEY] = 'spent'
    _grant_temp_hp(ctx, me, amount, THOUSAND)


@hook('after_save_resolved')
def venom_body_temp_hp(ctx: Any, subject: Any, ability: Any, named: Any, failed: bool) -> None:
    """Venom Body Method "Once per round, when you succeed on a saving throw against poison or a Toxin Effect, you gain
    Temporary HP equal to your Proficiency Bonus" and Thousand-Poison Immunity's "Once per short rest, when you succeed on
    a saving throw against a poison or Toxin Effect, you may gain Temporary HP equal to twice your Proficiency Bonus".

    "when you succeed on a saving throw" -- the reward belongs to the creature that saved, so ownership is read on that
    creature, not on the source of the poison that provoked the save. Each rider is resolved on its own limit, so a
    creature that owns both keeps Venom Body Method's mandatory per-round benefit even when it declines the optional
    once-per-rest one."""
    me = subject
    if failed or me is None or not me.active or not _poison_save(ctx, named):
        return
    if _owns(ctx.engine, me, BODY):
        _venom_body_reward(ctx, me)
    if _owns(ctx.engine, me, THOUSAND):
        _thousand_reward(ctx, me)
