"""Alchemy rider states: denied Bonus Actions and Pill Devouring's formula DC.

The DC state is restricted to the owner's Field Formula text, including its
compiled base options and release-only recipe actions. It does not increase
Backdraft Fumes or saves from other spheres. Existing speech, CP-denial and
healing-reduction interpreters handle the other reviewed Alchemy riders.

Smoke of Returning Breath uses the beneficiary's bounded choice checkpoint,
not the caster's menu. Deafened removal, free standing and the next CON save
run through existing interpreters. Blinded removal remains a GM choice because
conditions do not reliably record smoke/powder/poison/alchemical causation.

Court of the Three-Legged Cauldron's active domain state enables its failed-save
damage rider. The caster chooses its printed damage type; an evented condition
on each beneficiary records use until the triggering turn ends. Active typed
saves are covered; the separate generic-reaction save interpreter is not.
Its once-per-turn Field Formula CP discount is refunded as the formula resolves,
through the shared technique_costs seam and the fighter's own Path pool.

Bitter Dregs variants substitute declared prepared stock at compile time via
the general replace_cost vocabulary. Their marker enables one damage-roll
bonus and resolved-outcome backlash in this activation's shared Context cache.
The technique_final hook pays the mandatory backlash even if the formula ended
combat; no transient use state is stored on an actor or left for another turn.

Formula Intensification compiles one costed option per use. Its push records
final failed saves/hits locally, then lets the caster choose exactly one
affected creature after resolution. Its step uses the shared path resolver in
the final callback, including after the formula defeats the last hostile.

Pill of Restoration ends Poisoned instances with a retained alchemical source
action. Unknown/non-alchemical causes stay GM-qualified; a generic Poisoned
tag is not evidence of the printed cause. The source action survives reload.

Pill Devouring stores an evented obligation with the standard ten-round clock.
At its expiry boundary the owner chooses Impurity or Poison through the existing
bounded choice transport and the native accepted intent's transaction-bound
END_TURN transport. Saved obligations contain only a clock string; saved Pill
Impurities contain an integer, remain until removed, and have no invented cap.
Purification's self-consumption option rolls and removes 1d4 from that same
counter. Preparation, administration, affliction grades and rest history remain
explicit GM qualifications. Hunger's separate Impurity resource is untouched.

Seven-Flavor Furnace records the damage types its owner prepared, in one string, on
the caster's own condition, and offers them *beside* the printed Acid, Fire, Poison
or Force choice (the printed talent says "instead", which is a choice between the two
sets, not a replacement of them): the ``damage_type_choices`` seam
(combat/typed_executor.choose_damage_type) for a formula that chooses its type as
it resolves (Furnace Vent, Rotting Pill, Backdraft Fumes, Explosive Pill), the Court's
own failed-save choice (which asks the same question, so a formula that offers no
damage type of its own can still prepare), and this module's own creation-time choice
for World Within the Furnace, whose printed type is chosen when the area is made. A
fight has no Long Rest boundary, so the printed choice is put once, at the first
printed damage-type choice that would matter, and the answer is then sealed for that
rest: an empty preparation is recorded too, so declining is a decision rather than a
repeated question. The prompt names the ability, the action that triggered it and the
creature affected. Nobody answering leaves every printed type exactly as printed.

World Within the Furnace uses a compiled damage menu and a bounded creation
choice for each printed decision: the damage type of the area and the failed-save
effect. Each start-turn beneficiary is chosen by the caster through the bounded
choice transport. Zone rows retain both chosen effects, including on reload;
no new creature is silently included merely because it joins the fight later.

Healing Pill counts actual HP benefits on the consumer, not on the recipe's
refiner. The evented integer survives turns and table reloads. Combat has no
Long Rest boundary or cross-fight recipe-history import: the retained rider
requires that history to be supplied and the counter removed after a real rest.

Binding Dregs' "If the target is standing on a solid surface, it also cannot take
the Dash action" is qualified when the save resolves, not while the condition is
read: a creature that was in the air when the formula hit never gains the printed
Dash ban, and one that was on the ground keeps it even if it takes off before the
caster's next turn. The printed expiry is unchanged.
"""
import re
from typing import Any

from . import effect, hook
from .passive_rows import row_of
from .rider_helpers import effect_rows, printed_source

NO_BONUS = 'condition:typed.alchemy_no_bonus'
FIELD_DC = 'condition:typed.field_formula_dc'
COURT = 'condition:typed.alchemy_court_damage'
COURT_ID = 'tianxia.talent.alchemy.court_of_the_three_legged_cauldron'
BITTER_ID = 'TAL_ALCHEMY_BITTER_DREGS'
INTENSIFY_ID = 'tianxia.talent.alchemy.formula_intensification'
RESTORATION_ID = 'TAL_ALCHEMY_PILL_OF_RESTORATION'
DEVOURING_ID = 'tianxia.talent.alchemy.pill_devouring'
PURIFICATION_ID = 'tianxia.talent.alchemy.purification_formula'
FURNACE_ID = 'tianxia.talent.alchemy.world_within_the_furnace'
DEVOURING_COST = 'condition:typed.pill_devouring_cost'
PILL_IMPURITIES = 'condition:typed.pill_impurities'
HEALING_PILL_ID = 'TAL_ALCHEMY_HEALING_PILL'
HEALING_PILL_BENEFITS = 'condition:typed.healing_pill_benefits'
SEVEN_ID = 'tianxia.talent.alchemy.seven_flavor_furnace'
SEVEN_CONDITION = 'condition:typed.seven_flavor_types'
#: The printed set Seven-Flavor Furnace substitutes into ("When an Alchemy technique lets you choose Acid, Fire,
#: Poison, or Force damage"), and the eight types a Long Rest may prepare.
SUBSTITUTED = ('acid', 'fire', 'poison', 'force')
PREPARABLE = ('acid', 'cold', 'fire', 'lightning', 'necrotic', 'poison', 'radiant', 'thunder')


