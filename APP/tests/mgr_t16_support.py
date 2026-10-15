"""Deterministic AI primary selection for T16 service choice regressions.

Information, movement and passage tests select a known legal primary through
the real auto-step route. The native controller still owns recipient choices;
no model server or transport is contacted.
"""
from combat.gate4_adapters import ManualControllerAdapter
from tests import worker2_support as S


def automatic(combat, table, mid, actor_id, name, *, at=None):
    engine = combat._load_session(mid).engine
    sources = {key for key, action in engine.action_catalog.items()
               if action.display_name == name}
    real = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            rows = [row for row in context.legal_candidates if row.source_definition_id in sources
                    and (at is None or row.metadata.get('placement_picker')
                         or row.destination and (row.destination.x, row.destination.y) == at[:2]
                         and (len(at) == 2 or row.destination.z == at[2]))]
            assert rows, name
            choice = ManualControllerAdapter(lambda _: (rows[0].candidate_id, ())).choose_primary_action(context)
            if at is not None and rows[0].metadata.get('placement_picker'):
                # The real service validates/binds this deferred square, exactly
                # as a local/model seat's two-stage placement intent does.
                from combat.gate2_runtime_models import Position
                choice = choice.model_copy(update={'intent': choice.intent.model_copy(update={
                    'placement_destination': Position(x=at[0], y=at[1], z=at[2] if len(at) > 2 else 0)})})
            return choice

        def __getattr__(self, key):
            return getattr(real, key)

    combat.controller = Controller()
    try:
        combat.set_controller_mode(mid, actor_id=actor_id, controller_mode='LOCAL_AUTO')
        return S.settle(table, mid, '', auto=True)
    finally:
        combat.controller = real
