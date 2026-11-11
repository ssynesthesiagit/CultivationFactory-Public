"""One way for a test to make a LOCAL_AUTO seat take a specific primary action.

The automatic seat's decision context carries ONE placeholder per cell-aimed action ("... - choose a square",
combat/placement_menu.py) and the controller aims it with the intent's ``placement_destination``; the exact-cell
candidates of ``engine.legal_candidates()`` are not in that context, and ManualControllerAdapter (and the service's own
bookkeeping) only know the listed ones. A test that names an exact candidate is therefore turned into the placeholder
plus that destination here, once, instead of in every test file.
"""
from combat.gate4_adapters import ManualControllerAdapter


def exact_candidate(combat, mid, candidate_id):
    return next((c for c in combat._load_session(mid).engine.legal_candidates() if c.candidate_id == candidate_id), None)


def fixed_primary(combat, mid, context, candidate_id, option_ids=()):
    """The ControllerChoice for ``candidate_id``: a listed candidate as it is, or an exact-cell one as its placeholder
    plus the ``placement_destination`` the automatic controller itself uses (combat/gate4_controller.py)."""
    adapter = ManualControllerAdapter
    if candidate_id in {c.candidate_id for c in context.legal_candidates}:
        return adapter(lambda _: (candidate_id, option_ids)).choose_primary_action(context)
    exact = exact_candidate(combat, mid, candidate_id)
    root = None if exact is None else next(
        (c for c in context.legal_candidates if c.metadata.get('placement_picker')
         and c.source_definition_id == exact.source_definition_id
         and c.metadata.get('effect_origin') == exact.metadata.get('effect_origin')
         and tuple(c.option_ids) == tuple(exact.option_ids)), None)
    if root is None:
        return adapter(lambda _: (candidate_id, option_ids)).choose_primary_action(context)  # the adapter's own refusal
    choice = adapter(lambda _: (root.candidate_id, option_ids)).choose_primary_action(context)
    return choice.model_copy(update={'intent': choice.intent.model_copy(update={'placement_destination': exact.destination})})


class FixedPrimary(ManualControllerAdapter):
    """A controller that always picks ``candidate_id`` (see ``fixed_primary``); reactions go to ``reaction_chooser``."""

    def __init__(self, combat, mid, candidate_id, option_ids=(), reaction_chooser=None):
        super().__init__(lambda _: (candidate_id, option_ids), reaction_chooser)
        self._fixed = (combat, mid, candidate_id, option_ids)

    def choose_primary_action(self, context):
        return fixed_primary(*self._fixed[:2], context, *self._fixed[2:])


def force_primary(combat, mid, actor, candidate_id, option_ids=()):
    """Install a controller that always picks ``candidate_id`` and put ``actor`` on LOCAL_AUTO."""
    real = combat.controller

    class FixedController:
        def choose_primary_action(self, context):
            return fixed_primary(combat, mid, context, candidate_id, option_ids)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = FixedController()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
