"""Read actual scene possessions through the existing native inventory ledger.

Consumers: scene tool use, prepared-map/Anchor identity and other source-owned
procedures. This transient query view creates no fight, turn, initiative, item
or roll. Actual sealed bundle definitions and permanent encounter conditions
feed the same possession, remaining-quantity and hand-occupancy contracts used
in combat. A source absent from the party is not reconstructed or fabricated.
"""
import json
from .journey_assets import JourneyAssetContext
from .gate2_runtime_models import ActorState, ActionDefinition, ConditionInstance


class JourneyInventoryContext(JourneyAssetContext):
    def __init__(self, session):
        super().__init__(session)
        self.typed_bundle_documents = [actor['bundle'] for actor in session.state['actors'].values()]
        self.action_catalog = {row['source_definition_id']: ActionDefinition.model_validate(row)
            for bundle in self.typed_bundle_documents for row in bundle['action_catalog']}
        self.typed_passive_rows = {bundle['actor_id']: bundle.get('typed_passives', [])
            for bundle in self.typed_bundle_documents}
        self.state.state_version = session.state['revision']
        self.state.current_actor_id = None
        for aid, actor in session.state['actors'].items():
            template = actor['bundle']['actor_template']
            snapshot = actor.get('encounter_snapshot') or {}
            values = {key: value for key, value in template.items() if key in ActorState.model_fields}
            values.update(entity_id=aid, position=actor['position'], resources=actor['resources'],
                team_id=str(actor.get('team_id') or aid), movement_remaining_ft=0,
                current_hp=snapshot.get('current_hp', template['maximum_hp']),
                temporary_hp=snapshot.get('temporary_hp', 0),
                active=bool(snapshot.get('active', 1)), life_state=snapshot.get('life_state') or None,
                conditions={key: ConditionInstance.model_validate(json.loads(text))
                    for key, text in snapshot.get('conditions', {}).items()},
                resource_maximums={row['resource_id']: row['maximum'] for row in template['resources']})
            self.state.actors[aid] = ActorState.model_validate(values)

    def _update_object(self, *args, **kwargs):
        raise ValueError('A scene inventory query cannot create or update an object.')


def possessions(session, actor_id):
    """Current real usable carried identities; no inferred or granted items."""
    from .item_uses import possessions as native
    context = JourneyInventoryContext(session)
    return native(context, context.state.actors[actor_id])


def held_possessions(session, actor_id):
    """Current real hand identities, including retained Draw/Stow/transfer state."""
    from .ext.scoundrel_riders import held_possessions as native
    context = JourneyInventoryContext(session)
    return native(context, context.state.actors[actor_id])
