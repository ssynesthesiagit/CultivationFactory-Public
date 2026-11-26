"""Soul Splitting's free GM reference until separate-origin geometry is supported.

The printed fragment is an asset, never a second acting character. Existing
candidate admission measures from the owner, so creating a summon alone cannot
implement Second Origin. Compile a reference rather than charge for a placeholder;
the existing candidate veto also closes the paid action in older saved catalogs.
No actor position, catalog or core function is changed at runtime.
"""
from copy import deepcopy

from . import effect, hook, note
from .ability_source import mechanic_of

SOURCE = 'tianxia.path.spirit_awakening.feature.soul_splitting'
REFERENCE = 'soul_splitting_reference'
LABEL = 'Soul Splitting — GM-run rules (no action or resource spent)'
EXPLANATION = (
    'Soul Splitting is GM-run: this button only shows instructions; it creates no fragment '
    'and spends no action or Resonance. To use the ability, the GM must spend your Action '
    'and 8 Resonance once, then place one soul fragment in a legal empty space within '
    '30 feet for this scene. The GM tracks its defenses, Hit Points, movement and '
    '300-foot tether, measures features from your chosen origin, and resolves one '
    'eligible Fragment Expression once on each of your turns after you spend Resonance '
    'on a Spirit Awakening Path or Subpath feature or use Mind Spike. If destroyed, it deals 4d10 Psychic damage '
    'to you ignoring Resistance and cannot be recreated until a Full Cultivation Session.'
)
# Head text for the table button. The shared selector wording in tabletop.py
# describes a choice "kept until you change it", which is wrong here: reading this
# reference stores nothing and changes no future activation, so it must say so.
REFERENCE_HEAD = (
    'Rules reference, not a choice: pressing this opens the GM-run rules below. '
    'It selects nothing, keeps no setting, and takes no action and costs no Resonance. '
    'To use Soul Splitting itself, the GM spends your Action and 8 Resonance (your Spirit '
    'Awakening Path resource) once, then places one soul fragment in an unoccupied space '
    'within 30 feet of you for the rest of the scene.'
)


@hook('compile_action')
def gm_reference(action, info):
    if SOURCE not in info['owned_ids'] or mechanic_of(action) != SOURCE:
        return None
    from ..gate2_runtime_models import EconomyKind

    parameters = deepcopy(action.parameters)
    parameters.update(inert=True, player_only=True, expected_damage=0, setting_only=True,
                      setting_description=REFERENCE_HEAD)
    parameters['typed'].update(
        soul_splitting_reference=True, effects=[{'type': REFERENCE}], options=[],
        duration={'kind': 'instant'}, riders=[], gm_text=EXPLANATION,
    )
    return action.model_copy(update={
        'display_name': LABEL, 'economy': EconomyKind.NONE, 'costs': (),
        'target_kind': 'SELF', 'range_ft': None, 'reach_ft': None,
        'parameters': parameters,
    })


@effect(REFERENCE)
def show_gm_rules(ctx, row):
    note(ctx.engine, ctx.source, ctx.actor, EXPLANATION)


@hook('candidate_allowed')
def refuse_legacy_placeholder(engine, actor, candidate, action):
    if mechanic_of(action) != SOURCE:
        return None
    # Serialized pre-fix actions remain loadable; they must not charge for an
    # unimplemented fragment. Only the compiled, free reference may be used.
    typed = action.parameters.get('typed') or {}
    return bool(typed.get('soul_splitting_reference') and action.parameters.get('setting_only') is True and not action.costs
                and str(action.economy) == 'NONE' and typed.get('effects') == [{'type': REFERENCE}]
                and typed.get('duration') == {'kind': 'instant'})
