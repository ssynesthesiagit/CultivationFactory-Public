"""Life's shared treatments on existing compile/effect/choice hooks.

New reviewed choose_patients rows seal their options and contact permission.
Old saved life_more_targets and purify_one rows retain their original paths.
Body-contact exceptions are recorded before compilation in
path_and_subpath.life_contact_permissions[feature_id]: talent_id, record_id,
note explaining physical continuity. Invalid/missing records keep touch range.
compile_action, compile_actions and choice_reactors are documented existing
hooks; no general engine seam or saved runtime field is introduced.
"""
from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any

from . import hook
from .needle import CHOICE, ask, checkpoint_id
from .choice_prompt import action_context
from .choice_costs import quote

P = 'tianxia.talent.life.'
PURIFY = 'LIFE_BASE_PURIFY_THE_PULSE'


def _contact_permission(sheet: dict, feature: str) -> bool:
    permissions = (sheet.get('path_and_subpath') or {}).get('life_contact_permissions')
    if not isinstance(permissions, dict):
        return False
    record = permissions.get(feature)
    return bool(isinstance(record, dict) and record.get('talent_id') == feature
                and all(isinstance(record.get(k), str) and record[k].strip() for k in ('record_id', 'note')))


@hook('compile_action')
def seal_treatment(action: Any, info: dict) -> Any:
    parameters = copy.deepcopy(action.parameters or {})
    typed = parameters.get('typed') or {}
    changed = False
    range_ft = action.range_ft
    for row in typed.get('effects') or []:
        if row.get('type') == 'life_more_targets' and row.get('choose_patients'):
            feature = P + ('pulse_array_treatment' if row.get('kind') == 'array' else 'shared_infirmary_hand')
            row['body_contact'] = str((info['owner_sheet'].get('identity') or {}).get('path') or '').lower().startswith('body')
            row['remote_contact'] = _contact_permission(info['owner_sheet'], feature)
            base = info['mechanics'].get(str(typed.get('source') or '')) or {}
            row['base_effects'] = copy.deepcopy(base.get('effects') or [])
            row['base_is_purify'] = typed.get('source') == PURIFY
            row['purify_options'] = copy.deepcopy((info['mechanics'].get(PURIFY) or {}).get('options') or [])
            if row.get('kind') == 'array':
                from ..typed_executor import mark_condition_id
                cl = int(info['numbers'].get('cl') or 1)
                range_ft = 5 if row['body_contact'] and not row['remote_contact'] else 30 if cl < 10 else 60 if cl < 15 else 120
                typed['range_ft'] = range_ft
                parameters['target_requires_condition'] = mark_condition_id('Pulse Seal', action.owner_id)
            changed = True
        if row.get('type') == 'purify_one' and row.get('choose_treatment'):
            row['purify_options'] = copy.deepcopy((info['mechanics'].get(PURIFY) or {}).get('options') or [])
            changed = True
    return action.model_copy(update={'parameters': parameters, 'range_ft': range_ft}) if changed else None


def treatment_description(ctx: Any) -> str:
    """Explain the base treatment being offered, without implying shared augments."""
    source = str(ctx.typed.get('source') or ctx.action.source_definition_id)
    if source == 'LIFE_BASE_MEND_THE_PULSE':
        return 'Mend the Pulse restores Hit Points. Instantaneous base treatment.'
    if source == 'LIFE_BASE_BORROWED_BREATH':
        return ('Borrowed Breath stabilizes a living patient at 0 Hit Points and grants Temporary HP '
                'up to their missing Hit Points; it does not restore consciousness. '
                'Base duration: 1 hour or until depleted.')
    if source == 'LIFE_BASE_READ_THE_PULSE':
        return ('Read the Pulse checks the living pattern for injury and conditions and places a Pulse Seal. '
                'The reading is Instantaneous; the seal remains until removed.')
    if source == PURIFY:
        return ('Purify the Pulse removes one chosen condition: Blinded, Deafened, Paralyzed or Poisoned. '
                'Instantaneous removal of the chosen condition; this does not end an ongoing source.')
    return f'{ctx.action.display_name} treats this patient.'


def treatment_context(ctx: Any, patient: Any, *, consent: bool = False) -> dict[str, str]:
    context = action_context(ctx.engine, ctx.actor, ctx.action.source_definition_id, patient)
    price = quote(ctx.action.costs) or '0 CP'
    context['cost'] = (f'No action or CP for the patient; caster pays {price} for the whole action.'
                       if consent else f'Included in the caster’s whole-action cost: {price}; no extra action or CP.')
    return context


