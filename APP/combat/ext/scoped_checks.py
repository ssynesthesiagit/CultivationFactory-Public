"""Scoped ability-check modes and explicit escape choices (Iron-Bone first user).

``check_against`` self-effect: abilities, optional skills, against, mode, ordinary duration fields.
An omitted skills list retains the legacy all-skills behavior for that ability.
Only a compiled owned source grants it. ``typed_executor.check_mode(..., hazards=)``
reads the stored rule before a matching check, never a save or unrelated check.
The existing compile_actions/candidate_allowed hooks offer Strength (Athletics)
and Dexterity (Acrobatics) escape actions only while a matching owned buff is active.
Players select the skill on their turn through the ordinary action menu; AI chooses
an action normally. No reaction, extra resource cost or new expiry is introduced.

``escape_modes`` is the shared public helper used by typed_executor and trap.
Explicit choices read only their own ability/skill; legacy mixed-skill escapes retain
their prior unscoped modes and bonus rather than borrowing STR Advantage for DEX.
"""
from __future__ import annotations

from typing import Any

from . import effect, hook

CONDITION = "condition:typed.check_against"


@hook('compile_actions')
def movement_check_action(info):
    """Reachable GM-adjudicated movement check, separate from Hide or movement.

    This general scene-check caller supplies explicit issues to contextual check
    providers (Sound, and future terrain/sensory providers). It grants no movement,
    concealment or guessed DC. Live providers opt the scene into this check via
    scene_check_relevant; the GM supplies its constraints and difficulty.
    """
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.movement_check",
        display_name='Check movement: move quietly', owner_id=info['actor_id'],
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'effects': [{'type': 'scene_movement_check'}],
                    'numbers': info['numbers'], 'duration': {'kind': 'instant'},
                    'manual_inline_choice': True, 'gm_adjudication': True}, 'expected_damage': 0,
                    'scene_check_purpose': 'quiet_movement',
                    'description': 'Roll Dexterity (Stealth) to move quietly against a difficulty set by the GM. '
                        'Choose whether sound is the only obstacle or sight also matters. No action or cultivation '
                        'points; this check alone does not move you or make you Hidden.'})]


@hook('candidate_allowed')
def relevant_scene_check(engine, actor, candidate, action):
    """Keep compiled scene checks dormant until a live provider opts them in."""
    purpose = (action.parameters or {}).get('scene_check_purpose') if action else None
    if not purpose:
        return None
    return None if _relevant(engine, actor, purpose) else False


def _relevant(engine, actor, purpose):
    from . import run
    return bool(any(run('scene_check_relevant', engine, actor, purpose)))


@hook('source_unavailable')
def scene_check_unavailable(engine, actor, action):
    """The same source-wide check for the compact-menu header (no target is chosen yet)."""
    purpose = (action.parameters or {}).get('scene_check_purpose') if action else None
    if purpose and not _relevant(engine, actor, purpose):
        return 'No part of this scene calls for that check.'
    return None


@effect('scene_movement_check')
def scene_movement_check(ctx, eff):
    """Journal the scene's sensory constraints and GM DC before any check dice."""
    from .needle import ask, checkpoint_id
    from ..typed_executor import resolve_opposed_check
    issues = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'movement_issues', ctx.source),
        ctx.actor, 'choice:needle.movement_issues', ['sound', 'mixed'], name='Move quietly',
        automatic=False, allow_decline=True, default='decline', gm_adjudication=True,
        labels={'sound': 'Only sound matters', 'mixed': 'Sound and sight matter'},
        prompt='Move quietly: choose the obstacles specified by the GM. This free Dexterity (Stealth) check '
            'does not move you or make you Hidden; it costs no cultivation points.')
    if not issues:
        return
    dc = select_gm_dc(ctx, 'Move quietly')
    if dc is None:
        return
    metadata = {'purpose': 'quiet_movement', 'source_actor_id': ctx.actor.entity_id,
                'issues': ['sound'] if issues[0] == 'sound' else ['sound', 'sight']}
    resolve_opposed_check(ctx, ctx.actor,
        {'kind': 'check', 'ability': 'DEX', 'skill': 'Stealth', 'metadata': metadata},
        {'kind': 'dc', 'dc': dc, 'label': 'GM-set movement difficulty'})