def alchemy_source(source: str) -> bool:
    """Whether a typed source is one of Alchemy's own printed mechanics (including legacy TAL ids)."""
    from ..factory_compiler import _rules_text

    return (source in _rules_text()
            and (source.startswith('ALCHEMY_BASE_') or source.startswith('TAL_ALCHEMY_')
                 or source.startswith('tianxia.talent.alchemy.')))


@hook('compile_block')
def compile_seven_flavor(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[Any] | None:
    """Record the owner of Seven-Flavor Furnace as a compiled passive row of this module's own block."""
    if block == 'alchemy':
        return [{**row, 'kind': str(spec.get('kind') or ''), 'numbers': dict(numbers)}]


def owns_seven_flavor(engine: Any, actor: Any) -> bool:
    """Whether this creature's own compiled bundle carries Seven-Flavor Furnace."""
    return row_of(engine, actor.entity_id, 'alchemy', 'seven_flavor') is not None


def preparation(actor: Any) -> Any | None:
    """The owner's own Seven-Flavor Furnace record, the one condition this ability ever puts on its owner."""
    return next((c for c in actor.conditions.values() if c.condition_id == SEVEN_CONDITION), None)


def recorded_types(actor: Any) -> list[str]:
    """The owner's prepared damage types, as remembered on their own condition (one '|'-joined string).

    Empty when the owner answered the printed Long Rest question with nothing (see :func:`declared_types`).
    """
    held = preparation(actor)
    if held is None:
        return []
    return [value for value in str((held.data or {}).get('types') or '').split('|') if value]


def declares_substitution(engine: Any, actor: Any, source: str) -> bool:
    """Whether this creature's own Alchemy ability is the printed one Seven-Flavor Furnace substitutes into."""
    return owns_seven_flavor(engine, actor) and alchemy_source(source)


#: The printed evidence of a damage type its user chooses when the effect is made ("takes 5d6 damage of the chosen
#: type"), which is how a zone carries one printed type per compiled option. Read from the effect's own words.
CHOOSES_TYPE = re.compile(r'of the chosen type|chosen when you (?:create|refine)', re.I)
#: How deep a compiled row tree is walked looking for a printed damage-type choice. A zone nests
#: typed > zone_spec > triggers > effects > effects > save > on_fail > damage, so eight is too shallow; the walk
#: is bounded because a compiled row tree is data, never a graph.
MAX_ROW_DEPTH = 16


def deals_its_damage_now(row: dict[str, Any]) -> bool:
    """Whether the engine resolves this row's own damage as part of the activation being read.

    A row whose type only a plug-in handles (``combat/ext``'s own ``@effect``, which typed_executor falls back to
    its rider printer for) records state and prints a rider; the types it lists describe damage dealt on a later
    trigger, so the printed choice belongs to that trigger's own question and not to this activation. A row the
    engine resolves (``typed_executor.BLOCKS``) deals what it lists right here. Read from the row's own type, so
    every sphere's marker rows are treated alike and nothing is keyed on an ability id.
    """
    from ..typed_executor import BLOCKS

    kind = row.get('type')
    return kind is None or kind in BLOCKS


def offered_types(data: Any, depth: int = 0) -> set[str]:
    """The damage types this compiled data really offers its user a choice of, lower-cased.

    Two printed shapes, both read from the data itself: a damage row that lists more than one type ("takes Poison
    or Fire damage ... chosen when you use this formula"), and a damage row whose own evidence says its type is
    chosen when the effect is made ("takes 5d6 damage of the chosen type"; a zone carries one printed type per
    compiled option, so no single row of it offers a choice). A row that only a plug-in resolves describes a
    later trigger instead (see :func:`deals_its_damage_now`). Nothing about any one ability is named here.
    """
    if depth > MAX_ROW_DEPTH:
        return set()
    if isinstance(data, dict):
        kinds = {str(kind).lower() for kind in data.get('damage_types') or []}
        if deals_its_damage_now(data) and (len(kinds) > 1
                                           or (kinds and CHOOSES_TYPE.search(str(data.get('evidence') or '')))):
            return kinds
        return set().union(*(offered_types(value, depth + 1) for value in data.values()))
    if isinstance(data, list):
        return set().union(*(offered_types(item, depth + 1) for item in data))
    return set()


def declares_seven_flavor(engine: Any, actor: Any, source: str, kinds: Any) -> bool:
    """Whether ``source`` is one of this owner's Alchemy abilities whose printed damage-type choice
    ("Acid, Fire, Poison or Force") Seven-Flavor Furnace substitutes into."""
    if not declares_substitution(engine, actor, source):
        return False
    return bool({str(kind).lower() for kind in kinds} & set(SUBSTITUTED))


def declared_types(ctx: Any, *, subject: Any = None) -> list[str]:
    """Seven-Flavor Furnace's prepared damage types, asking the printed Long Rest question once if it is open.

    "When you finish a Long Rest, choose up to three damage types": a fight has no Long Rest boundary, so the
    question is put the first time one of this owner's Alchemy abilities really offers the printed choice, through
    the bounded choice transport and as a player-owned decision (automatic=False). The answer is remembered on the
    owner's own condition as one string and stands until it is changed or removed.

    An empty answer is recorded too: "up to three" lets a player prepare nothing, and once-per-rest means one
    question, so declining is sealed rather than asked again on the next formula (and never re-asked after the
    answer has been learned about a new enemy). Nobody answering leaves every printed type exactly as printed.
    ``subject`` only names the creature affected, for the prompt.
    """
    if preparation(ctx.actor) is not None or not declares_substitution(ctx.engine, ctx.actor, printed_source(ctx)):
        return recorded_types(ctx.actor)
    from . import needle

    labels = {kind: kind.capitalize() for kind in PREPARABLE}
    trigger = f'before {ctx.action.display_name}'
    if subject is not None:
        trigger = f'after {subject.display_name} fails the save from {ctx.action.display_name}'
    chosen = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'SEVEN_FLAVOR', SEVEN_ID),
        ctx.actor, 'choice:needle.seven_flavor', list(PREPARABLE), labels=labels,
        prompt=f'Seven-Flavor Furnace, {trigger}: name up to three damage types you have prepared for this rest '
               '(each one needs its own ingredients, furnace fuel or recipe logic). They can stand in for the Acid, '
               'Fire, Poison or Force damage your Alchemy formulas let you choose. Name none to keep only the '
               'printed types.',
        name='Seven-Flavor Furnace', feature_id=SEVEN_ID, minimum=0, maximum=3,
        allow_decline=True, automatic=False, default='decline')
    types = '|'.join(kind for kind in chosen if kind in PREPARABLE)
    ctx.engine._remove_condition(ctx.actor, SEVEN_CONDITION, SEVEN_ID)
    ctx.engine._apply_condition(ctx.actor, SEVEN_CONDITION, SEVEN_ID, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                                data={'types': types, 'label': preparation_label(types)})
    return recorded_types(ctx.actor)