def choose_purification(ctx: Any, options: list[dict], *, name: str) -> list[dict]:
    """Ask separately for this patient; AI receives only their represented states."""
    target = ctx.target
    held = {c.condition_id.removeprefix('condition:typed.') for c in target.conditions.values()}
    available = {str(i): option for i, option in enumerate(options)
                 if any(e.get('condition') in held for e in option.get('effects') or [])}
    if not available:
        return []
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'LIFE_TREATMENT', target.entity_id),
                   ctx.actor, CHOICE + 'life_treatment', list(available),
                   labels={k: v['label'] + ' from ' + target.display_name for k, v in available.items()},
                   preferred=sorted(available, key=lambda k: next((i for i, n in enumerate(('paralyzed', 'blinded', 'poisoned', 'deafened')) if any(e.get('condition') == n for e in available[k]['effects'])), 99))[:1], target_id=target.entity_id,
                   prompt_context=treatment_context(ctx, target),
                   prompt=f'{name}: {ctx.actor.display_name} uses {ctx.action.display_name} on {target.display_name}. '
                          f'{treatment_description(ctx)} Choose one Purify the Pulse treatment: '
                          'remove Blinded, Deafened, Paralyzed or Poisoned. Instantaneous removal; '
                          'this does not end an ongoing source. '
                          f'This is included in the whole action’s cost ({quote(ctx.action.costs) or "0 CP"}) '
                          'and uses no extra action or CP.')
    return copy.deepcopy(available[selected[0]]['effects']) if selected else []


def treat_additional(ctx: Any, eff: dict) -> None:
    from .. import relations, targeting
    from ..target_knowledge import can_see
    from ..typed_executor import bears_mark, run_effects
    from . import life_state

    engine, actor = ctx.engine, ctx.actor
    first = ctx.target or (ctx.targets[0] if ctx.targets else actor)
    cl = int(ctx.numbers.get('cl') or 1)
    band = 1 if cl < 5 else 2 if cl < 10 else 3 if cl < 15 else 4
    array = eff.get('kind') == 'array'
    reach = (30 if band <= 2 else 60 if band == 3 else 120) if array else 5
    max_count = len(engine.state.actors) if array else (1 if band == 1 else 2 if band == 2 else int(ctx.numbers.get('pb') or 2))
    body = eff.get('body_contact') and not eff.get('remote_contact')
    base = str(ctx.typed.get('source') or ctx.action.source_definition_id)
    breath = 'BORROWED_BREATH' in base and 'Greater Invigorate' not in ctx.action.display_name
    mend = 'MEND_THE_PULSE' in base
    from .creature_kinds import owns_modifier
    esoteric = owns_modifier(engine, actor, P + 'esoteric_vitality')
    patients = []
    for other in engine.state.actors.values():
        if not other.active or other is first or life_state.is_dead(other):
            continue
        distance = engine._distance_actor_to_actor(actor, other)
        sealed = bears_mark(other, actor.entity_id, 'Pulse Seal')
        if array and not sealed:
            continue
        limit = 5 if body else reach if array else 30 if band == 4 and sealed else 5
        if distance > limit or not can_see(engine, actor, other) or not targeting.line_of_effect(engine, actor, target=other):
            continue
        if mend and not esoteric and {str(t).lower() for t in other.creature_types} & {'undead', 'construct'}:
            continue
        if breath and other.current_hp >= other.maximum_hp:
            continue
        patients.append(other)
    if not patients:
        return
    patients.sort(key=lambda a: (relations.relation(engine, actor, a) != relations.ALLY, a.current_hp - a.maximum_hp, a.entity_id))
    choices = {a.entity_id: a.display_name for a in patients}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, 'LIFE_PATIENTS', str(eff.get('kind'))), actor,
                 CHOICE + 'life_patients', list(choices), labels=choices, maximum=min(max_count, len(patients)),
                 allow_decline=True, preferred=list(choices)[:max_count], default='all', target_id=first.entity_id,
                 prompt_context=treatment_context(ctx, first),
                 prompt=f"{eff['name']}: choose up to {min(max_count, len(patients))} additional willing patients. "
                        f'{treatment_description(ctx)} Choose each patient’s treatment separately. '
                        f'The whole action costs {quote(ctx.action.costs) or "0 CP"}, including the additional CP. '
                        'Body Refiners require physical contact '
                        'unless their imported sheet records permission for this talent.')
    # Only the base ability is shared, exactly as the printed talent states.
    rows = copy.deepcopy(eff['base_effects']) if 'base_effects' in eff else [
        copy.deepcopy(r) for r in ctx.typed.get('effects') or []
        if not r.get('source_modifier') and r.get('type') != 'life_more_targets']
    # A consenting patient is the recipient, including a different-team ally
    # or a willing neutral/opponent; do not let native ally lookup retarget it.
    for row in rows:
        if row.get('applies_to') == 'ally':
            row['applies_to'] = 'target'
    for patient in patients:
        if patient.entity_id not in picked:
            continue
        consent = ask(engine, ctx.intent, checkpoint_id(engine, 'LIFE_CONSENT', patient.entity_id), patient,
                      CHOICE + 'life_patient_consent', ['accept'], labels={'accept': 'Accept the treatment'},
                      preferred=['accept'] if relations.relation(engine, actor, patient) == relations.ALLY else [],
                      allow_decline=True, automatic=relations.relation(engine, actor, patient) == relations.ALLY,
                      default='first' if relations.relation(engine, actor, patient) == relations.ALLY else 'decline',
                      target_id=patient.entity_id,
                      prompt_context=treatment_context(ctx, patient, consent=True),
                      prompt=f"{eff['name']}: {actor.display_name} offers {patient.display_name} {ctx.action.display_name}. "
                             f'{treatment_description(ctx)} Accept it willingly? It costs you no action or CP; '
                             f'the caster pays {quote(ctx.action.costs) or "0 CP"} for the whole action.')
        if not consent:
            continue
        sub = replace(ctx, target=patient, targets=[patient], damage_cache={})
        treatment = rows
        if eff.get('base_is_purify') or any(r.get('type') == 'remove_condition' for r in rows):
            treatment = [r for r in rows if r.get('type') != 'remove_condition'] + choose_purification(
                sub, eff.get('purify_options') or [], name=eff['name'])
        run_effects(sub, treatment)


