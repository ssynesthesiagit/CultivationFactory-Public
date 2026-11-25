"""Pure retreat-and-Dodge scoring used by the native local controller."""
from .gate2_runtime_models import CandidateKind
from .relations import NEUTRAL_TEAM


def score(context, actor, candidate):
    """Move away from perceived combatants, then Dodge, then end the turn."""
    if candidate.kind == CandidateKind.MOVE and candidate.destination is not None:
        dangers = [a for a in context.actors if a.active and a.entity_id != actor.entity_id
                   and a.team_id != NEUTRAL_TEAM]
        if not dangers:
            return -100
        def distance(cell):
            return min(max(abs(cell.x-a.position.x), abs(cell.y-a.position.y),
                           abs(cell.z-a.position.z)) * 5 for a in dangers)
        gain = distance(candidate.destination) - distance(actor.position)
        if gain <= 0 or candidate.metadata.get('hazard_exposure') or candidate.metadata.get('reaction_exposure'):
            return -100
        return 100 + gain * 10 - candidate.movement_cost_ft
    if candidate.source_definition_id == 'system:combat.dodge':
        return 50
    if candidate.kind == CandidateKind.END_TURN:
        return 0
    return -10000