def preparation_label(types: str) -> str:
    """What this condition means, in the words of the printed talent, for the creature's own condition pill.

    Says what it does (stand in for the printed types), which types, and how long (until you change or
    remove it). An empty preparation says plainly that the formulas keep their printed types.
    """
    if not types:
        return ('Seven-Flavor Furnace: no damage types prepared this rest, so your Alchemy formulas keep the '
                'printed Acid, Fire, Poison and Force damage')
    named = ', '.join(kind.capitalize() for kind in types.split('|'))
    return (f'Seven-Flavor Furnace: your Alchemy formulas may deal {named} damage instead of the printed Acid, '
            'Fire, Poison or Force, until you change or remove it')


@hook('technique_start')
def seven_flavor_prepare(engine: Any, actor: Any, action: Any) -> None:
    """Put the printed Long Rest question before this formula's effects, where the printed choice exists.

    Only where the activation's own compiled rows really offer the substituted set (a damage row that lists one of
    Acid, Fire, Poison or Force among a choice, or one whose evidence says its type is chosen as the effect is
    made): Seven-Flavor Furnace's printed trigger is a damage-type choice, not every Alchemy activation.
    Returns nothing: it never stops the activation.
    """
    if not owns_seven_flavor(engine, actor) or preparation(actor) is not None:
        return
    typed = dict(getattr(action, 'parameters', None) or {}).get('typed') or {}
    source = str(typed.get('option_of') or typed.get('source') or '').split('#')[0]
    if not declares_substitution(engine, actor, source) or not offered_types(typed) & set(SUBSTITUTED):
        return
    from ..typed_executor import Context

    declared_types(Context(engine, actor, action, getattr(engine, '_active_intent', None), typed, [], None))


@hook('damage_type_choices')
def seven_flavor_choice(ctx: Any, kinds: list[str]) -> list[str] | None:
    """The owner's prepared types beside the printed ones, wherever an Alchemy formula chooses its damage type.

    The printed talent says its owner "may choose one of your selected damage types instead", which is a choice
    between two sets: the prepared types are added to the types the row already offers, never substituted for them,
    so a prepared type that a creature resists or is immune to loses to a printed one that lands. Prepared first,
    because the automatic "lands hardest" pick keeps the first listed type of a tie and the owner declared these.
    """
    if not declares_seven_flavor(ctx.engine, ctx.actor, printed_source(ctx), kinds):
        return None
    prepared = declared_types(ctx)
    if not prepared:
        return None
    return [kind.upper() for kind in dict.fromkeys([*prepared, *(str(kind).lower() for kind in kinds)])]


@effect('alchemy_seven_flavor_types')
def seven_flavor_marker(ctx: Any, row: dict[str, Any]) -> None:
    """The passive talent's own marker row; the prepared types are held by its plug-in state."""


def zone_damage_types(spec: dict[str, Any]) -> list[str]:
    """The damage types this zone's own rows carry, lower-cased and in the order they appear."""
    kinds: list[str] = []
    for row in effect_rows(spec.get('triggers')):
        if row.get('type') == 'damage':
            kinds.extend(str(kind).lower() for kind in row.get('damage_types') or [])
    return list(dict.fromkeys(kinds))


def retype_zone_damage(spec: dict[str, Any], kind: str) -> dict[str, Any]:
    """Carry one chosen damage type on every damage row of a zone the printed text types as "the chosen type"."""
    for row in effect_rows(spec.get('triggers')):
        if row.get('type') == 'damage' and {str(kind).lower() for kind in row.get('damage_types') or []} <= set(SUBSTITUTED):
            row['damage_types'] = [str(kind).lower()]
    return spec