@hook('compile_actions')
def restorative_compositions(info: dict) -> list[Any] | None:
    """Use already compiled Purify variants: their effects, gates and payment survive."""
    if P + 'restorative_mend' not in info['owned_ids']:
        return None
    out = []
    purifies = [a for a in info['actions'] if (a.parameters.get('typed') or {}).get('source') == PURIFY]
    for mend in info['actions']:
        typed = mend.parameters.get('typed') or {}
        if not any(e.get('type') == 'purify_one' and e.get('choose_treatment') for e in typed.get('effects') or []):
            continue
        # Contact/shared-target modifiers stay separate; each composition is one
        # Mend/Breath followed by one Purify variant with its normal CP costs.
        for purify in purifies:
            ptyped = purify.parameters.get('typed') or {}
            if not any(e.get('source_modifier') for e in ptyped.get('effects') or []):
                continue
            if any(e.get('type') == 'life_more_targets' for e in ptyped.get('effects') or []):
                continue
            params = copy.deepcopy(mend.parameters)
            params['typed']['effects'] = [e for e in params['typed']['effects'] if e.get('type') != 'purify_one'] + copy.deepcopy(ptyped.get('effects') or [])
            # Replace Restorative's included 1 CP with the compiled Purify
            # portion, whose own minimum is zero. Free variants omit the cost
            # row entirely; they must still remove the included base payment.
            from ..factory_compiler import RESOURCE_IDS
            costs = dict(mend.costs)
            primary_pool = RESOURCE_IDS.get(info['primary'])
            costs[primary_pool] = costs.get(primary_pool, 0) - 1
            for pool, amount in purify.costs:
                costs[pool] = costs.get(pool, 0) + max(0, int(amount))
            costs = {pool: amount for pool, amount in costs.items() if amount}
            params['typed']['riders'] = list(dict.fromkeys([*(params['typed'].get('riders') or []), *(ptyped.get('riders') or [])]))
            if purify.parameters.get('life_seal_reach_body_refiner'):
                params['life_seal_reach_body_refiner'] = True
            # Keep touch range: the original Mend/Breath target remains authoritative.
            out.append(mend.model_copy(update={
                'source_definition_id': mend.source_definition_id + '.purify.' + purify.source_definition_id,
                'display_name': mend.display_name + ' / ' + purify.display_name,
                'parameters': params, 'costs': tuple(costs.items())}))
    return out or None


@hook('choice_reactors')
def treatment_choice_reactors(engine: Any) -> tuple[str, ...] | None:
    """Manual patient consent stays player-owned during an AI healer's turn."""
    if any(any(r.get('type') == 'life_more_targets' and r.get('choose_patients')
               for r in ((a.parameters or {}).get('typed') or {}).get('effects') or [])
           for a in engine.action_catalog.values()):
        return tuple(a.entity_id for a in engine.state.actors.values() if a.active)
    return None
