"""Lifetime-preserving replacements expire at the exact persisted Table boundary."""
import pytest

from combat import ext
from combat.ext import effect_durations as clocks, life_state, verdant_chassis as verdant
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt15_support import LEFT, ALLY, RIGHT, fight, act, turn, reload
from tests.test_sol184r1_custom_expiry import step

LINEAGE = "tianxia.talent.verdant_growth.rooted_lineage_scripture"


def test_clock_helpers_do_not_reorder_existing_boundary_subscribers():
    """A fresh discovery must preserve the legacy order of tied boundary hooks."""
    import subprocess
    import sys
    from pathlib import Path

    code = """
from combat import ext
ext.effects()
for point, earlier, later in (
    ('turn_start', 'combat.ext.afflictions.periodic', 'combat.ext.effect_durations.turn_started'),
    ('turn_end', 'combat.ext.afflictions.repeat_one', 'combat.ext.effect_durations.turn_ended'),
):
    names = [f.__module__ + '.' + f.__name__ for f in ext._HOOKS[point]]
    assert names.index(earlier) < names.index(later), (point, earlier, later)
"""
    subprocess.check_call([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])


@pytest.mark.parametrize("replace", ["extend", "spend", "renew"])
@pytest.mark.parametrize("revive", [False, True])
def test_growth_replacement_exact_table_boundary_after_reload(tmp_path, monkeypatch, replace, revive):
    def setup(ctx, row):
        e, owner, holder = ctx.engine, ctx.engine.state.actors[LEFT], ctx.engine.state.actors[ALLY]
        if ctx.actor.entity_id == LEFT:
            assert verdant.place(e, owner, holder, 3, ctx.source) == 3
            e._commit_damage(owner, owner.current_hp, "UNTYPED", "test:death", LEFT, None, reaction_depth=0)
            e._apply_condition(owner, life_state.SOUL, "test:death", LEFT, expires_on="UNTIL_REMOVED",
                              data={"round": e.state.round_number, "slot": e.state.current_slot_index,
                                    "window": 10, "lamp": True, "label": "Lingering soul"})
        else:
            if replace == "spend":
                assert verdant.spend(e, owner, holder, 1, ctx.source)
            elif replace == "renew":
                assert verdant.place(e, owner, holder, 1, ctx.source) == 1
            if revive:
                for cid in (life_state.SEAL, life_state.SOUL, "condition:typed.death_finalized"):
                    e._remove_condition(owner, cid, "test:revive")
                life_state.restore_hp(e, owner, 1, "test:revive", ctx.actor.entity_id)
                e._set_life_state(owner, None, "test:revive")

    monkeypatch.setitem(ext.effects(), "sol184r2_growth_setup", setup)
    combat, table, mid = fight(tmp_path, [LINEAGE], right=["POISON_BASE_DELIVER_THE_DOSE"], ally=[],
                              effects=[{"type": "sol184r2_growth_setup"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"

    def loaded():
        nonlocal combat, table
        combat = CombatService(combat.source_root, tmp_path)
        table = TabletopService(combat, tmp_path)
        return reload(combat, mid)

    def mark(e):
        return next((c for c in e.state.actors[ALLY].conditions.values()
                     if c.source_actor_id == LEFT and "growth_mark" in c.condition_id), None)

    initial_state = loaded().state
    initial_round, owner_slot = initial_state.round_number, initial_state.current_slot_index
    initial = mark(loaded())
    assert initial is not None
    deadline = int(initial.data["marker_turn"]) + 2
    step(table, mid)  # Finish the turn already started before death.
    while (loaded().state.round_number, loaded().state.current_slot_index) <= (initial_round + 1, owner_slot):
        step(table, mid)
    e = loaded()  # First omitted owner slot extends once, at the normal deadline.
    extended = mark(e)
    assert extended is not None and extended.data["lineage_extended"] == 1
    assert extended.expires_on == clocks.token("end", LEFT, deadline)
    assert clocks.skipped_expiry_slots(e.state.actors[ALLY], extended) == 1
    assert clocks.expiry_key(initial) not in e.state.actors[ALLY].turn_flags

    turn(table, mid, RIGHT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    e = loaded()
    current = mark(e)
    assert current is not None
    assert clocks.skipped_expiry_slots(e.state.actors[ALLY], current) == (0 if replace == "renew" else 1)
    if replace == "spend":
        assert current.instance_id != extended.instance_id and current.data["count"] == 2
    # After revival, the real owner's next end is the same nominal deadline.
    while (loaded().state.round_number, loaded().state.current_slot_index) < (initial_round + 2, owner_slot):
        step(table, mid)
    e = loaded()
    if revive:
        assert e.state.current_actor_id == LEFT
        assert mark(e) is not None  # Not early at the revived start.
        step(table, mid)
        e = loaded()
    if replace == "renew":
        assert mark(e) is not None and mark(e).data["lineage_extended"] == 1
        while (loaded().state.round_number, loaded().state.current_slot_index) < (initial_round + 3, owner_slot):
            step(table, mid)
        if revive:
            step(table, mid)
        e = loaded()
    assert mark(e) is None  # Exactly one additional round, never one extra skipped slot.
    assert not any(k.startswith("expiry_round_skipped:") for k in e.state.actors[ALLY].turn_flags)


@pytest.mark.parametrize("kind", ["condition", "modifier"])
def test_transfer_moves_elapsed_clock_with_lifetime(kind):
    from types import SimpleNamespace
    from combat.ext.effect_transfer import _move
    from combat.gate2_runtime_models import ConditionInstance, ModifierInstance

    source = SimpleNamespace(entity_id="source", conditions={}, modifiers={}, turn_flags={})
    recipient = SimpleNamespace(entity_id="recipient", conditions={}, modifiers={}, turn_flags={})
    e = SimpleNamespace(state=SimpleNamespace(event_sequence=3), _append_event=lambda *a, **kw: None)
    item = (ConditionInstance(instance_id="old", condition_id="condition:typed.frightened", target_id="source",
                              source_definition_id="cast", source_actor_id="owner", applied_sequence=1,
                              expires_on=clocks.token("end", "owner", 4), data={}) if kind == "condition" else
            ModifierInstance(modifier_id="old", target_id="source", source_definition_id="cast", source_actor_id="owner",
                             target_field="armor_class", operation="ADD", value=1, applies_to="ALWAYS",
                             expires_on=clocks.token("end", "owner", 4)))
    store = source.conditions if kind == "condition" else source.modifiers
    store["old"] = item
    source.turn_flags[clocks.expiry_key(item)] = 2
    new = _move(e, "test", recipient, source, recipient, kind, "old", item, "STOLEN")
    moved = (recipient.conditions if kind == "condition" else recipient.modifiers)[new]
    assert clocks.skipped_expiry_slots(recipient, moved) == 2
    assert clocks.expiry_key(item) not in source.turn_flags


@pytest.mark.parametrize("topic", ["compass", "fire", "eye", "thorn", "monkey", "afflictions"])
def test_existing_bookkeeping_entry_points_keep_the_instance_clock(topic):
    """Exercise actual update entry points, rather than merely testing helper arithmetic."""
    from types import SimpleNamespace
    from combat.ext import compass_breaking_hand, fire_sphere, eye_patient_eye, thorn_bleeding, monkey, afflictions
    from combat.gate2_runtime_models import ConditionInstance

    holder = SimpleNamespace(entity_id="holder", conditions={}, modifiers={}, turn_flags={})
    engine = SimpleNamespace(state=SimpleNamespace(event_sequence=1))

    def event(*args, **kwargs):
        engine.state.event_sequence += 1

    def remove(actor, cid, source):
        for key, row in list(actor.conditions.items()):
            if row.condition_id == cid:
                remove_instance(actor, key, source, expected=row)

    def remove_instance(actor, iid, source, **kwargs):
        from combat.effect_endings import remove_instance as end_instance
        return end_instance(engine, actor, "condition", iid, source, **kwargs)

    def apply(actor, cid, source, owner, *, expires_on, data=None):
        key = f"condition-instance:{cid}:{actor.entity_id}:{engine.state.event_sequence + 1}"
        actor.conditions[key] = ConditionInstance(instance_id=key, condition_id=cid, source_definition_id=source,
            source_actor_id=owner, target_id=actor.entity_id, applied_sequence=engine.state.event_sequence + 1,
            expires_on=expires_on, data=data or {})
        event()

    engine._append_event, engine._remove_condition, engine._apply_condition = event, remove, apply
    engine._remove_condition_instance = remove_instance
    cid = {"thorn": thorn_bleeding.BLEEDING, "monkey": monkey.MIRROR,
           "afflictions": afflictions.condition_id()}.get(topic, "condition:typed.sol184r2")
    data = {"label": "Temporary effect", "picks": ["Voice"], "parts": {"Voice": {"companions": ["silenced"]}},
            "menu": "test:menu"}
    apply(holder, cid, "cast", "owner", expires_on=clocks.token("end", "owner", 4), data=data)
    old = next(iter(holder.conditions.values()))
    holder.turn_flags[clocks.expiry_key(old)] = 2
    if topic == "compass":
        compass_breaking_hand._update(engine, holder, old, {"updated": 1})
    elif topic == "fire":
        fire_sphere._rewake(engine, holder, old, {"updated": 1})
    elif topic == "eye":
        eye_patient_eye._refresh(engine, holder, old, updated=1)
    elif topic == "thorn":
        thorn_bleeding._update(engine, holder, old.instance_id, old, {"moved_ft": 5})
    elif topic == "monkey":
        monkey._set_images(engine, holder, 1, "cast")
    else:
        afflictions._companions(engine, holder, data, "cast", "owner", old.expires_on)
    new = next(c for c in holder.conditions.values() if c.instance_id != old.instance_id)
    assert new.instance_id != old.instance_id and new.expires_on == old.expires_on
    assert clocks.skipped_expiry_slots(holder, new) == 2
    if topic == "afflictions":
        assert clocks.skipped_expiry_slots(holder, old) == 2  # Copied lifetime still belongs to the parent too.
    else:
        assert clocks.expiry_key(old) not in holder.turn_flags


def test_shared_clock_copy_and_unstamped_inertness():
    from types import SimpleNamespace
    old = SimpleNamespace(instance_id="old")
    new = SimpleNamespace(instance_id="new")
    holder = SimpleNamespace(conditions={"old": old}, modifiers={}, turn_flags={})
    recipient = SimpleNamespace(conditions={"new": new}, modifiers={}, turn_flags={})
    clocks.transfer_expiry_clock(holder, old, recipient, new)
    assert holder.turn_flags == recipient.turn_flags == {}  # No stamps for legacy effects.
    holder.turn_flags[clocks.expiry_key(old)] = 2
    clocks.transfer_expiry_clock(holder, old, recipient, new)
    assert clocks.skipped_expiry_slots(holder, old) == clocks.skipped_expiry_slots(recipient, new) == 2


@pytest.mark.parametrize("skipped", [0, 2])
@pytest.mark.parametrize("name", ["END_OF_SOURCE_TURN_AT:4", "END_OF_MARKER_NEXT_TURN"])
def test_replacement_by_another_applier_retains_consumed_clock_anchor(skipped, name):
    from types import SimpleNamespace
    from combat.gate2_runtime_models import ConditionInstance

    holder = SimpleNamespace(entity_id="owner", conditions={}, modifiers={}, turn_flags={}, turns_started=1)
    other = SimpleNamespace(entity_id="other", turns_started=10)
    engine = SimpleNamespace(state=SimpleNamespace(event_sequence=1, current_actor_id="other",
                                                   actors={"owner": holder, "other": other}))
    old = ConditionInstance(instance_id="old", condition_id="condition:typed.test", target_id="owner",
        source_definition_id="cast", source_actor_id="owner", applied_sequence=1, expires_on=name,
        data={"marker_turn": 3})
    if skipped:
        holder.turn_flags[clocks.expiry_key(old)] = skipped

    def apply(actor, cid, source, owner, *, expires_on, data=None):
        actor.conditions["new"] = ConditionInstance(instance_id="new", condition_id=cid, target_id=actor.entity_id,
            source_definition_id=source, source_actor_id=owner, applied_sequence=2, expires_on=expires_on, data=data or {})
    engine._apply_condition = apply
    clocks.apply_condition_preserving_clock(engine, holder, old, old.condition_id, "cast", "other",
                                            expires_on=name, data=old.data)
    new = holder.conditions["new"]
    assert new.source_actor_id == "other"  # Attribution and duration owner are separate.
    if not skipped:
        assert new.expires_on == name and not holder.turn_flags  # Legacy saves remain unstamped.
        return
    assert new.expires_on == clocks.token("end", "owner", 4)
    assert not clocks.due(engine, new.expires_on, "other", skipped=skipped)
    holder.turns_started = 2
    engine.state.current_actor_id = "owner"
    assert not clocks.due(engine, new.expires_on, None, skipped=skipped)
    assert clocks.due(engine, new.expires_on, "owner", skipped=skipped)
