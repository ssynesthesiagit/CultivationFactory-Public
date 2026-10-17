"""Beastmastery ownership and activated Sovereign Pack Mind.

Owner rules: authority/typed_mechanics/rules_text.json. The paid Bonus Action
creates an ordinary one-minute condition through reviewed typing. Only that
source-owned grant enables an optional post-roll bonus. The integer round
receipt is persisted by the native table transaction.

Procession's undefined Resistance to Frightened remains a GM reminder, never
immunity. Encirclement's per-reactor Disengage exception requires a locked
engine seam; its speed-on-hit and movement clauses also remain reminders.
"""
from __future__ import annotations
from typing import Any
from . import hook

PROCESSION = 'TAL_BEASTMASTERY_TEN_THOUSAND_BEAST_PROCESSION'
ENCIRCLEMENT = 'TAL_BEASTMASTERY_PACK_ENCIRCLEMENT'
PACK_MIND = 'TAL_BEASTMASTERY_SOVEREIGN_PACK_MIND'
BLOCK = 'beastmastery_pack'
ALLY_SOURCES = ('tamer', 'rider')
PACK_MIND_RANGE_FT = 120
PACK_MIND_ROUND_FLAG = '_round_sovereign_pack_mind'
PACK_MIND_ACTIVE = 'condition:typed.sovereign_pack_mind'
PACK_MIND_CHOICE = 'choice:needle.beastmastery.pack_mind'


@hook('compile_block')
def pack_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Ownership marker only; keep compiling the ordinary Actions/modifier."""
    if block != BLOCK:
        return None
    return [{**row, 'block': BLOCK, 'kind': spec.get('kind'), 'keeps_compiling': True}]


def beast_allies(engine: Any, owner: Any) -> list[Any]:
    """Public recipient predicate used by Pack Mind and pack regression fixtures.

    Only active, present, same-side Tamer/Rider summons with this owner count.
    Ownership of unrelated summons never makes them Beast Allies.
    """
    return [beast for beast in engine.state.actors.values()
            if beast.active and beast.team_id == owner.team_id and beast.summon
            and beast.summon.get('source') in ALLY_SOURCES
            and str(beast.summon.get('owner') or '') == owner.entity_id
            and beast.summon.get('status', 'present') == 'present']


def holds(engine: Any, actor: Any, kind: str) -> bool:
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, BLOCK, kind) is not None


@hook('d20_bonus')
def sovereign_pack_mind_bonus(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Offer a grant after the die, before outcome; spend only on acceptance."""
    from . import needle
    context = engine.d20_context(roll) or {}
    kind = str(context.get('kind') or '')
    if kind not in {'attack', 'save', 'check'} or intent is None:
        return None
    roller = engine.state.actors.get(str(roll.actor_id or ''))
    if roller is None or not roller.active:
        return None
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (not owner.active or needle.incapacitated(owner)
                or not holds(engine, owner, 'sovereign_pack_mind')
                or owner.turn_flags.get(PACK_MIND_ROUND_FLAG) == engine.state.round_number
                or not any(c.condition_id == PACK_MIND_ACTIVE and c.source_actor_id == owner.entity_id
                           for c in owner.conditions.values())
                or roller not in beast_allies(engine, owner)
                or engine._distance_actor_to_actor(owner, roller) > PACK_MIND_RANGE_FT):
            continue
        source = str(context.get('source_id') or '')
        action = engine.action_catalog.get(source)
        action_name = getattr(action, 'display_name', None) or {'attack': 'attack', 'save': 'saving throw', 'check': 'ability check'}[kind]
        bonus = int(owner.proficiency_bonus or 2)
        chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, 'PACK_MIND', roll.roll_id),
                            owner, PACK_MIND_CHOICE, ['grant'],
                            labels={'grant': f'Add {bonus} to this roll'}, preferred=['grant'],
                            allow_decline=True, automatic=True, default='decline',
                            name='Sovereign Pack Mind', feature_id=PACK_MIND, target_id=roller.entity_id,
                            prompt=f"Sovereign Pack Mind: {roller.display_name}'s {kind} roll for {action_name} is {roll.total}. "
                                   f"Add {bonus} (your Proficiency Bonus) before the outcome is known? "
                                   "No additional cost; uses your one grant this round. You may decline and save it for another roll. "
                                   "Available only during the 1-minute effect, activated by a Bonus Action that expends Martial Focus once per long rest.",
                            prompt_context={'cost': 'No additional cost; one grant per round', 'action_name': action_name})
        if chosen != ['grant']:
            continue
        owner.turn_flags[PACK_MIND_ROUND_FLAG] = int(engine.state.round_number)
        return {'source_id': PACK_MIND, 'bonus': bonus, 'user_id': owner.entity_id}
    return None
