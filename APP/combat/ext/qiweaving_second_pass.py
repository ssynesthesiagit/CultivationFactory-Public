"""Chosen saving-throw protection and the Qiweaving concentration Insight.

Newly compiled Modulation variants seal a shared per-turn gate. Historical
variants without that stamp retain their previous behavior. Chosen protection
is selected at activation and recorded on any resulting zone, using perceived area recipients.
No feature/source is inferred from a live opponent's hidden sheet.
"""
from __future__ import annotations

import copy
from typing import Any
from . import effect, hook, note
from .needle import ask, checkpoint_id, answerable
from .choice_prompt import action_context
from .d20_rewrite import Rule, register

GENTLE = 'TAL_QIWEAVING_GENTLE_MODULATION'
GATE = 'once_per_turn:qiweaving_modulation'


@effect('chosen_save_protection', harmful=False)
def protection_marker(ctx: Any, row: dict[str, Any]) -> None:
    """Compile-time descriptor; the save hook resolves the benefit."""


@effect('qiweaving_concentration_reroll', harmful=False)
def reroll_marker(ctx: Any, row: dict[str, Any]) -> None:
    """The compiled d20_rewrite row owns this passive; no active effect."""


@hook('compile_action')
def modulation_gate(action: Any, info: dict[str, Any]) -> Any:
    typed = (action.parameters or {}).get('typed') or {}
    mid = (typed.get('modifier') or {}).get('id')
    mechanic = ((info.get('mechanics') or {}).get(mid) or {})
    # Source identity, not name matching; the owner explicitly labels this group.
    if not mid or (mechanic.get('modifier') or {}).get('group') != 'Modulation':
        return None
    parameters = copy.deepcopy(action.parameters)
    typed = parameters['typed']
    typed['qiweaving_modulation_gate'] = True
    if mid == GENTLE:
        typed['chosen_save_protection'] = True
        typed['effects'] = [r for r in typed.get('effects') or [] if r.get('type') != 'chosen_save_protection']
    return action.model_copy(update={'parameters': parameters})


@hook('candidate_allowed')
def modulation_available(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    if typed.get('qiweaving_modulation_gate'):
        return not bool(actor.turn_flags.get(GATE))
    return None


@hook('technique_accepted')
def modulation_spent(engine: Any, actor: Any, action: Any) -> None:
    if (action.parameters.get('typed') or {}).get('qiweaving_modulation_gate'):
        actor.turn_flags[GATE] = True
        note(engine, action.source_definition_id, actor, 'Apply Modulation: one Modulation used this turn.')


def _chosen(ctx: Any) -> set[str]:
    key = 'qiweaving_gentle_recipients'
    if key not in ctx.damage_cache:
        from ..target_knowledge import located
        recipients = [a for a in ctx.targets if a.active and located(ctx.engine, ctx.actor, a)]
        ceiling = min(len(recipients), max(1, int(ctx.numbers.get('key_mod') or 0)))
        preferred = [a.entity_id for a in recipients if a.team_id == ctx.actor.team_id][:ceiling]
        if not answerable(ctx.engine, ctx.actor):
            ctx.damage_cache[key] = preferred
            return set(preferred)
        ctx.damage_cache[key] = ask(
            ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'gentle_modulation', ctx.actor.entity_id), ctx.actor,
            'choice:needle.gentle_modulation', [a.entity_id for a in recipients],
            labels={a.entity_id: f'Protect {a.display_name}' for a in recipients},
            minimum=0, maximum=ceiling, preferred=preferred, default='decline', name='Gentle Modulation',
            prompt_context=action_context(ctx.engine, ctx.actor, ctx.source, ctx.actor),
            prompt=f'Gentle Modulation: choose up to {ceiling} creatures in the area to automatically succeed on saving throws against {ctx.action.display_name}. If a successful save normally deals half damage, they take no damage instead. Effects without a saving throw still apply.') if recipients else []
    return set(ctx.damage_cache[key] or [])


@hook('before_target_reactions')
def choose_protection(ctx: Any) -> None:
    if ctx.typed.get('chosen_save_protection'):
        _chosen(ctx)


@hook('zone_created')
def save_protection(ctx: Any, zone: Any) -> None:
    if ctx.typed.get('chosen_save_protection'):
        zone.trigger_profile['qiweaving_gentle_protection'] = {
            'recipients': sorted(_chosen(ctx)), 'source': ctx.source,
            'owner': ctx.actor.entity_id}


@hook('zone_trigger_context')
def restore_protection(ctx: Any, zone: Any, creature: Any, moment: str) -> None:
    protection = zone.trigger_profile.get('qiweaving_gentle_protection')
    if (not isinstance(protection, dict) or protection.get('source') != zone.source_definition_id
            or protection.get('owner') != zone.owner_id):
        return
    ctx.typed['chosen_save_protection'] = True
    ctx.damage_cache['qiweaving_gentle_recipients'] = list(protection.get('recipients') or [])


@hook('automatic_save_success')
def gentle_success(ctx: Any, subject: Any, effect: dict[str, Any]) -> bool | None:
    if not ctx.typed.get('chosen_save_protection') or subject.entity_id not in _chosen(ctx):
        return None
    ctx.damage_cache.setdefault('qiweaving_gentle_half', {})[subject.entity_id] = any(r.get('type') == 'half_damage' for r in effect.get('on_success') or [])
    note(ctx.engine, ctx.source, ctx.actor, f'Gentle Modulation: {subject.display_name} automatically succeeds on this saving throw.', (subject,))
    return True


@hook('evasion')
def gentle_half_damage(ctx: Any, subject: Any, ability: str, failed: bool, effects: Any) -> bool | None:
    if ctx.typed.get('chosen_save_protection') and not failed and subject.entity_id in _chosen(ctx):
        # Evasion suppresses the success damage only for save-for-half effects.
        if ctx.damage_cache.get('qiweaving_gentle_half', {}).get(subject.entity_id):
            return True
    return None


def calm_technique(engine: Any, holder: Any, rc: Any) -> bool:
    if rc.source_id != 'system:combat.concentration' or holder.actor.concentration is None:
        return False
    source = holder.actor.concentration.source_definition_id
    action = engine.action_catalog.get(source)
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return typed.get('sphere') == 'tianxia.sphere.qiweaving' or bool(typed.get('qiweaving_modulation_gate'))


register(Rule('qiweaving_calm_hands', 'Calm Hands, Clear Current', rolls=('save',),
              limit='fight', guard=calm_technique, ai=lambda engine, holder, rc: True))
