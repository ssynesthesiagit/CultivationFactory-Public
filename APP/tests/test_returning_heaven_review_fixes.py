"""F1 review regressions: real acquisition, table choices, commit and cold replay.

Extra ordinary deliveries are sealed through the compiler's test fixture seam;
ownership/Returning-Heaven progression and all triggering events remain native.
No model transport or browser is used.
"""
import json
from types import SimpleNamespace

import pytest

from combat import ext
from combat.gate2_runtime_models import Position
from tests.hunt12_support import hit_dice
from tests.worker2_support import candidate, reload, settle, turn
from tests.test_returning_heaven_native import OWNER, FOE, P, M, IRON, start, move, strike, checked


def extra_deliveries(monkeypatch):
    """Compile two ordinary reach-10 palms plus ineligible unarmed techniques."""
    ext.effects()
    def additions(info):
        if info["actor_id"] != OWNER:
            return None
        base=next(a for a in info["actions"] if a.owner_id==OWNER
                  and (a.parameters.get("typed") or {}).get("attack_action")
                  and any(e.get("attack_kind")=="unarmed" for e in a.parameters["typed"]["effects"]))
        rows=[]
        for suffix, name, params, costs in [
            ("zz_long", "Long palm", {}, ()),
            ("zz_wide", "Wide palm", {}, ()),
            ("zz_paid", "Paid palm technique", {}, (("resource:core.stamina", 1),)),
            ("zz_stance", "Unavailable stance palm", {"requires_condition":"condition:test.missing_stance"}, ()),
        ]:
            action=base.model_copy(deep=True,update={
                "source_definition_id":base.source_definition_id.rsplit(".",1)[0]+"."+suffix,
                "display_name":name,"range_ft":10,"reach_ft":None,"costs":costs})
            # Native ordinary melee catalogs encode reach in range_ft.
            action.parameters.update(params)
            # Catch accidental execution of the whole Attack action's count.
            attack=next(e for e in action.parameters["typed"]["effects"] if e.get("type")=="attack")
            attack["count_by_cl"]=[[1,30,3]]
            rows.append(action)
        return rows
    monkeypatch.setitem(ext._HOOKS,"compile_actions",[*ext._HOOKS.get("compile_actions",[]),additions])


@pytest.mark.parametrize("endpoint,delivery",[(6,"Long palm"),(6,"Wide palm"),(7,"Long palm"),(7,"Wide palm")])
def test_rebound_preserves_all_legal_unarmed_deliveries_and_reach(tmp_path,monkeypatch,endpoint,delivery):
    hit_dice(monkeypatch,save_roll=1)
    extra_deliveries(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=["tianxia.talent.space.spatial_displacement"])
    move(combat,table,mid,7)
    move(combat,table,mid,5)
    turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    source=next(a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id==OWNER and a.display_name==delivery)
    short_names={a.display_name for a in engine.action_catalog.values() if a.owner_id==OWNER
                 and max(a.range_ft or 0,a.reach_ft or 0)<=5
                 and (a.parameters.get("typed") or {}).get("attack_action")
                 and any(e.get("attack_kind")=="unarmed" for e in (a.parameters.get("typed") or {}).get("effects",[]))}
    assert short_names
    before=len(engine.events)
    prompts=settle(table,mid,candidate(combat,mid,"Spatial Displacement",target=OWNER).candidate_id,choices={
        "choice:needle.subject_destination":"cell:4,6",
        "choice:needle.rebounding_assault":"use",
        "choice:needle.rebound_move":(f"cell:{endpoint},6",None),
        "choice:needle.rebound_strike":source,
        "choice:needle.rebound_hit":"prone",
        "choice:needle.gather_and_return":None,
        "choice:needle.fact_admission.momentum_eligibility":"genuine"})
    engine=checked(tmp_path,mid)
    menu=next(p for p in prompts if p["context"]["reaction_source_id"]=="choice:needle.rebound_strike")
    labels={o["label"] for o in menu["choice"]["options"]}
    assert {"Long palm","Wide palm"}<=labels
    assert "Paid palm technique" not in labels and "Unavailable stance palm" not in labels
    # The shorter first delivery must not hide either legal reach-10 delivery.
    assert bool(short_names & labels)==(endpoint==7)
    attacks=[e for e in engine.events[before:] if e.event_type=="ATTACK_ROLLED" and e.actor_id==OWNER]
    assert len(attacks)==1 and attacks[0].source_definition_id==source
    assert engine.state.actors[OWNER].position==Position(x=endpoint,y=6)
    assert any(c.condition_id.endswith(".prone") for c in engine.state.actors[FOE].conditions.values())


