"""CONCSAVE2: a rider added to a confirmed hit is part of that hit's single Concentration save.

Bloodletting Strike (combat/ext/blood_riders.py ``thread_augments``, the after_hit_choice seam) adds
1d6 Necrotic damage to the triggering hit. Its damage packet must carry the hit's AttackDamage (same
roll_id) so the hit makes ONE Concentration save judged on the combined damage
(combat/attached_concentration.py). Built with a bare Context it lost that provenance: the rider's
packet made its own immediate save and the hit's deferred save was then judged on the rider alone (or,
on a successful save, made a second one).

These tests drive a real Blood Thread hit through the engine's legal candidates and choice transport,
so they fail if ``thread_augments`` stops building the child of the triggering hit.
"""

from combat.damage_context import AttackDamage
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, ReactionDecision
from combat.typed_executor import Context
from tests import test_auto_lane1 as L1
from tests.test_auto_docket import AN

BL = "tianxia.talent.blood."
QI = "resource:core.qi"


def _bleeder(talents, cl=10, dc=50, qi=40):
    """A Blood cultivator owning Blood Thread plus ``talents``, beside one foe."""
    sheet = L1._sheet("BLOOD_BASE_BLOOD_THREAD", cl=cl, dc=dc)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [BL + name for name in talents]
    engine = L1._engine(compile_character(sheet, actor_id=L1.ME))
    me, foe = engine.state.actors[L1.ME], engine.state.actors[AN]
    me.resource_maximums[QI] = me.resources[QI] = qi
    foe.maximum_hp = foe.current_hp = 500
    return engine, me, foe


def _answers(engine, picks):
    """Immediate choice transport: accept the first option unless ``picks`` answers a choice kind."""
    def provider(request):
        if not str(request["reaction_source_id"]).startswith("choice:needle."):
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE",
                                    option_ids=()), None
        options = list(request["legal_option_ids"])
        pick = picks.get(str(request["reaction_source_id"]).split(".")[-1])
        chosen = pick(options) if pick else options[:1]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if chosen is None else "USE",
                                option_ids=tuple(chosen or ())), None

    engine.set_reaction_provider(provider)


def _cast(engine, name, target):
    L1._ready(engine)
    found = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == L1.ME
             and tuple(c.target_ids or ()) == (target,)]
    assert found, f"{name!r} on {target} is not legal"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=L1.ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination, option_ids=candidate.option_ids))
    return engine.events[before:]


def test_one_blood_thread_hit_with_bloodletting_makes_one_combined_save(monkeypatch):
    engine, me, foe = _bleeder(["bloodletting_strike"])
    engine._start_concentration(foe, "action:held_by_foe")
    packets, saves = [], []
    original_commit, original_check = engine._commit_damage, engine._concentration_check

    def commit_spy(target, amount, damage_type, source_definition_id, source_actor_id, intent, **kwargs):
        if target is foe:
            packets.append((damage_type, amount, kwargs.get("attack_context")))
        return original_commit(target, amount, damage_type, source_definition_id, source_actor_id, intent, **kwargs)

    def check_spy(actor, hp_damage, **kwargs):
        if actor is foe:
            saves.append(hp_damage)
        return original_check(actor, hp_damage, **kwargs)

    monkeypatch.setattr(engine, "_commit_damage", commit_spy)
    monkeypatch.setattr(engine, "_concentration_check", check_spy)
    _answers(engine, {})  # the Bloodletting offer is accepted (its first option)
    events = _cast(engine, "Blood Thread", AN)

    # The hit's own packet and the Bloodletting rider both reached the foe, as one attack roll.
    assert len(packets) == 2, packets
    assert all(context is not None for _, _, context in packets), "a rider packet lost the hit's attack provenance"
    assert len({context.roll_id for _, _, context in packets}) == 1, "rider and hit must share one attack roll"
    # The rider is part of this hit: one save, judged on the combined damage of that hit.
    combined = sum(int(event.payload.get("reduced_to") or 0) for event in events
                   if event.event_type == "DAMAGE_COMMITTED" and foe.entity_id in (event.target_ids or ()))
    assert combined > 0
    assert saves == [combined], saves


def test_hit_child_inherits_the_hits_critical_and_defense_state_for_the_rider():
    """Rider dice belong to the hit's damage, so on a critical hit they are doubled like the rest of
    the attack's dice; the rider also keeps the hit's declared defenses. A standalone Context has neither."""
    engine, me, foe = _bleeder([])
    action = ActionDefinition(source_definition_id="action:blood_thread", display_name="Blood Thread",
                              owner_id=me.entity_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY")
    ctx = Context(engine, me, action, None, {}, [foe], foe, {})
    spec = {"defense": "marker"}
    ctx.attack_damage_context = AttackDamage(source_id="action:blood_thread", attacker_id=me.entity_id,
                                             target_id=foe.entity_id, attack_index=1, roll_id="roll:hit",
                                             natural_result=20, total=24, critical=True)
    ctx.critical_hit = True
    ctx.attack_defense_spec = spec
    child = ctx.on_hit_context(foe, damage_cache={})
    assert child.critical_hit is True
    assert child.attack_defense_spec is spec
    standalone = Context(engine, me, action, None, {}, [foe], foe, {}).on_hit_context(foe, damage_cache={})
    assert standalone.critical_hit is False
