"""Printed reaction Range measures the affected creature, through real tables."""
import json
import zipfile

import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.anchor_support import ME, FRIEND, FOE, PROJECTS
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act

GRACE = "tianxia.talent.beauty.grace_that_shames_the_cruel"

PRINTED_REFERENCES = [
    ("TAL_CHAINS_ANCHOR_LINK_BASE", "subject"),
    ("BEAUTY_BASE_TURN_THE_BLADE_ASIDE", "source"),
    (GRACE, "source"),
    ("tianxia.talent.chains.chain_the_falling_star", "subject"),
    ("tianxia.talent.chains.iron_link_guard", "subject"),
    ("tianxia.talent.chains.rescue_line", "subject"),
    ("tianxia.talent.chains.restraining_hook", "subject"),
    ("tianxia.talent.yang.the_completed_action_beneath_heaven", "subject"),
    ("tianxia.talent.yin.the_unfinished_action_beneath_heaven", "subject"),
]


@pytest.mark.parametrize("feature,reference", PRINTED_REFERENCES)
def test_newly_bounded_rows_measure_audited_creature(feature, reference):
    """riders/c13 69dd5070 retains explicit Anchor trigger ranges
    (approving C13r3.review.md); those rows need no inferred range_reference field.
    """
    from combat.factory_compiler import compile_character
    from combat.typed_reactions import _generic_in_range
    from tests.test_forced_movement_reactions import _engine, REACTOR, LEE, AN

    rows = [r for r in compile_character(sheet([feature], cl=17), actor_id=REACTOR)["typed_reactions"]
            if r["feature_id"] == feature and (r.get("range_reference")
                or feature == "TAL_CHAINS_ANCHOR_LINK_BASE" and r.get("range_ft") is not None)]
    assert rows
    engine = _engine([])
    reactor, subject, source = (engine.state.actors[a] for a in (REACTOR, LEE, AN))
    reactor.position = Position(x=1, y=1)
    for row in rows:
        assert row.get("range_reference", reference) == reference
        near = Position(x=2, y=1)
        far = Position(x=2 + row["range_ft"] // 5, y=1)
        for legacy in (False, True):
            tested = dict(row)
            if legacy:
                tested["range_ft"] = None
                tested.pop("range_reference", None)
            before = json.dumps(tested, sort_keys=True)
            subject.position, source.position = near, far
            assert _generic_in_range(engine, reactor, subject, tested, subject=subject, source=source) == (reference == "subject")
            subject.position, source.position = far, near
            assert _generic_in_range(engine, reactor, subject, tested, subject=subject, source=source) == (reference == "source")
            assert json.dumps(tested, sort_keys=True) == before


def _accept(service, table, mid, predicate, *, use=None):
    state = table.state(mid)
    menu = state["menu"]
    candidate = next(c for c in service._load_session(mid).engine.legal_candidates() if predicate(c))
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    prompts, answers = [], []
    for _ in range(10):
        result = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED"
        assert service._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        choice = prompt.get("choice") or {}
        answer = {**prompt["context"], "selection": "USE" if prompt["reaction"] == use else "DECLINE"}
        if choice and not choice.get("allow_decline", True):
            answer.update(selection="USE", option_ids=[o["id"] for o in choice["options"][:choice.get("minimum", 1)]])
        answers.append(answer)
    raise AssertionError("too many reactions")


def _table(tmp_path, feature, *, victim_ft, attacker_ft, legacy=False, dc=60):
    for project, talents in zip(PROJECTS, ([feature], [], ["AIR_BASE_WIND_LASH"])):
        doc = sheet(talents, cl=5, dc=dc)
        doc["identity"]["display_name"] = {PROJECTS[0]: "Protector", PROJECTS[1]: "Traveler", PROJECTS[2]: "Attacker"}[project]
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 60
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS[0], {"mode": "ask"}, {feature})
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Range reference yard", "width_squares": 25,
        "height_squares": 10, "walls": [], "starts": {
            "team1": [[3, 4], [3 + victim_ft // 5, 4]], "team2": [[3 + attacker_ft // 5, 4]]}})
    modes = {actor: "MANUAL" for actor in (ME, FRIEND, FOE)}
    arena = "battlefield:map.range-reference-yard"
    if legacy:
        # Supply old null-range rows before genesis, without rewriting a
        # committed bundle or patching compilation/runtime functions.
        from combat.factory_compiler import compile_character
        bundles = [service._with_prefight(compile_character(service._factory_owner_sheet(p),
            actor_id=a, reaction_plan=ButtonStore(tmp_path / "tabletop_buttons").get(p).get("reactions")), None)
            for p, a in zip(PROJECTS, (ME, FRIEND, FOE))]
        for bundle in bundles:
            for row in bundle["typed_reactions"]:
                if row["feature_id"] == feature:
                    row["range_ft"] = None
                    row.pop("range_reference", None)
        mid = service._finish_factory_match(bundles, [ME, FRIEND, FOE],
            {ME: "team:factory", FRIEND: "team:factory", FOE: "team:opponents"},
            {ME: {"x": 3, "y": 4}, FRIEND: {"x": 3 + victim_ft // 5, "y": 4},
             FOE: {"x": 3 + attacker_ft // 5, "y": 4}}, service.factory_arenas()[arena], [ME, FRIEND], [FOE],
            control_modes=modes, match_seed="GRACE-RANGE", display_name=None, maximum_rounds=8)["match_id"]
    else:
        mid = service.create_factory_match(project_ids=list(PROJECTS[:2]), opponent_actor_ids=[FOE],
            control_modes=modes, arena_id=arena, match_seed="GRACE-RANGE", maximum_rounds=8)["match_id"]
    table = TabletopService(service, tmp_path)
    return service, table, mid


def _advance(table, mid, actor):
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("actor turn not reached")


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("attacker_ft,victim_ft,offered", [(30, 80, True), (80, 30, False)])
def test_grace_range_measures_marked_attacker_at_table(tmp_path, attacker_ft, victim_ft, offered, legacy):
    from combat.typed_executor import bears_mark
    from combat.gate3_storage import TYPED_BUNDLES_FILE

    # A successful Catch the Eye save still allows a Beauty Mark, without
    # Captivated forcing the next attack to target the Protector instead.
    service, table, mid = _table(tmp_path, GRACE, victim_ft=victim_ft, attacker_ft=min(attacker_ft, 60), legacy=legacy, dc=1)
    sealed = (service._match_dir(mid) / TYPED_BUNDLES_FILE).read_bytes()
    _advance(table, mid, ME)
    _accept(service, table, mid, lambda c: "Catch the Eye" in c.display_name and c.target_ids == (FOE,))
    assert bears_mark(service._load_session(mid).engine.state.actors[FOE], ME, "Beauty Mark")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    _advance(table, mid, FOE)
    if attacker_ft > 60:
        # A real accepted move carries the marked attacker beyond 60 feet.
        _accept(service, table, mid, lambda c: c.kind.value == "MOVE" and c.destination == Position(x=3 + attacker_ft // 5, y=4))
    engine = service._load_session(mid).engine
    assert engine.grid.distance_ft(engine.state.actors[ME].position, engine.state.actors[FOE].position) == attacker_ft
    assert engine.grid.distance_ft(engine.state.actors[ME].position, engine.state.actors[FRIEND].position) == victim_ft
    prompts = _accept(service, table, mid, lambda c: "Wind Lash" in c.display_name and c.target_ids == (FRIEND,),
                      use="Grace That Shames the Cruel")
    assert any(p["reaction"] == "Grace That Shames the Cruel" for p in prompts) == offered, (
        [(p["reaction"], [(o["id"], o["label"][:60]) for o in (p.get("choice") or {}).get("options", [])]) for p in prompts],
        [(e.event_type, e.source_definition_id, e.actor_id) for e in service._load_session(mid).engine.events
         if e.event_type in {"ATTACK_ROLLED", "DAMAGE_COMMITTED", "REACTION_RESOLVED"}][-8:])
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == GRACE for e in loaded.engine.events) == offered
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert (service._match_dir(mid) / TYPED_BUNDLES_FILE).read_bytes() == sealed


def test_iron_link_guard_self_range_measures_protected_creature(tmp_path):
    feature = "tianxia.talent.chains.iron_link_guard"
    service, table, mid = _table(tmp_path, feature, victim_ft=5, attacker_ft=40)
    _advance(table, mid, FOE)
    prompts = _accept(service, table, mid, lambda c: "Wind Lash" in c.display_name and c.target_ids == (ME,),
                      use="Iron Link Guard")
    assert any(p["reaction"] == "Iron Link Guard" for p in prompts)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == feature for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"
