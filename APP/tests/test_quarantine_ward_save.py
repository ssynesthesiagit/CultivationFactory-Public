"""A Ward exit save uses the ward's Disease source after a table reload."""

from combat.gate2_rolls import DeterministicRollAuthority
from tests.test_disease_quarantine_ward import (
    OWNER, SELECTED, _fight, _fresh, _raise_ward, _sow, _submit, _turn,
)


def test_plague_bearing_body_advantage_allows_ward_teleport_after_reload(tmp_path, monkeypatch):
    body = "tianxia.talent.disease.plague_bearing_body"
    combat, table, mid = _fight(tmp_path, selected_talents=[body], dc=15, selected_cha=0, selected_teleport=True)
    raw = DeterministicRollAuthority.raw_d20

    def controlled(roller, **kwargs):
        roll = raw(roller, **kwargs)
        if kwargs["reason"].startswith("ATTACK:"):
            return roll.model_copy(update={"natural_result": 10, "dice": (10,),
                                           "discarded": (), "total": 10 + kwargs["modifier"]})
        if kwargs["reason"].startswith("SAVE:") and kwargs["actor_id"] == SELECTED:
            advantage = kwargs["mode"] == "ADVANTAGE"
            chosen = 18 if advantage else 3
            return roll.model_copy(update={"natural_result": chosen,
                "dice": (3, 18) if advantage else (3,), "discarded": (3,) if advantage else (),
                "total": chosen + kwargs["modifier"]})
        return roll

    monkeypatch.setattr(DeterministicRollAuthority, "raw_d20", controlled)
    state = _turn(combat, table, mid, SELECTED)
    engine = _fresh(combat, mid).engine
    action = next(c for c in engine.legal_candidates()
                  if c.actor_id == SELECTED and body in c.source_definition_id)
    _submit(table, mid, state, action.candidate_id)
    _raise_ward(combat, table, mid)
    _sow(combat, table, mid, SELECTED)
    state = _turn(combat, table, mid, SELECTED)
    engine = _fresh(combat, mid).engine
    from combat.ext.disease import tokens
    assert tokens(engine, engine.state.actors[OWNER], engine.state.actors[SELECTED]) > 0
    from combat.spatial_areas import zone_contains
    ward = next(z for z in engine.state.zones.values()
                if isinstance((z.trigger_profile or {}).get("quarantine_ward"), dict))
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == f"test:quarantine_ward_teleport:{SELECTED}"
                     and c.destination is not None
                     and not zone_contains(engine, engine.state.actors[SELECTED], ward, at=c.destination))
    _submit(table, mid, state, candidate.candidate_id)
    loaded = _fresh(combat, mid).engine
    assert loaded.state.actors[SELECTED].position == candidate.destination
    rolls = [event for event in loaded.events if event.event_type == "SAVE_ROLLED"
             and event.actor_id == SELECTED]
    assert any("ADVANTAGE" in str(event.payload) for event in rolls)