# ------------------------------------------------------------------------------- solid-surface qualification


def on_solid_surface(subject: Any) -> bool:
    """Whether a creature stands on a solid surface, read from its own position: anything above the board
    (position.z) is in the air, the same altitude test combat/ext/altitude_abilities.py already uses."""
    return (getattr(getattr(subject, 'position', None), 'z', 0) or 0) <= 0


def needs_solid_surface(effect: Any) -> bool:
    """Whether a typed condition row's own rule is printed as depending on a solid surface
    ("If the target is standing on a solid surface, it also cannot take the Dash action"), spelled
    ``condition_data {"rule": {"requires_ground": true}}``. Read from the row, so any sphere's data may use it."""
    return bool(((effect.get('condition_data') or {}).get('rule') or {}).get('requires_ground'))


@hook('condition_state')
def solid_surface_qualification(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    """Qualify a solid-surface clause once, when the condition's own effect resolves.

    The engine's general condition_state seam (combat/ext/__init__.py): False skips application. The printed
    clause is about the target as the formula found it, so a creature in the air then never gains the rule and one
    on the ground keeps it for the row's own printed duration even if it later takes off; reading the same clause
    while the condition is queried would add the rule on landing and drop it on taking off. Every other row, and
    every reader of the rule afterwards (the action menu combat/ext/no_dash.py, a typed Dash, the printed text),
    is unchanged.
    """
    if not needs_solid_surface(effect) or on_solid_surface(subject):
        return None
    ctx.rider(f'{ctx.action.display_name} does not prevent {subject.display_name} from taking the Dash action '
              f'because it was not standing on a solid surface.')
    return False


@effect('alchemy_healing_pill')
def healing_pill(ctx: Any, row: dict[str, Any]) -> None:
    """A prepared Healing Pill benefits its consumer at most that consumer's PB.

    Ordinary consumption is self; Medicine Saint's administration explicitly
    targets its recipient. Full HP and denied healing spend no benefit use.
    Rest/pre-fight history remains an explicit preparation boundary.
    """
    from dataclasses import replace
    from ..typed_executor import _default_subject, block_healing

    if str(ctx.typed.get('option_of') or ctx.typed.get('source') or '').split('#')[0] != HEALING_PILL_ID:
        return
    for subject in _default_subject(ctx, row, harmful=False):
        used = sum(int(c.data.get('amount', 0)) for c in subject.conditions.values()
                   if c.condition_id == HEALING_PILL_BENEFITS)
        if used >= int(subject.proficiency_bonus):
            ctx.rider(f'Healing Pill: {subject.display_name} has reached its benefits limit; no HP restored.')
            continue
        first_event = len(ctx.engine.events)
        block_healing(replace(ctx, target=subject, targets=[subject]),
                      {**row, 'type': 'healing', 'applies_to': 'target'})
        benefited = any(e.event_type == 'HEALING_APPLIED' and e.source_definition_id == ctx.source
                        and subject.entity_id in e.target_ids and e.payload['offered'] > 0
                        and e.payload['before'] < subject.maximum_hp
                        for e in ctx.engine.events[first_event:])
        if benefited:
            # The exact recipe cap is shared across refiners and administration
            # routes. Replace the aggregate instead of summing overlapping counts.
            ctx.engine._remove_condition(subject, HEALING_PILL_BENEFITS, ctx.source)
            ctx.engine._apply_condition(subject, HEALING_PILL_BENEFITS, ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'amount': used + 1, 'label': 'Healing Pill benefits since Long Rest'})


@effect('alchemy_furnace_create')
def furnace_create(ctx: Any, row: dict[str, Any]) -> None:
    """Both printed creation choices of World Within the Furnace, put before the following zone effect stores them.

    "When you create the area, choose Acid, Fire, or Poison" and "suffers one of the following effects, chosen when
    you create the area" are two separate printed decisions. The damage type is a compiled action option (Acid, Fire
    and Poison are three of this ability's own options), so it is asked here as one bounded menu over those printed
    types plus the owner's own prepared ones (Seven-Flavor Furnace: "you may choose one of your selected damage types
    instead"), and the chosen type is written into this activation's zone rows, which the area keeps and a saved
    fight reloads. The failed-save effect is the rider menu. Only this activation's Context is changed, never the
    catalog or a core function.
    """
    import copy
    from . import needle

    if str(ctx.typed.get('option_of') or ctx.typed.get('source') or '').split('#')[0] != FURNACE_ID:
        return
    spec = copy.deepcopy(ctx.typed['zone_spec'])
    printed = zone_damage_types(spec)
    prepared = declared_types(ctx)
    kinds = list(dict.fromkeys([*prepared, *printed])) or printed
    if len(kinds) > 1:
        kind = needle.ask(ctx.engine, ctx.intent,
            needle.checkpoint_id(ctx.engine, 'FURNACE_TYPE', ctx.source), ctx.actor,
            'choice:needle.furnace_type', kinds,
            labels={kind: f'{kind.capitalize()} damage' for kind in kinds},
            prompt=f'World Within the Furnace: {ctx.action.display_name} — choose the damage type creatures in the '
                   f'area take when they fail their save',
            name='World Within the Furnace', minimum=1, maximum=1, preferred=printed)
        if kind:
            retype_zone_damage(spec, kind[0])
    ctx.typed['zone_spec'] = spec
    choices = row.get('choices') or {}
    chosen = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'FURNACE_RIDER', ctx.source), ctx.actor,
        'choice:needle.furnace_rider', list(choices),
        prompt=f'World Within the Furnace: {ctx.action.display_name} — choose the failed-save effect for affected creatures',
        name='World Within the Furnace')
    if not chosen:
        return
    for trigger in spec['triggers']:
        if trigger['who'] == 'hostile':
            save = trigger['effects'][0]['effects'][0]
            save['on_fail'].extend(copy.deepcopy(choices[chosen[0]]))


