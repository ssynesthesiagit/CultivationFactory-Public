"""The printed form choice designates each new physical vessel, not only a doll-free hand.

Puppet Strike lets the puppeteer pick Bludgeoning, Piercing or Slashing "when you designate the
vessel's form". A freshly learned puppeteer (nonempty initiation receipt, no completed Long Rest
product yet) and a puppeteer carrying an intact prepared doll must both be able to designate a
scene prop's form at the table, and a strike from that prop must use the chosen type.
"""
from combat.ext import placed
from combat.gate2_rolls import DeterministicRollAuthority
from combat.tabletop import normalize_map
from tests.auto28_puppetry_support import resolve, turn
from tests.puppet_scene_support import (
    A, B, PID, OTHER, SPHERE, TOOLS, choose, cold, native, _raise_at,
)


def _always_hit(monkeypatch):
    original = DeterministicRollAuthority.d20

    def hit(self, **kwargs):
        result = original(self, **kwargs)
        if "ATTACK" in kwargs.get("reason", "").upper():
            return result.model_copy(update={"natural_result": 15, "total": 100})
        return result

    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)


def _commit(combat, table, mid, actor_id, pick):
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor_id and pick(c))
    view = table.state(mid)
    menu = view["menu"]
    result, _prompts = resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers))
    assert result["status"] == "COMMITTED"


def _match_with_scene_prop(tmp_path, monkeypatch, *, prepared):
    """A native puppeteer in a journey with one unattended crate prop, optionally rested."""
    _always_hit(monkeypatch)
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    scene = combat.tabletop_maps.save(normalize_map({
        "map_id": "scene-form", "display_name": "Scene form",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
        "objects": [{"id": 1, "kind": "crate", "name": "puppet prop", "x": 5, "y": 6, "hp": 20}],
    }))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    if prepared:
        # The completed Long Rest product is the only puppet vessel this owner physically has.
        option = next(o for o in combat.journey_menu(jid, A)["options"]
                      if o["kind"] == "puppet_initiation_rest" and o["payload"]["form"] == "bludgeoning")
        state = combat.journey_act(jid, state["revision"], A, option["kind"], option["payload"])
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    return combat, table, mid


def _scene_vessel(combat, mid):
    engine = combat._load_session(mid).engine
    return next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("scene_object_id") == "object:map.1")


def test_a_freshly_learned_puppeteer_designates_the_scene_prop_form_and_strikes_with_it(tmp_path, monkeypatch):
    """F5R finding 1: without the form picks, Raise permanently designates Bludgeoning."""
    combat, table, mid = _match_with_scene_prop(tmp_path, monkeypatch, prepared=False)
    turn(table, mid, A)
    _commit(combat, table, mid, A, lambda c: c.display_name == "Vessel form: Piercing")
    combat, table = cold(tmp_path)
    assert not placed.of(combat._load_session(mid).engine, "vessel", owner_id=A)  # a pick raises nothing

    _raise_at(table, combat, mid, A, (5, 6))
    combat, table = cold(tmp_path)
    assert placed.data(_scene_vessel(combat, mid))["form"] == "piercing"

    turn(table, mid, B)
    turn(table, mid, A)
    _commit(combat, table, mid, A, lambda c: c.display_name.startswith("Puppet Strike (from the vessel)")
            and c.display_name.endswith("(5,6)"))
    combat, table = cold(tmp_path)
    damage = [e for e in combat._load_session(mid).engine.events
              if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == A and B in e.target_ids]
    assert damage and str(damage[-1].payload["damage_type"]).lower() == "piercing"


def test_an_intact_prepared_doll_keeps_its_own_form_and_still_allows_another_vessel_form(tmp_path, monkeypatch):
    """F5R finding 1: the doll's fixed form must not lock the form of a different vessel."""
    combat, table, mid = _match_with_scene_prop(tmp_path, monkeypatch, prepared=True)
    turn(table, mid, A)
    _commit(combat, table, mid, A, lambda c: c.display_name == "Vessel form: Slashing")
    combat, table = cold(tmp_path)

    _raise_at(table, combat, mid, A, (3, 5))
    combat, table = cold(tmp_path)
    doll = next(z for z in placed.of(combat._load_session(mid).engine, "vessel", owner_id=A)
                if placed.data(z).get("item_instance_id"))
    assert placed.data(doll)["form"] == "bludgeoning"

    # Raising spent the Action; take the opposing turn before raising a second body.
    turn(table, mid, B)
    turn(table, mid, A)
    _raise_at(table, combat, mid, A, (5, 6))
    combat, table = cold(tmp_path)
    assert placed.data(_scene_vessel(combat, mid))["form"] == "slashing"
