from types import SimpleNamespace

from combat.ext import mgr_reserve_cremation_cinder_heart_ash_sentence as cremation


def test_new_journey_rebases_all_retained_deadlines():
    deadline = 654
    saved = {
        "clock": 600,
        "effects": [{"until": deadline}],
        "modifiers": [{"until": deadline}],
        "fields": [{"until": deadline}],
    }
    session = SimpleNamespace(state={"actors": {"a": {"bundle": {cremation.BLOCK: saved}}}})
    cremation.initialize_journey(session, "a")
    rebased = session.state["actors"]["a"]["source_states"][cremation.PARENT]
    assert rebased["clock"] == 0
    assert [rebased[k][0]["until"] for k in ("effects", "modifiers", "fields")] == [54, 54, 54]


def test_encounter_import_keeps_distinct_paid_conditions_and_rebinds_scripture():
    class Engine:
        typed_bundle_documents = []
        state = SimpleNamespace(actors={}, round_number=1, current_slot_index=0, initiative_order=["a"] )
        def _apply_condition(self, actor, cid, source, owner, *, expires_on, data):
            instance = "new-" + str(len(actor.conditions))
            condition = SimpleNamespace(condition_id=cid, source_definition_id=source,
                                        source_actor_id=owner, instance_id=instance,
                                        expires_on=expires_on, data=dict(data))
            actor.conditions[instance] = condition
            return condition

    actor = SimpleNamespace(entity_id="a", conditions={})
    saved = {
        "clock": 0,
        "effects": [
            {"condition": cremation.PREFIX+"activation", "source": cremation.FEATURES[0],
             "owner": "a", "instance": "paid1", "data": '{"kind":"damage","activation":"one"}', "until": 30},
            {"condition": cremation.PREFIX+"activation", "source": cremation.FEATURES[0],
             "owner": "a", "instance": "paid2", "data": '{"kind":"damage","activation":"two"}', "until": 30},
            {"condition": cremation.PREFIX+"activation", "source": cremation.FEATURES[0],
             "owner": "a", "instance": "ash", "data": '{"kind":"scripture"}', "until": 30},
            {"condition": cremation.PREFIX+"scripture_prepared", "source": cremation.FEATURES[2],
             "owner": "a", "instance": "prepared", "data": '{"ash_instance":"ash"}', "until": 30},
        ],
    }
    engine = Engine()
    engine.state.actors["a"] = actor
    engine.typed_bundle_documents = [{"actor_id": "a", cremation.BLOCK: saved}]
    cremation.import_timed_states(engine)
    activations = [c for c in actor.conditions.values() if c.condition_id == cremation.PREFIX+"activation"]
    assert len(activations) == 3
    prepared = next(c for c in actor.conditions.values() if c.condition_id == cremation.PREFIX+"scripture_prepared")
    restored_ash = next(c for c in activations if c.data["kind"] == "scripture")
    assert prepared.data["ash_instance"] == restored_ash.instance_id
