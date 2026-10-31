"""A Ward exit save uses the ward's Disease source after a table reload."""

from combat.gate2_rolls import DeterministicRollAuthority
from tests.test_disease_quarantine_ward import (
    OWNER, SELECTED, _fight, _fresh, _raise_ward, _sow, _submit, _turn,
)


def test_ward_exit_save_offers_the_settled_save_bonus_once(tmp_path, monkeypatch):
    """The Ward's own settlement is the only place its exit save gets a settled bonus.

    ``quarantine_ward_teleport`` rolls a native save and then settles it through the
    typed lifecycle so Disease save benefits and outcome reactions apply. It must tell
    ``_roll_save`` that it settles the draw itself, exactly as typed saves do, or the
    settled_save_roll_bonus hook is offered the same roll twice: once at the draw and
    again in settlement, adding a provider's bonus twice to one save.
    """
    from combat import ext

    offers = []

    def provider(engine, subject, ability, dc, roll, source_id, intent, failed, bearer):
        if subject.entity_id == SELECTED and ability == "CHA":
            offers.append(roll.roll_id)
            return 5  # a bonus the character can only take once per save
        return None

    monkeypatch.setitem(ext._HOOKS, "settled_save_roll_bonus", [provider])
    raw = DeterministicRollAuthority.raw_d20

    def controlled(roller, **kwargs):
        roll = raw(roller, **kwargs)
        if kwargs["reason"].startswith("ATTACK:"):
            return roll.model_copy(update={"natural_result": 10, "dice": (10,),
                                           "discarded": (), "total": 10 + kwargs["modifier"]})
        if kwargs["reason"].startswith("SAVE:") and kwargs["actor_id"] == SELECTED:
            # The natural 3 misses the DC 10 ward on its own; one +5 bonus carries it over.
            return roll.model_copy(update={"natural_result": 3, "dice": (3,), "discarded": (),
                                           "total": 3 + kwargs["modifier"]})
        return roll

    monkeypatch.setattr(DeterministicRollAuthority, "raw_d20", controlled)
    combat, table, mid = _fight(tmp_path, dc=10, selected_cha=6, selected_teleport=True)
    _raise_ward(combat, table, mid)
    _sow(combat, table, mid, SELECTED)
    state = _turn(combat, table, mid, SELECTED)
    engine = _fresh(combat, mid).engine
    from combat.ext.disease import tokens
    assert tokens(engine, engine.state.actors[OWNER], engine.state.actors[SELECTED]) > 0
    from combat.spatial_areas import zone_contains
    ward = next(zone for zone in engine.state.zones.values()
                if isinstance((zone.trigger_profile or {}).get("quarantine_ward"), dict))
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == "test:quarantine_ward_teleport:" + SELECTED
                     and c.destination is not None
                     and not zone_contains(engine, engine.state.actors[SELECTED], ward, at=c.destination))
    from combat.ext.needle import cell_id

    def choose(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:needle.teleport_destination":
            return [cell_id(candidate.destination)]
        return None

    _submit(table, mid, state, candidate.candidate_id, choose=choose)
    loaded = _fresh(combat, mid).engine
    # The settled bonus turned the failed save into a success, so the exit happened once.
    assert loaded.state.actors[SELECTED].position == candidate.destination
    saves = [event for event in loaded.events if event.event_type == "SAVE_ROLLED"
             and event.actor_id == SELECTED and str(event.payload.get("reason", "")).endswith(":CHA")]
    assert len(saves) == 1
    roll_id = saves[0].payload["roll_id"]
    assert offers == [roll_id]  # one draw, one settled-bonus offer
    triggers = [event for event in loaded.events if event.event_type == "PASSIVE_TRIGGERED"
                and event.payload.get("hook") == "settled_save_roll_bonus"
                and event.payload.get("roll_id") == roll_id]
    assert len(triggers) == 1
    assert triggers[0].payload["bonus"] == 5


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
    from combat.ext.needle import cell_id
    def choose(prompt):
        if prompt["context"]["reaction_source_id"] == "choice:needle.teleport_destination":
            return [cell_id(candidate.destination)]
        return None

    _submit(table, mid, state, candidate.candidate_id, choose=choose)
    loaded = _fresh(combat, mid).engine
    assert loaded.state.actors[SELECTED].position == candidate.destination
    rolls = [event for event in loaded.events if event.event_type == "SAVE_ROLLED"
             and event.actor_id == SELECTED]
    assert any("ADVANTAGE" in str(event.payload) for event in rolls)