def select_gm_dc(ctx, name):
    """Enter an arbitrary nonnegative GM-set DC through journaled digit choices.

    Shared scene-check protocol. No fixed DC menu, invented AI difficulty,
    speculative roll, persistent object or truncation of legal difficulties.
    Players enter the GM's number; the actual check rolls only after Done.
    """
    from .needle import ask, checkpoint_id
    digits = ''
    step = 0
    while True:
        options = list('0123456789') + (['done', 'clear'] if digits else [])
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'scene_gm_dc', ctx.source, str(step), digits),
            ctx.actor, 'choice:needle.scene_gm_dc', options, name=name, automatic=False,
            allow_decline=True, default='decline', preferred=['done'] if digits else [], gm_adjudication=True,
            labels={**{d: 'Append ' + d for d in '0123456789'}, 'done': 'Use GM difficulty ' + (digits or '0'), 'clear': 'Clear the number'},
            prompt=f'{name}: enter the difficulty already set by the GM. Current number: {digits or "empty"}. No check is rolled until you finish.')
        if not picked:
            return None
        if picked[0] == 'done':
            return int(digits)
        digits = '' if picked[0] == 'clear' else digits + picked[0]
        step += 1


@effect("check_against")
def check_against(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    if not ctx.typed.get("source") or eff.get("applies_to") != "self":
        return
    ctx.engine._apply_condition(ctx.actor, CONDITION, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, eff, ctx.actor, condition=True),
        data={"rule": {"check_against": {"abilities": list(eff.get("abilities") or []),
              **({"skills": list(eff["skills"])} if eff.get("skills") else {}),
              "against": list(eff.get("against") or []), "mode": str(eff.get("mode") or "ADVANTAGE")}},
              "label": str(eff.get("evidence") or "Scoped check mode")})


def escape_skill_metadata(eff: dict[str, Any]) -> dict[str, Any]:
    """Receipt metadata for the skill modes actually consulted by an escape.

    Shared escape_checks and Trap use this with the same effect passed to
    escape_modes. An explicit skill is authoritative; an ability-only check
    is unskilled. Legacy mixed-skill checks consult both named skill modes for
    one draw with their precompiled better bonus, so mode_skills discloses both
    inputs without claiming a player selected either or changing that roll.
    """
    if eff.get("check_ability"):
        return {"skill": eff.get("check_skill") or None}
    return {"skill": None, "mode_skills": ["Athletics", "Acrobatics"]}


def escape_modes(actor: Any, eff: dict[str, Any], against: tuple[str, ...], *, engine: Any = None) -> set[str]:
    from ..typed_executor import check_modes

    if eff.get("check_ability"):
        return check_modes(actor, str(eff["check_ability"]), eff.get("check_skill"), hazards=against, engine=engine)
    return (check_modes(actor, "STR", "Athletics", engine=engine)
            | check_modes(actor, "DEX", "Acrobatics", engine=engine))


def _effects(value: Any):
    if isinstance(value, dict):
        if value.get("type") == "check_against":
            yield value
        for child in value.values():
            yield from _effects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _effects(child)


@hook("compile_actions")
def escape_choices(info: dict[str, Any]) -> list[Any] | None:
    # Inspect owned typed data; this also supports later abilities using the effect.
    sources = [key for key in sorted(info["owned_ids"])
               if any(set(row.get("against") or []).intersection(("grappled", "restrained"))
                      for row in _effects(info["mechanics"].get(key) or {}))]
    if not sources:
        return None
    from ..factory_compiler import _skill_bonus
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .trap import NETTED

    out = []
    for key, name, held, hazards in (
        ("escape_grapple", "Escape grapple", "condition:typed.grappled", ("grappled", "restrained")),
        ("trap_escape", "Escape the net", NETTED, ("restrained",)),
    ):
        for ability, skill, label in (("STR", "Athletics", "Strength"), ("DEX", "Acrobatics", "Dexterity")):
            bonus = _skill_bonus(info["owner_sheet"], skill, info["mods"].get(ability, 0))
            out.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.scoped.{key}.{ability.lower()}",
                display_name=f"{name}: {label} ({skill})", owner_id=info["actor_id"],
                economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
                parameters={"typed": {"effects": [{"type": key, "bonus": bonus,
                    "check_ability": ability, "check_skill": skill}], "numbers": info["numbers"],
                    "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 1,
                    "requires_condition": held, "scoped_check_sources": sources,
                    "scoped_check_hazards": list(hazards)}))
    return out


