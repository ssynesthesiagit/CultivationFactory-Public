from app.models import CombatFactoryMatchRequest
from tests.worker2_support import fixture,OWNER,ALLY,FOE,reload


def test_native_factory_surprise_producer():
    # This exact native request is rejected by the base, before an encounter
    # can falsely claim to have represented the owner's explicit Surprise fact.
    CombatFactoryMatchRequest(project_ids=['worker2-owner'],surprised_actor_ids=[OWNER])
