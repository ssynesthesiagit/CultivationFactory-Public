"""Scenario-only setup actions that a fight's menu must offer.

Since ad49b65fd an action with no action economy is a turn intent only when it declares
``parameters['free_primary']`` (combat/primary_intents.py ``allows_primary``); otherwise
``action_legality`` answers PARENT_OPTION and the menu never lists it, so a test that
drives its fixture through ``candidate()`` fails with "AssertionError: <setup name>".
Build or mark every such row here, so a new scenario cannot forget the flag.
"""
from typing import Any

from combat.gate2_runtime_models import ActionDefinition


def declare_free(row: Any) -> Any:
    """Mark a scenario-only economy-NONE row (dict or ActionDefinition) as a declared free activation.

    A dict is updated in place and returned; an ActionDefinition is copied. Existing parameters are kept and a
    row that has an economy (Action, Bonus Action, Reaction) is returned unchanged.
    """
    if isinstance(row, ActionDefinition):
        if str(getattr(row.economy, 'value', row.economy)) != 'NONE':
            return row
        return row.model_copy(update={'parameters': {**(row.parameters or {}), 'free_primary': True}})
    if str(getattr(row.get('economy'), 'value', row.get('economy'))) == 'NONE':
        row.setdefault('parameters', {})['free_primary'] = True
    return row


def free_setup_action(owner_id: str, source_id: str, name: str, effects: list, *, target_kind: str = 'SELF',
                      range_ft: int | None = None, costs: list | None = None, typed_source: str | None = None,
                      numbers: dict | None = None, parameters: dict | None = None) -> dict:
    """A typed economy-NONE setup action, declared free, as a bundle ``action_catalog`` row."""
    typed = {'effects': effects, 'numbers': numbers if numbers is not None else {}, 'riders': [],
             'duration': {'kind': 'instant'}}
    if typed_source:
        typed['source'] = typed_source
    row = {'source_definition_id': source_id, 'display_name': name, 'owner_id': owner_id, 'economy': 'NONE',
           'resolution_kind': 'TYPED', 'target_kind': target_kind, 'costs': costs or [],
           'parameters': {'typed': typed, **(parameters or {})}}
    if range_ft is not None:
        row['range_ft'] = range_ft
    return declare_free(row)


def apply_transform(bundles: list, transform) -> None:
    """Run a fixture's ``bundle_transform`` and declare every economy-NONE row it adds as a free activation.

    A fixture transform adds scenario rows (conditions to set, damage to deal, an attack to repeat) that a test then
    drives through ``candidate()``. Declaring them here, once, means a new scenario cannot forget the flag. A row that
    states ``free_primary`` itself (True or False) keeps its own answer. Replaced bundles are left entirely
    untouched because their rows may be compiled rather than fixture-owned.
    """
    from combat.canonical import canonical_sha256
    known = [(bundle, {row['source_definition_id'] for row in bundle['action_catalog']}) for bundle in bundles]
    transform(bundles)
    for (original, before), bundle in zip(known, bundles):
        if bundle is not original:
            continue
        changed = False
        for row in bundle['action_catalog']:
            if (row['source_definition_id'] not in before and str(getattr(row.get('economy'), 'value', row.get('economy'))) == 'NONE'
                    and 'free_primary' not in (row.get('parameters') or {})):
                declare_free(row)
                changed = True
        if changed:
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