def pill_impurities(actor: Any) -> int:
    """Alchemy's persistent, uncapped counter; distinct from Hunger's Impurity."""
    return sum(int(c.data.get('amount', 0)) for c in actor.conditions.values()
               if c.condition_id == PILL_IMPURITIES)


def set_pill_impurities(ctx: Any, subject: Any, amount: int) -> None:
    """Replace through evented engine operations, never mutate condition data."""
    ctx.engine._remove_condition(subject, PILL_IMPURITIES, ctx.source)
    if amount > 0:
        ctx.engine._apply_condition(subject, PILL_IMPURITIES, ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'amount': int(amount), 'label': 'Pill Impurities'})


@effect('pill_impurities')
def impurities(ctx: Any, row: dict[str, Any]) -> None:
    """Devouring adds one at expiry; Purification removes a rolled, clamped 1d4."""
    from ..typed_executor import _default_subject

    source = str(ctx.typed.get('option_of') or ctx.typed.get('source') or '').split('#')[0]
    if source == DEVOURING_ID and row.get('operation') == 'gain':
        set_pill_impurities(ctx, ctx.actor, pill_impurities(ctx.actor) + 1)
    elif source == PURIFICATION_ID and row.get('operation') == 'remove':
        for subject in _default_subject(ctx, row, harmful=False):
            roll = ctx.engine.roller.roll(ctx.dice({'count': 1, 'sides': 4}),
                actor_id=ctx.actor.entity_id, reason=f'PILL_IMPURITIES:{ctx.source}')
            ctx.engine._record_roll(roll)
            ctx.engine._append_event('DAMAGE_ROLLED', ctx.source, actor_id=ctx.actor.entity_id,
                target_ids=(subject.entity_id,), payload=roll.model_dump(mode='json'))
            set_pill_impurities(ctx, subject, max(0, pill_impurities(subject) - roll.total))


@effect('pill_devouring_cost')
def devouring_cost(ctx: Any, row: dict[str, Any]) -> None:
    """Store only a clock string; the player chooses the cost when it comes due."""
    from .effect_durations import round_token

    if str(ctx.typed.get('source') or '').split('#')[0] != DEVOURING_ID:
        return
    ctx.engine._apply_condition(ctx.actor, DEVOURING_COST, ctx.source, ctx.actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'due': round_token(ctx.engine, 10),
            'label': 'Pill Devouring: cost due when the effect ends'})


@effect('alchemy_furnace_target')
def furnace_target(ctx: Any, row: dict[str, Any]) -> None:
    """Ask the owning caster for this turn's beneficiary before any save/effect.

    The zone's ordinary team and footprint filters decide eligibility first.
    The action catalog proves ownership; the row cannot affect unrelated zones.
    A real accepted intent is retained only transiently for END_TURN boundaries.
    """
    from dataclasses import replace
    from . import needle
    from ..typed_executor import run_effects

    typed = ctx.action.parameters.get('typed') or {}
    source = str(typed.get('option_of') or typed.get('source') or '').split('#')[0]
    if source not in (FURNACE_ID, COURT_ID) or ctx.target is None:
        return
    name = 'World Within the Furnace' if source == FURNACE_ID else 'Court of the Three-Legged Cauldron'
    intent = ctx.intent or getattr(ctx.engine, '_active_intent', None)
    if intent is None:
        ctx.rider(f'{name}: GM chooses whether {ctx.target.display_name} is affected at this boundary.')
        return
    chosen = needle.ask(ctx.engine, intent,
        needle.checkpoint_id(ctx.engine, 'FURNACE_TARGET', ctx.source, ctx.target.entity_id),
        ctx.actor, 'choice:needle.furnace_target', ['include', 'exclude'],
        labels={'include': 'Affect this creature', 'exclude': 'Leave this creature unaffected'},
        prompt=f'{name}: {ctx.action.display_name} at turn start — affect {ctx.target.display_name}?',
        name=name,
        preferred=['include'], target_id=ctx.target.entity_id)
    if chosen == ['include']:
        run_effects(replace(ctx, intent=intent), row.get('effects') or [])


@hook('turn_start_choice')
def pay_devouring_cost(engine: Any, actor: Any) -> None:
    """Resolve all due owners, including an owner's cost on another actor's turn."""
    from . import needle
    from .effect_durations import due, token
    from ..typed_executor import Context, run_effects

    # Fresh-engine initialization has no accepted player action. Never silently
    # choose for a player there; the persistent obligation remains for replay.
    intent = engine._active_intent
    if intent is None:
        return
    for owner in engine.state.actors.values():
        for obligation in list(owner.conditions.values()):
            if obligation.condition_id != DEVOURING_COST or not due(engine, obligation.data.get('due')):
                continue
            action = engine.action_catalog.get(obligation.source_definition_id)
            if action is None:
                continue
            chosen = needle.ask(engine, intent,
                needle.checkpoint_id(engine, 'PILL_DEVOURING_COST', owner.entity_id, obligation.instance_id),
                owner, 'choice:needle.pill_devouring_cost', ['impurity', 'poison'],
                labels={'impurity': 'Gain 1 Pill Impurity', 'poison': 'Take 2d6 Poison damage and become Poisoned'},
                prompt=f'Pill Devouring: {action.display_name} ends — choose the cost for {owner.display_name}',
                name='Pill Devouring',
                minimum=1, maximum=1, preferred=['impurity'], target_id=owner.entity_id)
            if not chosen:
                continue
            del owner.conditions[obligation.instance_id]
            engine._append_event('CONDITION_REMOVED', action.source_definition_id,
                actor_id=owner.entity_id, target_ids=(owner.entity_id,),
                payload={'condition_id': DEVOURING_COST, 'instance_id': obligation.instance_id})
            rows = [{'type': 'pill_impurities', 'operation': 'gain'}] if chosen == ['impurity'] else [
                {'type': 'damage', 'applies_to': 'self', 'dice': {'count': 2, 'sides': 6},
                 'damage_types': ['poison']},
                {'type': 'condition', 'applies_to': 'self', 'condition': 'poisoned',
                 'expires_on': token('end', owner.entity_id, owner.turns_started + 1)}]
            run_effects(Context(engine, owner, action, intent, action.parameters['typed'], [owner], owner), rows)