@hook("candidate_allowed")
def active_escape_choice(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:  # movement/end-turn candidates have no ActionDefinition
        return None
    sources = (action.parameters or {}).get("scoped_check_sources")
    if not sources:
        return None
    hazards = set(action.parameters["scoped_check_hazards"])
    for state in actor.conditions.values():
        if state.condition_id != CONDITION or state.source_actor_id != actor.entity_id:
            continue
        source = engine.action_catalog.get(state.source_definition_id)
        owned = ((source.parameters or {}).get("typed") or {}).get("source") if source else None
        rule = ((state.data or {}).get("rule") or {}).get("check_against") or {}
        if owned in sources and hazards.intersection(rule.get("against") or []):
            return None
    return False


@effect('contextual_check', harmful=False)
def contextual_check(ctx, spec):
    """Roll against a native, revision-bound subject offered by its producer.

    Used by Thread's line checks. A provider supplies actual active subject ids,
    each with a plain ``label`` and, for a creature subject, that creature's entity
    id as ``against``. Arbitrary actor ids, labels, a bare skill or a freeform
    approval do not supply scope. The committed receipt binds
    scope/subject/against/ability/skill to this roll, and a named creature makes the
    roll an ordinary check against it, so every source/target-qualified resolver
    hook (``typed_executor.check_modes``'s ability_check_mode) applies here too.
    Other source effects may use the same seam without changing ordinary checks.
    """
    from . import run_strict
    from .needle import ask, checkpoint_id
    from .ability_source import combine_modes
    from ..typed_executor import check_modes
    subjects = {}
    for rows in run_strict('contextual_check_subjects', ctx, spec):
        subjects.update(rows)
    if not subjects:
        raise ValueError('This check needs an active subject supplied by its source.')
    if not all(isinstance(row, dict) and isinstance(row.get('label'), str) for row in subjects.values()):
        raise ValueError('Each check subject needs a plain label.')
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'contextual_check_subject', ctx.source),
        ctx.actor, 'choice:needle.contextual_check_subject', list(subjects),
        labels={subject_id: row['label'] for subject_id, row in subjects.items()},
        name=ctx.action.display_name, prompt='Choose the actual line or object this check involves.')
    checks = spec['checks']
    skill = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'contextual_check_skill', ctx.source),
        ctx.actor, 'choice:needle.contextual_check_skill', list(checks),
        labels={s: s for s in checks}, name=ctx.action.display_name,
        prompt='Choose the ability check you are making. Action, no CP.')
    if not selected or not skill:
        return
    ability = checks[skill[0]]['ability']
    against_id = subjects[selected[0]].get('against')
    against = ctx.engine.state.actors.get(against_id) if against_id else None
    if against_id and against is None:
        raise ValueError('This check names a creature that is not on the battlefield.')
    frame = {'scope': spec['scope'], 'subject': selected[0],
             'against': against.entity_id if against else None, 'skill': skill[0], 'ability': ability}
    modes = check_modes(ctx.actor, ability, skill[0], engine=ctx.engine, against_creature=against)
    modes.update(mode for mode in run_strict('contextual_check_modes', ctx.engine, ctx.actor, frame)
                 if mode in ('ADVANTAGE', 'DISADVANTAGE'))
    from . import floored, run
    # The same seams the typed check resolver uses (typed_executor.check): every check_bonus
    # provider (Exhaustion's penalty, Invoke the Ledger's die -- spent once, here) adds to the
    # compiled skill bonus before the roll, and the check_floor provider (Complete Mandala
    # Auspice) may raise the total after it. No DC is known for a line check, so no floor is spent.
    bonus = int(checks[skill[0]]['bonus']) + sum(int(n) for n in run('check_bonus', ctx, ctx.actor)
        if isinstance(n, int) and not isinstance(n, bool))
    with ctx.engine.d20_scope({'kind': 'check', 'actor_id': ctx.actor.entity_id,
            'source_id': ctx.source, 'skill': skill[0], 'ability': ability}):
        roll = ctx.engine.roller.d20(modifier=bonus, actor_id=ctx.actor.entity_id,
            reason='CHECK:' + ctx.source, mode=combine_modes(modes))
        roll = floored(ctx.engine, ctx.actor, roll, None)
    ctx.engine._record_roll(roll)
    ctx.engine._append_event('CHECK_ROLLED', ctx.source, actor_id=ctx.actor.entity_id,
        payload={'actor': roll.model_dump(mode='json'), 'skill': skill[0], 'ability': ability,
                 'check_context': frame})
