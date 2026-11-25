"""CONCREALM1 repro: the Bible's Realm-scaled Concentration limit is the shipped default (owner ruling 2026-11-25).

Synthetic Factory characters are compiled through the normal path with no mode override, so these assertions read
the capacity the shipped combat/rules/concentration.json seals into each new bundle.
"""

from combat import concentration
from combat.gate2_runtime_content import AN
from tests.test_multi_concentration import _engine


def _held(actor) -> str:
    return f"held={concentration.sources(actor)}"


def test_cl1_holds_one_and_the_older_one_ends():
    engine, me = _engine(1)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    assert concentration.sources(me) == ["action:b"], _held(me)


def test_cl5_holds_two_and_a_third_start_ends_the_oldest():
    engine, me = _engine(5)
    for source in ("action:a", "action:b", "action:c"):
        engine._start_concentration(me, source)
    assert concentration.sources(me) == ["action:b", "action:c"], _held(me)


def test_cl20_holds_five():
    engine, me = _engine(20)
    for i in range(6):
        engine._start_concentration(me, f"action:{i}")
    assert concentration.sources(me) == [f"action:{i}" for i in range(1, 6)], _held(me)


def test_limit_for_cl_reads_the_mythic_rows_from_the_shipped_file():
    assert concentration.limit_for_cl(21) == 6, f"CL21 limit={concentration.limit_for_cl(21)}"
    assert concentration.limit_for_cl(40) == 10, f"CL40 limit={concentration.limit_for_cl(40)}"


def test_failed_damage_save_ends_only_the_newest():
    engine, me = _engine(5)
    engine._start_concentration(me, "action:a")
    engine._start_concentration(me, "action:b")
    me.saving_throws["CON"] = -100  # the save fails
    engine._commit_damage(me, 1, "BLUDGEONING", "test:hit", AN, None, reaction_depth=0)
    assert concentration.sources(me) == ["action:a"], _held(me)


def test_seventy_damage_uses_dc_35():
    engine, actor = _engine(20)
    actor.maximum_hp = 1000
    actor.current_hp = 1000
    engine._start_concentration(actor, "action:a")
    before = len(engine.events)
    engine._commit_damage(actor, 70, "BLUDGEONING", "test:hit", AN, None, reaction_depth=0)
    saves = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"]
    assert len(saves) == 1 and saves[0].payload["dc"] == 35


def test_two_timed_copies_expire_separately_after_table_reload(tmp_path):
    from combat import zones
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from tests.test_riders_lane11 import MOON, ROOT, _sheet
    import json
    import zipfile

    caster, foe = [FACTORY_ACTOR_PREFIX + p for p in ("realm-timed", "realm-timed-foe")]
    docs = [_sheet(MOON, cl=20), _sheet(MOON)]
    docs[1]["path_and_subpath"] = {"path_feature_record_ids": []}
    docs[0]["ability_scores_and_statistics"]["primary_resource"] = {"name": "Qi", "maximum": 1000}
    for aid, doc in zip((caster, foe), docs):
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [compile_character(doc, actor_id=aid) for doc, aid in zip(docs, (caster, foe))],
        [caster, foe], {caster: "team:factory", foe: "team:opponents"},
        {caster: {"x": 3, "y": 6}, foe: {"x": 13, "y": 8}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [caster], [foe],
        control_modes={caster: "MANUAL", foe: "MANUAL"}, match_seed="REALM-TIMED",
        display_name="Two timed fields", maximum_rounds=20)["match_id"]

    def take(candidate):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], 0)
        assert result["status"] == "COMMITTED", result

    def end():
        engine = combat._load_session(mid).engine
        take(next(c for c in engine.legal_candidates() if c.kind.value == "END_TURN"))

    slot_count = len(combat._load_session(mid).engine.state.initiative_order)

    def slot_number(engine):
        return engine.state.round_number * slot_count + engine.state.current_slot_index

    def reload_at(target_slot):
        turns = target_slot - slot_number(combat._load_session(mid).engine)
        assert turns >= 0
        for _ in range(turns):
            end()
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        assert slot_number(session.engine) == target_slot
        return session

    def assert_active(session, expected):
        actor = session.engine.state.actors[caster]
        active = [copy for _, copy in concentration.held(actor)]
        if actor.concentration is not None:
            active.append(actor.concentration)
        assert [(copy.started_sequence, copy.zone_id) for copy in active] == expected
        assert {z.zone_id for z in zones.typed_zones(session.engine)} == {zone_id for _, zone_id in expected}

    while table.state(mid)["menu"]["actor_id"] != caster:
        end()
    copies, deadlines = [], []
    for cast in range(2):
        engine = combat._load_session(mid).engine
        # Moon's Pull lasts one minute: ten rounds from the cast's own slot.
        deadlines.append(slot_number(engine) + 10 * slot_count)
        candidate = next(c for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog
            and engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source") == MOON
            and c.destination is not None and (c.destination.x, c.destination.y) == (3, 6))
        take(candidate)
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        current = session.engine.state.actors[caster].concentration
        assert current is not None and current.source_definition_id == candidate.source_definition_id
        assert current.zone_id is not None and current.zone_id not in {zone_id for _, zone_id in copies}
        copies.append((current.started_sequence, current.zone_id))
        assert_active(session, copies)
        if cast == 0:
            for _ in range(slot_count):
                end()

    for index, deadline in enumerate(deadlines):
        assert_active(reload_at(deadline - 1), copies[index:])
        session = reload_at(deadline)
        assert_active(session, copies[index + 1:])
        assert session.verify()["status"] == "PASS"
