"""Synthetic Hunt 12 fights through table preview, commit and disk reload."""
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act
from tests.iron_fist_support import answering_iron_fist  # Iron Fist damage-type question (L45)

ME, FOE = "actor:factory.fix12", "actor:factory.fix12-foe"
STAMINA = "resource:core.stamina"


def fight(tmp_path, mids=(), *, cl=18, dc=100, kit=None, foe_mids=()):
    doc = sheet(list(mids), cl=cl, dc=dc, primary="Stamina", score=18, kit=kit)
    foe = sheet(list(foe_mids), cl=cl, primary="Stamina")
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundles = [compile_character(doc, actor_id=ME, reaction_plan={"ask": True}),
               compile_character(foe, actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="FIX12",
        display_name="Hunt 12 regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def candidate(combat, mid, name):
    return next(c for c in combat._load_session(mid).engine.legal_candidates() if name(c))


def send(combat, table, mid, chosen, answers=(), *, auto=False):
    if auto:
        real = combat.controller

        class SelectedController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = SelectedController()
        try:
            return answering_iron_fist(lambda given: table.auto_step(mid, 0, given))(list(answers))
        finally:
            combat.controller = real
    state = table.state(mid)
    menu = state["menu"]
    return answering_iron_fist(lambda given: table.act(mid, chosen.candidate_id, menu["decision_id"], menu["state_version"],
                                                       state["last_sequence"], given))(list(answers))


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def hit_dice(monkeypatch, *, critical=False, save_roll=None):
    from combat.gate4_engine import Gate4ControllerEngine
    original = Gate4ControllerEngine._resolve_attack_spec

    def resolve(engine, *args, **kwargs):
        script(engine, [20 if critical else 18, *([1] * 60)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)
    if save_roll is not None:
        original_save = Gate4ControllerEngine._roll_save

        def roll_save(engine, *args, **kwargs):
            script(engine, [save_roll])
            return original_save(engine, *args, **kwargs)

        monkeypatch.setattr(Gate4ControllerEngine, "_roll_save", roll_save)


def event_hook(monkeypatch, function):
    """Add a synthetic trigger without hiding shipped event subscribers."""
    from combat import ext
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS["event"], function])
