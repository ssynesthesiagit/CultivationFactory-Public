"""Unlimited admission at the table, sealed capacity rules, and independent expiry."""

import json
import zipfile

import pytest

from combat import concentration, zones
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_riders_lane11 import MOON, ROOT, _sheet


@pytest.mark.parametrize("auto_turn", [False, True])
def test_seven_moons_table_commit_reload_and_exact_expiry(tmp_path, auto_turn):
    caster, foe = [FACTORY_ACTOR_PREFIX + pid for pid in ("r11-capacity", "r11-capacity-foe")]
    documents = [_sheet(MOON), _sheet(MOON)]
    documents[1]["path_and_subpath"] = {"path_feature_record_ids": []}
    documents[0]["ability_scores_and_statistics"] = {
        **documents[0]["ability_scores_and_statistics"],
        "primary_resource": {"name": "Qi", "maximum": 1000}}
    for aid, doc in zip((caster, foe), documents):
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [compile_character(doc, actor_id=aid) for aid, doc in zip((caster, foe), documents)],
        [caster, foe], {caster: "team:factory", foe: "team:opponents"},
        {caster: {"x": 3, "y": 6}, foe: {"x": 13, "y": 8}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [caster], [foe],
        control_modes={caster: "MANUAL", foe: "LOCAL_AUTO" if auto_turn else "MANUAL"},
        match_seed="R11-UNLIMITED", display_name="Seven lunar fields", maximum_rounds=20)["match_id"]
    original = combat.controller
    selected = None
    selected_boundary = None

    class SelectedController:
        """Choose a legal table candidate through the actual automatic commit path."""

        def choose_primary_action(self, context):
            # Table polling also asks the installed controller to rank a menu.
            # The scripted selection belongs only to take()'s exact boundary;
            # ranking a previous/next actor uses the ordinary controller.
            if (context.actor_id, context.state_version) != selected_boundary:
                return original.choose_primary_action(context)
            candidate = next(c for c in context.legal_candidates if c.candidate_id == selected)
            return ManualControllerAdapter(lambda _context: (candidate.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    if auto_turn:
        combat.controller = SelectedController()

    def take(cid):
        nonlocal selected, selected_boundary
        selected = cid
        menu = table.state(mid)["menu"]
        selected_boundary = (menu['actor_id'], menu['state_version'])
        result = (table.auto_step(mid, 0) if auto_turn and menu["actor_id"] == foe else
                  table.act(mid, cid, menu["decision_id"], menu["state_version"], 0))
        assert result["status"] == "COMMITTED", result

    def end_turn():
        session = combat._load_session(mid)
        take(next(c.candidate_id for c in session.engine.legal_candidates() if c.kind.value == "END_TURN"))

    owned = []
    for count in range(1, 8):
        while table.state(mid)["menu"]["actor_id"] != caster:
            end_turn()
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
                         if c.source_definition_id in engine.action_catalog
                         and engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("source") == MOON
                         and c.destination is not None and (c.destination.x, c.destination.y) == (3, 6))
        take(candidate.candidate_id)
        # New service/session instances force a disk reload, not a cached engine.
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        actor = session.engine.state.actors[caster]
        current = zones.typed_zones(session.engine)
        assert len(concentration.sources(actor)) == count
        assert len(current) == count
        assert set(owned) <= {zone.zone_id for zone in current}
        owned = sorted((zone.zone_id for zone in current), key=lambda zid: int(zid.rsplit(":", 1)[-1]))
        assert session.verify()["status"] == "PASS"
        assert session.mechanical.replay()["status"] == "PASS"
        if count < 7:
            end_turn()

    # Printed one-minute lifetime is still enforced for each independently created
    # copy. These END_TURN commits must expire the oldest, not all seven fields.
    while True:
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        current = zones.typed_zones(session.engine)
        if len(current) < 7:
            break
        end_turn()
    assert len(current) == 6
    assert owned[0] not in {zone.zone_id for zone in current}
    assert set(owned[1:]) == {zone.zone_id for zone in current}
    assert len(concentration.sources(session.engine.state.actors[caster])) == 6
    assert session.verify()["status"] == "PASS"


def test_capacity_snapshot_is_independent_of_later_rule_edits(monkeypatch):
    from tests.test_multi_concentration import _engine

    engine, actor = _engine(1)
    monkeypatch.setitem(concentration.rules(), "capacity", "cultivation_level")
    for i in range(7):
        engine._start_concentration(actor, f"action:{i}")
    assert len(concentration.sources(actor)) == 7


def test_prefight_service_accepts_two_concentration_buffs_at_cl1(tmp_path):
    from tests.test_prefight import SHEET

    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": 1}}
    bundle = compile_character(sheet, actor_id=FACTORY_ACTOR_PREFIX + "prefight-unlimited")
    options = bundle["prefight"]["options"]
    picks = [next(o["action_id"] for o in options if o["name"] == name)
             for name in ("Meld: Clearsight", "Karmic Sight")]
    combat = CombatService(ROOT, tmp_path)
    prepared = combat._with_prefight(bundle, {bundle["actor_id"]: picks})
    assert prepared["prefight"]["picks"] == picks
    assert prepared["concentration_rules"]["capacity"] == "unlimited"
