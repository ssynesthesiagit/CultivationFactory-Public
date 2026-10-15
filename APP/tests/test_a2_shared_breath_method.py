"""Insights 7: Shared Breath Method on a real Feed Current grant.

Drives the same sealed QIweaving fixtures as tests/test_qiweaving_auto12.py, so
the Temporary CP grant, the paid Cultivation Points and the willing-bonded
recipient are the engine's own. The rider itself attaches through the general
``temporary_cp_granted`` seam.
"""
from tests import test_qiweaving_auto12 as q
from combat.ext import insights7 as i7

SB = i7.SB_FEATURE
STAMINA = q.STAMINA


def _sheet_with_insight(talents, **kwargs):
    sheet = q.sheet(talents, **kwargs)
    fields = sheet.setdefault("spheres_and_talents", {})
    fields["cultivation_insight_record_ids"] = [SB]
    return sheet


def bonded(talents, **kwargs):
    from combat.factory_compiler import compile_character

    engine, me, foe = q.duel(compile_character(_sheet_with_insight(talents, **kwargs), actor_id=q.t.ME),
                             q.foe_bundle(), foe_stamina=40, with_ally=True)
    q.use(engine, "Qi Bond", who=me.entity_id, target=foe.entity_id)
    return engine, me, foe


def test_feed_current_also_grants_temporary_hit_points_to_the_willing_creature():
    """"When you grant Temporary CP to a willing creature with Feed Current, that creature also gains
    Temporary HP equal to your Proficiency Bonus." """
    engine, me, foe = bonded([q.BOND, q.FEED], pb=2)
    ally = engine.state.actors[q.ALLY]
    q.use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.resources[STAMINA] = 30
    assert ally.temporary_hp == 0
    events = q.use(engine, "Feed Current", who=me.entity_id, target=ally.entity_id)
    assert ally.temporary_hp == me.proficiency_bonus, (ally.temporary_hp, me.proficiency_bonus)
    assert any("gains 2 Temporary Cultivation Points" in line for line in q.logs(events)), q.logs(events)


def test_the_rider_grants_nothing_without_the_insight():
    engine, me, foe = q.bonded_fight([q.BOND, q.FEED], pb=2, with_ally=True)
    ally = engine.state.actors[q.ALLY]
    q.use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.resources[STAMINA] = 30
    events = q.use(engine, "Feed Current", who=me.entity_id, target=ally.entity_id)
    assert ally.temporary_hp == 0
    assert any("gains 2 Temporary Cultivation Points" in line for line in q.logs(events)), q.logs(events)


def test_the_rider_does_not_fire_when_feed_current_is_refused():
    """A refused payment (no Cultivation Points) grants no Temporary CP, so it grants no Temporary HP."""
    engine, me, foe = bonded([q.BOND, q.FEED], pb=2)
    ally = engine.state.actors[q.ALLY]
    q.use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.resources[STAMINA] = 30
    me.resources[STAMINA] = 0  # Feed Current needs 1 or more CP to spend
    events = q.use(engine, "Feed Current", who=me.entity_id, target=ally.entity_id)
    assert ally.temporary_hp == 0
    assert any("needs 1 or more" in line for line in q.reminders(events)), q.reminders(events)


def test_the_rider_is_committed_state_that_reloads(tmp_path):
    """Feed Current runs through CombatService.execute_intent and reload keeps its Temporary HP grant."""
    from combat.gate5_service import CombatService

    combat, table, mid = q._table(tmp_path, talents=(q.BOND, q.FEED, SB), pb=2, seed="GINS7-SHARED-BREATH")
    q._advance(combat, table, mid, q.t.ME)
    bond = q._answer_prompts(table, mid, q._pick(combat, mid, "Qi Bond (willing creature)", q.ALLY),
                             lambda _reaction: [])
    assert bond["status"] == "COMMITTED", bond
    feed = q._answer_prompts(table, mid, q._pick(combat, mid, "Feed Current", q.ALLY),
                             lambda reaction: [{**reaction["context"], "selection": "USE",
                                                "option_ids": [reaction["choice"]["options"][0]["id"]]}])
    assert feed["status"] == "COMMITTED", feed
    loaded = CombatService(combat.source_root, combat.userdata_root)._load_session(mid)
    ally = loaded.engine.state.actors[q.ALLY]
    assert ally.temporary_hp == 2, ally.temporary_hp
    grants = [e.model_dump(mode="json") for e in loaded.engine.events if e.event_type == "TEMP_HP_GRANTED"
              and e.source_definition_id == SB]
    assert grants and grants[-1]["payload"]["after"] == 2, grants
    assert loaded.mechanical.replay()["status"] == "PASS", loaded.mechanical.replay()


def test_the_rider_stays_off_another_temporary_cultivation_point_grant():
    """Another plug-in using the documented Temporary CP seam grants its own CP and no Shared Breath HP."""
    from combat import ext

    engine, me, foe = bonded([q.BOND, q.FEED], pb=2)
    ally = engine.state.actors[q.ALLY]
    q.use(engine, "Qi Bond (willing creature)", who=me.entity_id, target=ally.entity_id)
    ally.resources[STAMINA] = 30
    assert ally.temporary_hp == 0
    # The same documented seam, reported by an unrelated grant rather than Feed Current.
    ext.run("temporary_cp_granted", engine, ally, me, 3, "action:typed.someone_else.a_different_talent")
    assert ally.temporary_hp == 0
