"""Custom deadlines cross persisted Table boundaries without dead-creature gameplay."""
import pytest

from combat import ext
from combat.ext import effect_durations as clocks, placed, spirit_traditions as spirit
from combat.ext import life_state
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt15_support import LEFT, ALLY, RIGHT, fight, act, turn, reload


def step(table, mid):
    shown = table.state(mid)
    result = act(table, mid, "end") if shown["menu"].get("end_turn") else table.auto_step(mid, shown["last_sequence"])
    assert result["status"] == "COMMITTED"


@pytest.mark.parametrize("kind", ["filings", "grief", "grief_expired_original", "elbow", "wax_start", "wax_end",
                                  "mist", "choking", "shadow", "splinters", "force", "marker_start", "marker_end",
                                  "omen", "eye", "spine", "quench", "transfer", "end_suppression", "benefit",
                                  "pane", "claim", "feed", "thunder", "summon", "choir", "filings_revive", "grief_revive"])
def test_custom_deadlines_expire_after_table_commit_reload_and_stay_expired_on_revival(tmp_path, monkeypatch, kind):
    revive = kind.endswith("_revive")
    kind = kind.removesuffix("_revive")
    def setup(ctx, row):
        e, owner = ctx.engine, ctx.actor
        if kind == "thunder":
            owner = e.state.actors[LEFT]  # Defeat off-turn, after its real end callback.
        if owner.entity_id != LEFT:
            dead = e.state.actors[LEFT]
            e._remove_condition(dead, life_state.SEAL, "test:revive")
            e._remove_condition(dead, life_state.SOUL, "test:revive")
            e._remove_condition(dead, "condition:typed.death_finalized", "test:revive")
            life_state.restore_hp(e, dead, 1, "test:revive", owner.entity_id)
            e._set_life_state(dead, None, "test:revive")
            return
        ally = e.state.actors[ALLY]
        source = ctx.source
        if kind in ("grief", "grief_expired_original", "transfer", "end_suppression", "benefit"):
            e._apply_condition(ally, "condition:typed.frightened", "test:original", LEFT,
                expires_on=clocks.token("end", LEFT, owner.turns_started + 1) if kind == "grief_expired_original" else "UNTIL_REMOVED")
            original = next(c for c in ally.conditions.values() if c.source_definition_id == "test:original")
            if kind.startswith("grief"):
                spirit.suppress(e, ally, original, source, LEFT, "Eat the Bitter Memory", clock=owner)
            elif kind == "end_suppression":
                from combat.ext.end_effect import suppress
                suppress(ally, "condition", original.instance_id, original, engine=e, by=owner)
            elif kind == "benefit":
                from combat.ext.benefit_suppression import suppress
                assert suppress(e, owner, ally, "condition:" + original.instance_id, "owner_turn", source)
            else:
                from combat.ext.effect_transfer import FLAG
                ally.conditions.pop(original.instance_id)
                e._append_event("CONDITION_REMOVED", source, actor_id=LEFT, target_ids=(ALLY,),
                                payload={"condition_id": original.condition_id, "instance_id": original.instance_id})
                e._apply_condition(owner, original.condition_id, "test:original", LEFT, expires_on="UNTIL_REMOVED")
                held = next(c for c in owner.conditions.values() if c.source_definition_id == "test:original")
                owner.turn_flags[FLAG] = [{"kind": "condition", "key": held.instance_id, "from": ALLY,
                                          "turn": owner.turns_started + 1, "returns": True}]
        elif kind in ("pane", "claim", "feed"):
            from combat.gate2_runtime_models import RuntimeObjectState, Position
            from combat.ext import glass_pane, verdant_chassis as verdant
            component = {"kind": glass_pane.KEY, "glass_owner": LEFT, "source": source,
                         "collapse": clocks.token("end", LEFT, owner.turns_started + 1)} if kind == "pane" else {
                "owner": LEFT, "made": 1, "until_round": e.state.round_number + (1 if kind == "claim" else 10),
                "feed": 1 if kind == "feed" else 0, "feed_until": owner.turns_started + 1}
            obj = RuntimeObjectState(object_id="object:sol184r1", object_kind="GLASS_PANE" if kind == "pane" else verdant.KIND,
                                     position=Position(x=2, y=2), unattended=True, flammable=False,
                                     current_hp=5, maximum_hp=5, destroyed=False, component=component)
            e._update_object(obj, source, LEFT)
        elif kind == "choir":
            from combat.ext.choir_of_the_unopened_eye import HYMN_HELD
            e._apply_condition(owner, HYMN_HELD, source, LEFT, expires_on="UNTIL_REMOVED",
                               data={"turn": owner.turns_started, "target": RIGHT})
        elif kind == "thunder":
            from combat.ext.sound_cage import THUNDER
            e._apply_condition(owner, THUNDER, source, LEFT, expires_on="UNTIL_REMOVED",
                               data={"deadline": owner.turns_started + 1})
        elif kind == "summon":
            from combat.summons import summon
            companion = next(a for a in e.state.actors.values() if a.summon and a.summon["owner"] == LEFT)
            summon(e, owner, companion.summon["group"], source)
            companion.summon.update(status="present", expires_on=clocks.token("start", LEFT, owner.turns_started + 1))
        elif kind in ("marker_start", "marker_end"):
            e._apply_condition(ally, "condition:typed.sol184r1_mark", source, LEFT,
                expires_on="START_OF_MARKER_NEXT_TURN" if kind == "marker_start" else "END_OF_MARKER_NEXT_TURN",
                data={"marker_turn": owner.turns_started})
        elif kind in ("omen", "eye", "spine", "quench"):
            flag = {"omen": "_round_h1_omen_until", "eye": "_round_eye_beneath_unseen",
                    "spine": "_round_perfect_spine", "quench": "_round_edge_quench_charge"}[kind]
            if kind == "omen":
                from combat.ext.d20_rewrite_fate import _OMEN_UNTIL
                flag = _OMEN_UNTIL
                owner.turn_flags["_round_h1_omen"] = 6
            owner.turn_flags[flag] = owner.turns_started + 1 if kind == "omen" else {"until": owner.turns_started + 1}
        else:
            tags = {"elbow": "iron_elbow", "shadow": "shadow_anchor", "splinters": "scouring_splinters", "force": "force_anchor",
                    "filings": "metal_filings"}
            if kind == "filings":
                action = next(a for a in e.action_catalog.values() if a.owner_id == LEFT and
                              ((a.parameters or {}).get("typed") or {}).get("source") == "TAL_METAL_IRON_FILINGS_CLOUD")
                source = action.source_definition_id
            zone = placed.place(e, owner, source=source, tag=tags.get(kind, "sol184r1"), cells=[(2, 2)],
                                name="Temporary difficult terrain", difficult="all", placed={
                                    **({"expires_turn": owner.turns_started + 1} if kind == "elbow" else {}),
                                    # Batch 3's Iron Filings Cloud record (riders_metal.filings_ground at CL 10+:
                                    # ends at the end of the owner's next turn).
                                    **({"expires_turn": owner.turns_started + 1, "end": 1} if kind == "filings" else {}),
                                    **({"until": clocks.token("start" if kind == "splinters" else "end", LEFT, owner.turns_started + 1)}
                                       if kind in ("shadow", "splinters", "force") else {})})
            if kind == "filings":
                assert zone.zone_id in e.state.zones
                assert placed.data(e.state.zones[zone.zone_id])["expires_turn"] == owner.turns_started + 1
            else:
                if kind.startswith("wax"):
                    zone.trigger_profile.update(wax_smoke_edge=kind.split("_")[1], wax_smoke_turn=owner.turns_started + 1)
                elif kind == "mist":
                    zone.trigger_profile.update(dense_until_turn=owner.turns_started + 1, obscured="heavy")
                elif kind == "choking":
                    zone.trigger_profile.update(smoke_choking_until_owner_turn=owner.turns_started + 1,
                        triggers=[{"effects": [{"type": "smoke_choke_save", "expires_owner_turn": owner.turns_started + 1}]}])
                elif kind == "force":
                    from combat.ext.force import CLUNG
                    e._apply_condition(ally, CLUNG, source, LEFT, expires_on="UNTIL_REMOVED", data={"zone_id": zone.zone_id})
                e._append_event("ZONE_CREATED", source, actor_id=LEFT, payload={"zone": zone.model_dump(mode="json")})
        e._commit_damage(owner, owner.current_hp if revive else owner.maximum_hp * 3,
                         "UNTYPED", "test:death", LEFT, None, reaction_depth=0)
        if revive:
            # The supported lingering-soul state remains active in persistence
            # but omits creature turns. A lamp keeps its window available here.
            e._apply_condition(owner, life_state.SOUL, "test:death", LEFT, expires_on="UNTIL_REMOVED",
                               data={"round": e.state.round_number, "slot": e.state.current_slot_index,
                                     "window": 10, "lamp": True, "label": "Lingering soul"})

    monkeypatch.setitem(ext.effects(), "sol184r1_setup", setup)
    combat, table, mid = fight(tmp_path, ["TAL_METAL_IRON_FILINGS_CLOUD",
                              *(["TAL_VERDANT_GROWTH_FEED_THE_ROOT"] if kind == "feed" else []),
                              *(["tianxia.talent.disease.living_plague"] if kind == "summon" else [])],
                              right=["POISON_BASE_DELIVER_THE_DOSE"], ally=[], effects=[{"type": "sol184r1_setup"}])
    turn(table, mid, RIGHT if kind == "thunder" else LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    initial = reload(combat, mid)
    if kind in ("filings", "elbow", "wax_start", "wax_end", "shadow", "splinters", "force", "mist", "choking"):
        assert any(z.active for z in initial.state.zones.values())
    if kind.startswith("grief"):
        assert any(c.condition_id == spirit.SUPPRESSED for c in initial.state.actors[ALLY].conditions.values())
    step(table, mid)  # Complete the already-started turn; subsequent slots are expiry-only.
    e = reload(combat, mid)
    defeated = e.state.event_sequence
    turns = e.state.actors[LEFT].turns_started
    for _ in range(5):
        step(table, mid)
        e = reload(combat, mid)
        combat = CombatService(combat.source_root, tmp_path)
        table = TabletopService(combat, tmp_path)
    owner, ally = e.state.actors[LEFT], e.state.actors[ALLY]
    assert owner.turns_started == turns
    assert not any(ev.actor_id == LEFT and ev.sequence > defeated and ev.event_type in
                   ("TURN_STARTED", "TURN_ENDED", "CHECK_ROLLED", "ROLL_RECORDED") for ev in e.events)

    def expired(engine):
        owner, ally = engine.state.actors[LEFT], engine.state.actors[ALLY]
        assert not any(c.condition_id == spirit.SUPPRESSED for c in ally.conditions.values())
        if kind in ("grief", "end_suppression", "benefit", "transfer"):
            assert any(c.condition_id == "condition:typed.frightened" for c in ally.conditions.values())
        if kind == "grief_expired_original":
            assert not any(c.source_definition_id == "test:original" for c in ally.conditions.values())
        if kind.startswith("marker"):
            assert not any(c.condition_id == "condition:typed.sol184r1_mark" for c in ally.conditions.values())
        if kind in ("pane", "claim", "feed"):
            obj = engine.state.objects["object:sol184r1"]
            if kind == "feed":
                assert obj.component["feed"] == 0
            else:
                assert obj.destroyed
        if kind == "thunder":
            from combat.ext.sound_cage import THUNDER
            assert not any(c.condition_id == THUNDER for c in owner.conditions.values())
        if kind == "choir":
            from combat.ext.choir_of_the_unopened_eye import HYMN_HELD
            assert not any(c.condition_id == HYMN_HELD for c in owner.conditions.values())
        if kind == "summon":
            assert all(not a.active for a in engine.state.actors.values() if a.summon and a.summon["owner"] == LEFT)
        if kind in ("omen", "eye", "spine", "quench"):
            assert not any(k in owner.turn_flags for k in ("_round_eye_beneath_unseen", "_round_perfect_spine", "_round_edge_quench_charge"))
            if kind == "omen":
                assert owner.turn_flags["_round_h1_omen"] == 0
        if kind == "mist":
            assert any(z.active and z.trigger_profile.get("obscured") == "light" for z in engine.state.zones.values())
        elif kind == "choking":
            assert not any(z.trigger_profile.get("smoke_choking_until_owner_turn") for z in engine.state.zones.values())
        elif kind in ("filings", "elbow", "wax_start", "wax_end", "shadow", "splinters", "force"):
            assert not any(z.active for z in engine.state.zones.values())
            if kind == "force":
                from combat.ext.force import CLUNG
                assert not any(c.condition_id == CLUNG for c in ally.conditions.values())
    expired(e)
    if not revive:
        return
    turn(table, mid, RIGHT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    e = reload(combat, mid)
    assert e.state.actors[LEFT].current_hp == 1
    assert e.state.actors[LEFT].active
    expired(e)
    for _ in range(3):
        step(table, mid)
    expired(reload(combat, mid))


def test_custom_clock_multi_slot_revival_and_new_records():
    from types import SimpleNamespace
    actor = SimpleNamespace(turns_started=2)
    storage = {}
    assert not clocks.custom_turn_due(actor, 5, storage, "old", nominal=True)
    assert not clocks.custom_turn_due(actor, 5, storage, "old", nominal=True)
    assert not clocks.custom_turn_due(actor, 5, storage, "new")
    assert all("_round_" in key and type(value) is int for key, value in storage.items())
    actor.turns_started += 1
    assert clocks.custom_turn_due(actor, 5, storage, "old")
    assert not clocks.custom_turn_due(actor, 5, storage, "new")
    assert not storage


@pytest.mark.parametrize("kind", ["senses", "aura"])
def test_review_listed_round_clocks_expire_in_table_without_holder_turns(tmp_path, monkeypatch, kind):
    from combat.senses import SENSE
    from combat.ext.docket_terrain import AURA_ACTIVE
    condition_id = SENSE if kind == "senses" else AURA_ACTIVE

    def setup(ctx, row):
        e, owner = ctx.engine, ctx.actor
        e._apply_condition(owner, condition_id, ctx.source, LEFT, expires_on="UNTIL_REMOVED",
                           data={"until_round": e.state.round_number + 1})
        e._commit_damage(owner, owner.maximum_hp * 3, "UNTYPED", "test:death", LEFT, None, reaction_depth=0)

    monkeypatch.setitem(ext.effects(), "sol184r1_round_setup", setup)
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], ally=[],
                              effects=[{"type": "sol184r1_round_setup"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    e = reload(combat, mid)
    count = e.state.actors[LEFT].turns_started
    assert any(c.condition_id == condition_id for c in e.state.actors[LEFT].conditions.values())
    step(table, mid)
    after = reload(combat, mid).state.event_sequence
    for _ in range(3):
        step(table, mid)
        e = reload(combat, mid)
        combat = CombatService(combat.source_root, tmp_path)
        table = TabletopService(combat, tmp_path)
    assert not any(c.condition_id == condition_id for c in e.state.actors[LEFT].conditions.values())
    assert e.state.actors[LEFT].turns_started == count
    assert not any(ev.actor_id == LEFT and ev.sequence > after and ev.event_type in ("TURN_STARTED", "TURN_ENDED") for ev in e.events)


def test_pending_custom_offset_survives_holder_turn_reload_and_source_revival(tmp_path, monkeypatch):
    """A synthetic three-slot suppression exercises a pending custom runtime offset."""
    from combat.ext.retained_updates import record_instance_update

    def setup(ctx, row):
        e, actor = ctx.engine, ctx.actor
        owner, ally = e.state.actors[LEFT], e.state.actors[ALLY]
        if actor.entity_id != LEFT:
            e._remove_condition(owner, life_state.DEAD, "test:revive")
            e._remove_condition(owner, life_state.SOUL, "test:revive")
            life_state.restore_hp(e, owner, 1, "test:revive", actor.entity_id)
            e._set_life_state(owner, None, "test:revive")
            return
        e._apply_condition(ally, "condition:typed.frightened", "test:original", LEFT, expires_on="UNTIL_REMOVED")
        original = next(c for c in ally.conditions.values() if c.source_definition_id == "test:original")
        spirit.suppress(e, ally, original, ctx.source, LEFT, "Custom clock regression", clock=owner)
        marker = next(c for c in ally.conditions.values() if c.condition_id == spirit.SUPPRESSED)
        marker.data = {**marker.data, "restore_after_turn": owner.turns_started + 3}
        record_instance_update(e, ally, "condition", marker.instance_id, marker)
        e._commit_damage(owner, owner.current_hp, "UNTYPED", "test:death", LEFT, None, reaction_depth=0)
        e._apply_condition(owner, life_state.SOUL, "test:death", LEFT, expires_on="UNTIL_REMOVED",
                           data={"round": e.state.round_number, "slot": e.state.current_slot_index,
                                 "window": 10, "lamp": True, "label": "Lingering soul"})

    monkeypatch.setitem(ext.effects(), "sol184r1_pending", setup)
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], right=["POISON_BASE_DELIVER_THE_DOSE"],
                              ally=[], effects=[{"type": "sol184r1_pending"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    initial = reload(combat, mid).state.actors[LEFT].turns_started
    for _ in range(5):
        step(table, mid)
        e = reload(combat, mid)
        offsets = {k: v for k, v in e.state.actors[ALLY].turn_flags.items() if k.startswith("custom_expiry_round_skipped:")}
        if offsets:
            break
    assert list(offsets.values()) == [1]
    assert e.state.actors[LEFT].turns_started == initial
    combat = CombatService(combat.source_root, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    assert reload(combat, mid).state.actors[LEFT].current_hp == 1
    seen_pending_after_real_turn = False
    for _ in range(9):
        step(table, mid)
        e = reload(combat, mid)
        marker = next((c for c in e.state.actors[ALLY].conditions.values() if c.condition_id == spirit.SUPPRESSED), None)
        if marker is None:
            break
        seen_pending_after_real_turn |= e.state.actors[LEFT].turns_started > initial
        combat = CombatService(combat.source_root, tmp_path)
        table = TabletopService(combat, tmp_path)
    assert seen_pending_after_real_turn
    assert marker is None
    assert e.state.actors[LEFT].turns_started == initial + 2
    assert any(c.source_definition_id == "test:original" for c in e.state.actors[ALLY].conditions.values())
    assert not any(k.startswith("custom_expiry_round_skipped:") for k in e.state.actors[ALLY].turn_flags)