@effect('alchemy_restore_poison')
def restore_poison(ctx: Any, row: dict[str, Any]) -> None:
    """End only instances whose source action belongs to the Alchemy sphere.

    This does not guess poison causation for other spheres or legacy sources.
    Remove instances individually so an unrelated simultaneous cause survives.
    """
    import json
    from ..factory_compiler import TYPED_AUTHORITY

    if str(ctx.typed.get('option_of') or ctx.typed.get('source') or '').split('#')[0] != RESTORATION_ID:
        return
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())['mechanics']
    unresolved = False
    for instance_id, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id != 'condition:typed.poisoned':
            continue
        action = ctx.engine.action_catalog.get(condition.source_definition_id)
        typed = (action.parameters.get('typed') or {}) if action is not None else {}
        source = str(typed.get('option_of') or typed.get('source') or '').split('#')[0]
        if (mechanics.get(source) or {}).get('sphere_id') != 'tianxia.sphere.alchemy':
            unresolved = True
            continue
        del ctx.actor.conditions[instance_id]
        ctx.engine._append_event('CONDITION_REMOVED', ctx.source,
            actor_id=condition.source_actor_id, target_ids=(ctx.actor.entity_id,),
            payload={'condition_id': condition.condition_id, 'instance_id': instance_id})
    if unresolved:
        ctx.rider('Pill of Restoration: GM must qualify remaining Poisoned causes as poison or alchemical effects.')


@hook('compile_recipe_options')
def meridian_release(owned, mechanics):
    from ..recipe_options import RecipeOption
    base, recipe = 'ALCHEMY_BASE_FIELD_FORMULA', 'TAL_ALCHEMY_MERIDIAN_SEALING_PILL'
    if {base, recipe} <= owned:
        return [RecipeOption(base, recipe, mechanics[recipe]['effects'], 'ANY_CREATURE')]


def selected(ctx, feature):
    """Read one selected modifier or a composed recipe's selected modifiers."""
    return any(row.get('id') == feature for row in
               [ctx.typed.get('modifier') or {}, *(ctx.typed.get('selected_modifiers') or [])])


def intensification(ctx: Any) -> str | None:
    if not selected(ctx, INTENSIFY_ID):
        return None
    return next((row.get('option') for row in ctx.typed.get('effects') or []
                 if row.get('type') == 'formula_intensification'), None)


@effect('formula_intensification')
def intensification_marker(ctx: Any, row: dict[str, Any]) -> None:
    """Activation marker; final-outcome hooks own the delayed rider."""