def test_rebound_automatic_seat_receives_the_complete_delivery_menu(tmp_path,monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    hit_dice(monkeypatch,save_roll=1)
    extra_deliveries(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=["tianxia.talent.space.spatial_displacement"])
    move(combat,table,mid,7)
    move(combat,table,mid,5)
    turn(table,mid,FOE)
    engine=reload(tmp_path,mid)
    wide=next(a.source_definition_id for a in engine.action_catalog.values() if a.owner_id==OWNER and a.display_name=="Wide palm")
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode="LOCAL_AUTO")
    real=combat.controller
    seen=[]
    class FakeTransport:
        def choose_reaction(self,context):
            if context.reactor_id!=OWNER:
                return real.choose_reaction(context)
            rid=context.reaction_source_id
            selected={"choice:needle.rebounding_assault":"use","choice:needle.rebound_move":"cell:6,6",
                      "choice:needle.rebound_strike":wide,"choice:needle.rebound_hit":"prone"}.get(rid)
            if rid=="choice:needle.rebound_move" and "cell:6,6" not in context.legal_option_ids:
                selected=None
            if rid=="choice:needle.rebound_strike":
                seen.append(set(context.legal_option_ids))
            from combat.gate2_runtime_models import ReactionDecision
            decision=ReactionDecision(checkpoint=context.checkpoint,reactor_id=context.reactor_id,
                reaction_source_id=rid,selection="USE" if selected else "DECLINE",
                option_ids=(selected,) if selected else ())
            return ManualControllerAdapter(lambda _:("",()),reaction_chooser=lambda _:decision).choose_reaction(context)
        def __getattr__(self,key):
            return getattr(real,key)
    combat.controller=FakeTransport()
    try:
        prompts=settle(table,mid,candidate(combat,mid,"Spatial Displacement",target=OWNER).candidate_id,choices={
            "choice:needle.subject_destination":"cell:4,6",
            "choice:needle.fact_admission.momentum_eligibility":"genuine"})
    finally:
        combat.controller=real
    engine=checked(tmp_path,mid)
    expected={a.source_definition_id for a in engine.action_catalog.values()
              if a.owner_id==OWNER and a.display_name in {"Long palm","Wide palm"}}
    assert seen and all(menu==expected for menu in seen)
    assert not any(p["context"]["reactor_id"]==OWNER for p in prompts)
    assert any(e.event_type=="ATTACK_ROLLED" and e.source_definition_id==wide for e in engine.events)


@pytest.mark.parametrize("segments",[
    ("cell:3,5","cell:2,5","cell:2,4"),
    ("cell:3,5",None),
])
def test_avalanche_keeps_remaining_budget_across_committed_segments(tmp_path,monkeypatch,segments):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON])
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)["menu"]["end_turn"],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    turn(table,mid,FOE)
    row=next(c for c in reload(tmp_path,mid).legal_candidates() if c.kind=="MOVE" and c.destination==Position(x=4,y=6))
    settle(table,mid,row.candidate_id,choices={})
    turn(table,mid,OWNER)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[M]==4
    before=len(engine.events)
    prompts=settle(table,mid,strike(combat,mid,FOE).candidate_id,choices={
        "choice:needle.gather_and_return":("move","move","move"),
        "choice:needle.gather_move":segments})
    engine=checked(tmp_path,mid)
    moves=[e for e in engine.events[before:] if e.event_type=="MOVEMENT_COMMITTED"
           and e.source_definition_id==P+"gather_and_return"]
    expected=3 if len(segments)==3 else 1
    assert len(moves)==expected
    assert sum(e.payload["granted_cost_ft"] for e in moves)==5*expected
    assert all(e.payload["cost_ft"]==0 and not e.payload.get("forced") for e in moves)
    assert engine.state.actors[OWNER].resources[M]==1
    assert engine.state.actors[OWNER].position==(Position(x=2,y=4) if expected==3 else Position(x=3,y=5))
    menus=[p for p in prompts if p["context"]["reaction_source_id"]=="choice:needle.gather_move"]
    assert len(menus)==(3 if expected==3 else 2)
    assert not any("opportunity" in p["context"]["reaction_source_id"].lower() for p in prompts)


@pytest.mark.parametrize("reaction",["store","rebound"])
def test_reaction_prompt_names_actual_action_source_and_recipient(tmp_path,monkeypatch,reaction):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON],names={OWNER:"Wren",FOE:"Mara"})
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    selected=strike(combat,mid,OWNER)
    engine=reload(tmp_path,mid)
    action_name=engine.action_catalog[selected.source_definition_id].display_name
    source_name=engine.state.actors[FOE].display_name
    owner_name=engine.state.actors[OWNER].display_name
    prompts=settle(table,mid,selected.candidate_id,choices={
        "choice:needle.store_impact":"store" if reaction=="store" else None,
        "choice:needle.rebounding_assault":"use" if reaction=="rebound" else None,
        "choice:needle.rebound_hit":"prone",
        "choice:needle.fact_admission.momentum_eligibility":"genuine"})
    checked(tmp_path,mid)
    rid="choice:needle.store_impact" if reaction=="store" else "choice:needle.rebounding_assault"
    prompt=next(p for p in prompts if p["context"]["reaction_source_id"]==rid)
    # Test the actual prompt text, not an unrelated tooltip/recent-event fallback.
    text=prompt["moment"]
    assert action_name==prompt["action"]
    assert source_name!=owner_name
    assert all(name in text for name in (action_name,source_name,owner_name))
    assert "Reaction" in text and ("1 Stamina" if reaction=="store" else "2 Momentum") in text


def test_stock_comparison_uses_portable_validated_baseline(tmp_path,monkeypatch):
    import tests.test_a2_glass_stock as shared
    import tests.test_returning_heaven_stock as guard
    calls=[]
    monkeypatch.setattr(shared,"replay_base_or_skip",lambda:"portable-pinned-revision")
    monkeypatch.setenv("CF_STOCK_EVIDENCE",str(tmp_path/"evidence"))
    def capture(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(returncode=0,stdout=json.dumps({"state":{"terminal_result":{"outcome":"DRAW"}}}),stderr="")
    monkeypatch.setattr(shared.subprocess,"run",capture)
    guard.test_exact_base_stock(tmp_path,"portable")
    assert len(calls)==2 and calls[0][0][-1]=="portable-pinned-revision"
    assert all(kwargs["cwd"]==shared.APP for _,kwargs in calls)
