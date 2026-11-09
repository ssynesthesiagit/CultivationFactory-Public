"""Long-rest library choices and Hidden Sleeve Adept's initiative preparation.

The pre-fight form records earlier decisions; it never performs a long rest.
No choice is opened inside match_start. A family-only prepared slot remains
separate from the general pool, so it cannot pay for an unrelated formula.
Shared helpers library_available and library_read_mode serve talismans.py's
formula consumption and Read the Script check. No other module owns this slot.
"""
from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id
from .talisman_affinity import FAMILIES
from .talismans import PREPARED, TALENT

ADEPT = 'insight.hidden-sleeve-adept'
LIBRARY = TALENT + 'formula_library'
LIBRARY_STATE = 'condition:typed.talisman_library'
LIBRARY_SLOT = 'resource:named.library_talisman'
FAMILY_NAMES = tuple(sorted({name for names in FAMILIES.values() for name in names}))


@hook('compile_actions')
def library_ready_action(info: dict) -> list | None:
    if LIBRARY not in (info.get('owned_ids') or []):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.library_ready",
        owner_id=info['actor_id'], display_name='Ready a Formula Library talisman',
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF',
        parameters={'player_only': True, 'library_ready': True,
                    'description': 'Use your Action to ready one carried talisman of the family selected for '
                                   'your Formula Library extra prepared slot. This does not change that family.',
                    'typed': {'source': LIBRARY, 'sphere': 'tianxia.sphere.talismans',
                              'numbers': dict(info['numbers']), 'riders': [],
                              'effects': [{'type': 'talisman_library_ready'}], 'duration': {'kind': 'instant'}}})]


@hook('candidate_allowed')
def library_ready_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not action.parameters.get('library_ready'):
        return None
    return actor.resources.get(LIBRARY_SLOT, 0) == 0 and any(
        row.condition_id == LIBRARY_STATE and row.data.get('benefit') == 3 for row in actor.conditions.values())


@effect('talisman_library_ready')
def library_ready(ctx: Any, row: dict) -> None:
    if not library_ready_allowed(ctx.engine, ctx.actor, None, ctx.action):
        return
    ctx.engine._gain_resource(ctx.actor, LIBRARY_SLOT, 1, ctx.source)
    note(ctx.engine, LIBRARY, ctx.actor, f'{ctx.actor.display_name} readies a talisman in the Formula Library family slot.')


@hook('compile_resources')
def library_resource(info: dict) -> list | None:
    if LIBRARY not in (info.get('owned_ids') or []):
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=LIBRARY_SLOT, initial=0, maximum=1)]


def _settings(bundle: dict) -> dict:
    return next((row.get('parameters') or {} for row in bundle.get('action_catalog') or []
                 if (row.get('parameters') or {}).get('talisman') == 'ready'), {})


def _integer(key: str, label: str, help_text: str, maximum: int, default: int) -> dict:
    return {'id': key, 'label': label, 'help': help_text, 'kind': 'integer_range_list',
            'count': 1, 'item_label': label, 'minimum': 0, 'maximum': maximum, 'default': [default]}


@hook('prefight_setup_choices')
def preparation_choices(bundle: dict) -> list | None:
    settings = _settings(bundle)
    out = []
    if settings.get('talisman_sleeve_adept'):
        maximum = next((int(row['maximum']) for row in bundle['actor_template']['resources']
                        if row['resource_id'] == PREPARED), 0)
        out.extend([
            _integer('sleeve_starting_prepared', 'Talismans ready before Initiative',
                     'How many carried talismans are already prepared before rolling Initiative? '
                     'Hidden Sleeve Adept adds 1 to your Prepared Talisman Limit.', maximum, maximum),
            _integer('sleeve_initiative_ready', 'Hidden Sleeve Adept: ready one at Initiative',
                     'Choose 1 to ready one more carried talisman when Initiative is rolled, '
                     'or 0 to decline. This costs no Action and cannot exceed your Prepared Talisman Limit.', 1, 0)])
    if settings.get('talisman_library'):
        out.extend([
            _integer('library_family', 'Formula Library: family chosen at your last long rest',
                     'Record a family represented in your library: 0 = no recorded choice; '
                     + '; '.join(f'{index} = {name}' for index, name in enumerate(FAMILY_NAMES, 1))
                     + '. This records your earlier choice; it does not change your library.', len(FAMILY_NAMES), 0),
            _integer('library_benefit', 'Formula Library: benefit chosen at your last long rest',
                     'For that family, choose 0 = no recorded benefit; 1 = crafting DC reduced by 1; '
                     '2 = crafting CP reduced by 1 (minimum 0); 3 = one additional prepared talisman; '
                     '4 = Advantage on Read the Script. The choice lasts until your next long rest. '
                     'Crafting takes place outside this fight.', 4, 0)])
    return out or None


