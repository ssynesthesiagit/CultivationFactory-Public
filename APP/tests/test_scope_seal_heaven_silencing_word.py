"""The printed recipient choice must not make the automatic seat hit allies."""
from combat.speech import can_hear_from
from tests.fixed_controller import force_primary
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle


WORD = 'tianxia.subpath.qi.kiai_master.feature.heaven_silencing_word'


def test_automatic_heaven_silencing_word_only_rolls_saves_for_enemies(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_features=[WORD], cl=18,
                                owner_dc=100, seed='HEAVEN-SILENCING-WORD')
    cast = candidate(combat, mid, 'Heaven-Silencing Word')
    engine = combat._load_session(mid).engine
    assert can_hear_from(engine, engine.state.actors[OWNER], engine.state.actors[ALLY], WORD)
    force_primary(combat, mid, OWNER, cast.candidate_id)
    settle(table, mid, cast.candidate_id, auto=True)

    engine = reload(tmp_path, mid)
    saves = {event.actor_id for event in engine.events
             if event.event_type == 'SAVE_ROLLED' and event.source_definition_id == cast.source_definition_id}
    assert saves == {FOE}