@hook('after_save_resolved')
def intensification_save(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    if failed and intensification(ctx) == 'push':
        ctx.damage_cache.setdefault('_intensification_targets', set()).add(subject.entity_id)


@hook('after_hit')
def intensification_hit(ctx: Any, subject: Any, kind: str) -> None:
    if intensification(ctx) == 'push':
        ctx.damage_cache.setdefault('_intensification_targets', set()).add(subject.entity_id)


@hook('technique_used')
def intensification_finish(ctx: Any) -> None:
    from dataclasses import replace
    from . import needle
    from ..typed_executor import run_effects

    option = intensification(ctx)
    if option is None or not ctx.actor.active or ctx.engine.state.terminal_result is not None:
        return
    if option == 'push':
        targets = {key: ctx.engine.state.actors[key] for key in sorted(
            ctx.damage_cache.get('_intensification_targets', set())) if ctx.engine.state.actors[key].active}
        if not targets:
            return
        chosen = needle.ask(ctx.engine, ctx.intent,
            needle.checkpoint_id(ctx.engine, 'INTENSIFICATION_PUSH', ctx.source), ctx.actor,
            'choice:needle.intensification_push', list(targets),
            labels={key: f'Push {actor.display_name} 10 feet' for key, actor in targets.items()},
            prompt=f'Formula Intensification: {ctx.action.display_name} — choose one affected creature to push',
            name='Formula Intensification',
            preferred=list(targets)[:1], minimum=1, maximum=1)
        if chosen and chosen[0] in targets:
            subject = targets[chosen[0]]
            run_effects(replace(ctx, targets=[subject], target=subject), [{
                'type': 'forced_movement', 'applies_to': 'target',
                'distance_ft': 10, 'direction': 'away'}])


@hook('technique_final')
def intensification_step(ctx: Any) -> None:
    """Finish the chosen movement inside the native terminal-safe transaction."""
    if intensification(ctx) != 'step' or not ctx.actor.active:
        return
    from ..typed_executor import run_effects

    run_effects(ctx, [{'type': 'rider_step', 'distance_ft': 10, 'no_oa': True,
        'label': f'{ctx.action.display_name}: {ctx.actor.display_name} may step up to 10 feet '
                 'without provoking Opportunity Attacks, with no further cost'}])


def bitter_use(ctx: Any) -> bool:
    """Only an explicitly chosen, owned Bitter Dregs variant enables its hooks."""
    return selected(ctx, BITTER_ID)


@effect('bitter_dregs')
def bitter_marker(ctx: Any, row: dict[str, Any]) -> None:
    """The modifier marker; hooks account for outcomes and damage as they occur."""


@hook('damage_roll_bonus')
def bitter_bonus(ctx: Any, row: dict[str, Any] | None, kinds: list[str] | None = None) -> int | None:
    if row is None or not bitter_use(ctx) or ctx.damage_cache.get('_bitter_bonus_used') or not any(
            row is original for original in effect_rows(ctx.typed.get('effects'))):
        return None
    ctx.damage_cache['_bitter_bonus_used'] = True
    return ctx.formula('pb')


@hook('attack_damage_bonus')
def bitter_attack_bonus(ctx: Any, subject: Any, row: dict[str, Any]) -> int | None:
    bonus = bitter_bonus(ctx, row)
    if bonus is not None:
        ctx.damage_cache['_bitter_attack_reserved'] = True
    return bonus


@hook('after_hit')
def bitter_hit(ctx: Any, subject: Any, kind: str) -> None:
    if bitter_use(ctx):
        ctx.damage_cache.pop('_bitter_attack_reserved', None)


@hook('after_save_resolved')
def bitter_save(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    if not bitter_use(ctx):
        return
    ctx.damage_cache['_bitter_saves'] = ctx.damage_cache.get('_bitter_saves', 0) + 1
    if failed:
        ctx.damage_cache['_bitter_failed'] = True


@hook('after_miss')
def bitter_miss(ctx: Any, subject: Any) -> None:
    if bitter_use(ctx):
        ctx.damage_cache['_bitter_missed'] = True
        if ctx.damage_cache.pop('_bitter_attack_reserved', False):
            ctx.damage_cache.pop('_bitter_bonus_used', None)


@hook('technique_final')
def bitter_backlash(ctx: Any) -> None:
    """Pay once from final outcomes, inside the native final-rider transaction."""
    if not bitter_use(ctx) or not (ctx.damage_cache.get('_bitter_missed') or
            (ctx.damage_cache.get('_bitter_saves') and not ctx.damage_cache.get('_bitter_failed'))):
        return
    from dataclasses import replace
    from ..typed_executor import run_effects

    # A distinct empty cache prevents the bonus from ever buffing its own
    # backlash, including nondamaging Field Formulae such as Binding Dregs.
    run_effects(replace(ctx, targets=[ctx.actor], target=ctx.actor,
                        typed={**ctx.typed, 'modifier': None, 'selected_modifiers': []}, damage_cache={}),
                [{'type': 'damage', 'applies_to': 'self', 'flat': ctx.formula('pb'),
                  'formula': 'none', 'damage_types': ['poison']}])


@effect('bonus_action_denied')
def deny_bonus(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import _default_subject, effect_expiry

    for subject in _default_subject(ctx, row, harmful=True):
        ctx.engine._apply_condition(subject, NO_BONUS, ctx.source, ctx.actor.entity_id,
            expires_on=effect_expiry(ctx, row, subject, condition=True), data={'label':'Cannot take Bonus Actions'})


@hook('candidate_allowed')
def bonus_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if getattr(getattr(action, 'economy', None), 'value', None) == 'BONUS_ACTION' and any(
            c.condition_id == NO_BONUS for c in actor.conditions.values()):
        return False
    return None


@effect('field_formula_dc')
def formula_buff(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, FIELD_DC, ctx.source)
    ctx.engine._apply_condition(ctx.actor, FIELD_DC, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.actor, condition=True), data={'label':'+2 Field Formula save DC'})


def is_field_formula(source: str) -> bool:
    """Whether an ability's own printed text makes it one of Alchemy's Field Formulae.

    Read from the owner's rules text (the Field Formula base ability, a formula the
    character learned, or one released as a Field Formula), never from an ability name.
    """
    from ..factory_compiler import _rules_text

    text = _rules_text().get(source, '')
    return source == 'ALCHEMY_BASE_FIELD_FORMULA' or bool(re.search(
        r'Timing Detail: Field Formula|You learn the [^\n]+ Field Formula\.|When released as a Field Formula', text, re.I))


@hook('save')
def formula_dc(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    if not any(c.condition_id == FIELD_DC for c in ctx.actor.conditions.values()):
        return None
    source = str(ctx.typed.get('option_of') or ctx.typed.get('source') or '').split('#')[0]
    if not is_field_formula(source):
        return None
    # Save hooks shape the subject's bonus: -2 is the caster's printed +2 DC.
    return {'bonus': -2}


COURT_DISCOUNT = 'alchemy_court_formula_discount'


@hook('technique_used')
def court_formula_discount(ctx: Any) -> None:
    """"Once per turn when you use Field Formula, reduce its CP cost by 1, minimum 0".

    Paid as it resolves: the CP is refunded through the shared technique_costs seam, so the
    fighter's real Path pool is the one refunded (Qi, Stamina or Resonance, combat/ext/cp_pools.py)
    and a refund can never cross the technique's own cost floor. A formula whose listed CP cost
    the fighter cannot pay in full is still unavailable to them; that remainder is the retained
    rider. Inert without the Court's own condition, and once spent the turn.
    """
    from . import cp_pools
    from ..technique_costs import refund

    actor = ctx.actor
    held = next((c for c in actor.conditions.values() if c.condition_id == COURT), None)
    if held is None or not actor.active or actor.turn_flags.get(COURT_DISCOUNT):
        return
    if not is_field_formula(str(ctx.typed.get('option_of') or ctx.typed.get('source') or '').split('#')[0]):
        return
    pool = cp_pools.of(actor)
    listed = tuple(ctx.action.costs or ())
    if not pool or not any(resource == pool and int(amount) >= 1 for resource, amount in listed) or pool not in actor.resources:
        return
    if not refund(ctx.engine, actor, ctx.source, listed, pool, 1, f'passive:{COURT_ID}'):
        return
    actor.turn_flags[COURT_DISCOUNT] = True


@effect('returning_breath_choice')
def returning_breath(ctx: Any, row: dict[str, Any]) -> None:
    from dataclasses import replace
    from . import needle
    from ..typed_executor import _default_subject, run_effects

    options = {
        'end_deafened': {'type': 'remove_condition', 'condition': 'deafened'},
        'end_blinded': {'type': 'rider', 'evidence': 'GM: end Blinded only if caused by smoke, powder, poison, or alchemical irritation.'},
        'stand': {'type': 'remove_condition', 'condition': 'prone'},
        'next_con_save': {'type': 'advantage', 'on': 'the next Constitution saving throw',
                          'duration': 'until_start_of_your_next_turn'},
    }
    labels = {'end_deafened': 'End Deafened', 'end_blinded': 'End qualifying Blinded (GM)',
              'stand': 'Stand from Prone without spending movement',
              'next_con_save': 'Advantage on the next Constitution saving throw'}
    for subject in _default_subject(ctx, row, harmful=False):
        chosen = needle.ask(ctx.engine, ctx.intent,
            needle.checkpoint_id(ctx.engine, 'RETURNING_BREATH', ctx.source, subject.entity_id),
            subject, 'choice:needle.returning_breath', list(options), labels=labels,
            prompt=f'Smoke of Returning Breath: {ctx.action.display_name} — choose a benefit for {subject.display_name}',
            name='Smoke of Returning Breath',
            preferred=['next_con_save'], minimum=0, maximum=1, allow_decline=True,
            target_id=subject.entity_id)
        if chosen and chosen[0] in options:
            run_effects(replace(ctx, target=subject, targets=[subject]),
                        [{**options[chosen[0]], 'applies_to': 'target'}])


@effect('court_cauldron_damage')
def court_damage_state(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    ctx.engine._remove_condition(ctx.actor, COURT, ctx.source)
    ctx.engine._apply_condition(ctx.actor, COURT, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, row, ctx.actor, condition=True),
        data={'label': 'Court of the Three-Legged Cauldron: failed-save damage',
              'amount': ctx.formula('key_ability_modifier')})


#: The Court's printed extra damage types ("extra Acid, Fire, Poison, or Force damage").
COURT_TYPES = ('acid', 'fire', 'poison', 'force')


@hook('after_save_resolved')
def court_failed_save(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    from . import needle
    from .. import zones

    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == COURT), None)
    if held is None or not failed or subject.team_id == ctx.actor.team_id:
        return
    source = printed_source(ctx)
    # Owner source text establishes Alchemy membership, including legacy TAL ids.
    if not alchemy_source(source):
        return
    if not any(zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == held.source_definition_id
               and ctx.engine._footprint_intersects(subject, zone.affected_cells)
               for zone in zones.typed_zones(ctx.engine)):
        return
    spent = 'condition:typed.alchemy_court_spent.' + ctx.actor.entity_id
    if any(c.condition_id == spent for c in subject.conditions.values()):
        return
    # This choice is itself one of the printed Acid, Fire, Poison or Force choices, so Seven-Flavor Furnace
    # substitutes into it like any other: an owner who prepared types is offered them here, and a formula that
    # offers no damage type of its own (Binding Dregs) can still be the first thing that opens preparation.
    prepared = declared_types(ctx, subject=subject)
    kinds = list(dict.fromkeys([*prepared, *COURT_TYPES]))
    chosen = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'CAULDRON_DAMAGE', ctx.source, subject.entity_id), ctx.actor,
        'choice:needle.cauldron_damage', kinds,
        labels={kind: f'{kind.capitalize()} damage' for kind in kinds},
        prompt=f'Court of the Three-Legged Cauldron: {ctx.action.display_name} — choose the extra damage type '
               f'{subject.display_name} takes after failing the save',
        name='Court of the Three-Legged Cauldron',
        minimum=1, maximum=1, preferred=['acid'], target_id=subject.entity_id)
    if not chosen:
        return
    # END_OF_CURRENT_TURN removes a condition at its applier's or holder's turn
    # end. Use the actual current actor, including an off-turn Alchemy save.
    ctx.engine._apply_condition(subject, spent, COURT_ID, ctx.engine.state.current_actor_id,
        expires_on='END_OF_CURRENT_TURN', data={'owner_id': ctx.actor.entity_id})
    from dataclasses import replace
    from ..typed_executor import run_effects

    run_effects(replace(ctx, targets=[subject], target=subject), [{
        'type': 'damage', 'applies_to': 'target', 'flat': max(0, int(held.data['amount'])),
        'damage_types': [chosen[0]], 'formula': 'none'}])