@hook('match_start')
def seed_preparation(engine: Any) -> None:
    for bundle in getattr(engine, 'typed_bundle_documents', ()) or ():
        actor = engine.state.actors.get(bundle.get('actor_id'))
        if actor is None:
            continue
        settings = _settings(bundle)
        picks = (bundle.get('prefight') or {}).get('setup_choices') or {}
        if settings.get('talisman_sleeve_adept') and 'sleeve_starting_prepared' in picks:
            start = int(picks['sleeve_starting_prepared'][0])
            maximum = int(actor.resource_maximums[PREPARED])
            start = max(0, min(start, maximum))
            difference = int(actor.resources[PREPARED]) - start
            if difference > 0:
                engine._spend_resource(actor, PREPARED, difference, ADEPT)
            if picks.get('sleeve_initiative_ready') == [1] and start < maximum:
                engine._gain_resource(actor, PREPARED, 1, ADEPT)
                note(engine, ADEPT, actor, f'{actor.display_name} readies one carried talisman at Initiative '
                     'with Hidden Sleeve Adept, without using an Action.')
        index = (picks.get('library_family') or [0])[0]
        benefit = (picks.get('library_benefit') or [0])[0]
        if not settings.get('talisman_library') or not 1 <= index <= len(FAMILY_NAMES) or benefit not in (1, 2, 3, 4):
            continue
        family = FAMILY_NAMES[index - 1]
        engine._apply_condition(actor, LIBRARY_STATE, LIBRARY, actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'family': family, 'benefit': benefit,
                  'label': f'Formula Library: {family}; ' + {1: 'crafting DC -1', 2: 'crafting CP -1',
                      3: 'one extra prepared talisman of this family', 4: 'Advantage on Read the Script'}[benefit]})
        if benefit == 3:
            engine._gain_resource(actor, LIBRARY_SLOT, 1, LIBRARY)


def library_available(actor: Any, formula: str) -> bool:
    """Whether the library's one additional prepared slot can supply this formula."""
    return actor.resources.get(LIBRARY_SLOT, 0) > 0 and any(
        row.condition_id == LIBRARY_STATE and row.data.get('benefit') == 3
        and (row.data.get('family') in FAMILIES.get(formula, ())
             or formula in {'talisman_wall', 'talisman_bomb', 'talisman_spirit', 'talisman_reflection'})
        for row in actor.conditions.values())


def library_read_mode(ctx: Any) -> set[str]:
    """Apply the recorded benefit only to writing involving the selected family.

    The table describes unrepresented writing; AI never invents its family.
    """
    recorded = next((row for row in ctx.actor.conditions.values()
                     if row.condition_id == LIBRARY_STATE and row.data.get('benefit') == 4), None)
    if recorded is None:
        return set()
    options = ['unrecorded', *FAMILY_NAMES]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'library_script_family', ctx.actor.entity_id),
                 ctx.actor, CHOICE + 'library_script_family', options,
                 labels={name: 'Writing family not established' if name == 'unrecorded' else name + ' family'
                         for name in options}, preferred=['unrecorded'], automatic_options=['unrecorded'],
                 prompt='Read the Script: which established formula family does this writing involve? '
                        'Your Formula Library grants Advantage only for ' + recorded.data['family'] + '.',
                 name='Formula Library', feature_id=LIBRARY)
    return {'ADVANTAGE'} if picked == [recorded.data['family']] else set()
