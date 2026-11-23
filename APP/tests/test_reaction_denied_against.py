"""'Cannot take Reactions against you' only denies Reactions against the user (fight audit 2026-09-29: Jolt took every
Reaction away); 'cannot make Opportunity Attacks' is no_opportunity_attacks."""

from combat import typed_executor, typed_reactions, unmaking
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from factory_authoring import typed_mechanics
from factory_authoring.typed_structure import dedupe
from tests.test_generic_reactions import REACTOR_SHEET, _mechanic
from tests.test_reaction_reach import COUNTER, FRIEND, ME, ROOT, _ctx, _engine


def test_parser_scopes_reaction_denial_by_its_own_clause():
    lines = [
        ("The target is Dazed, cannot take Reactions until the end of its next turn, "
         "and you may move 5 feet without provoking Opportunity Attacks from it.", "all"),
        ("The target cannot take Reactions against you until the start of your next turn.", "against_source"),
    ]
    for line, scope in lines:
        rows = typed_mechanics._line_effects(line)
        denial = next(row for row in rows if row.get("type") == "reaction_denied" or row.get("condition") == "reaction_denied")
        assert denial["reaction_scope"] == scope


def _ids(actor):
    return {c.condition_id for c in actor.conditions.values()}


def test_against_you_denies_only_reactions_against_the_user():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_denied", "reaction_scope": "against_source", "applies_to": "target", "on": "against you",
                                                        "evidence": "The target cannot take Reactions against you until the start of your next turn."}])
    assert "condition:typed.reaction_denied" not in _ids(foe)
    assert unmaking.reactions_denied_against(foe, me)


def test_plain_cannot_take_reactions_still_denies_all_and_opportunity_attacks_are_their_own():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_denied", "reaction_scope": "all", "applies_to": "target", "evidence": "it cannot take Reactions"}])
    assert "condition:typed.reaction_denied" in _ids(foe)
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{"type": "reaction_denied", "reaction_scope": "opportunity", "applies_to": "target", "evidence": "it cannot make opportunity attacks"}])
    assert _ids(foe) & {"condition:typed.no_opportunity_attacks"} and "condition:typed.reaction_denied" not in _ids(foe)


def test_scoped_denial_persists_through_reload_and_allows_reacting_against_third_creature(tmp_path):
    authority = {"mechanics": {
        "DENY": {**_mechanic("DENY", "Scoped Denial", "action",
                             [{"type": "reaction_denied", "reaction_scope": "against_source", "applies_to": "target",
                               "evidence": "cannot take Reactions"}]),
                 "range": {"kind": "feet", "feet": 30}},
        "COUNTER": _mechanic("COUNTER", "Counter", "reaction", [COUNTER], trigger="A creature misses you with a melee attack"),
    }}
    bundles = [
        compile_character({**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["DENY"]}},
                          actor_id=ME, typed_authority=authority),
        compile_character({**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": []}},
                          actor_id=FRIEND, typed_authority=authority),
        compile_character({**REACTOR_SHEET, "spheres_and_talents": {"learned_talent_record_ids": ["COUNTER"]}},
                          actor_id=AN, typed_authority=authority),
    ]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FRIEND, AN], {ME: "team:a", FRIEND: "team:a", AN: "team:b"},
        {ME: {"x": 2, "y": 2}, FRIEND: {"x": 2, "y": 3}, AN: {"x": 3, "y": 2}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [ME, FRIEND], [AN],
        control_modes={ME: "MANUAL", FRIEND: "MANUAL", AN: "MANUAL"},
        match_seed="REACTION-SCOPE", display_name="Reaction scope reload", maximum_rounds=10,
    )["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        menu = table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    state = table.state(mid)
    menu = state["menu"]
    deny_group = next(g for g in menu["actions"] if g["label"] == "Scoped Denial")
    assert table.act(mid, deny_group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"])["status"] == "COMMITTED"

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine
    me, friend, foe = reloaded.state.actors[ME], reloaded.state.actors[FRIEND], reloaded.state.actors[AN]
    counter_row = next(r for r in reloaded.typed_reaction_rows[AN] if r["feature_id"] == "COUNTER")
    assert unmaking.reactions_denied_against(foe, me)
    assert not unmaking.reactions_denied_against(foe, friend)
    assert not typed_reactions.can_use_reaction(reloaded, foe, me, counter_row)
    assert typed_reactions.can_use_reaction(reloaded, foe, friend, counter_row)


def test_plain_reaction_scope_all_denies_every_reaction():
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1}, friend_at={"x": 3, "y": 1})
    me, friend, foe = engine.state.actors[ME], engine.state.actors[FRIEND], engine.state.actors[AN]
    typed_executor.run_effects(_ctx(engine, me, foe), [{
        "type": "reaction_denied", "reaction_scope": "all", "applies_to": "target",
        "evidence": "it cannot take Reactions",
    }])
    assert "condition:typed.reaction_denied" in _ids(foe)
    assert not typed_reactions.can_react(engine, foe)
    assert not typed_reactions.can_use_reaction(engine, foe, friend, {"feature_id": "COUNTER", "block": "generic"})


def test_dedupe_keeps_scoped_and_plain_reaction_denied_for_same_subject():
    scoped = {"type": "reaction_denied", "applies_to": "target", "reaction_scope": "against_source", "evidence": "cannot take Reactions"}
    plain = {"type": "reaction_denied", "applies_to": "target", "reaction_scope": "all", "evidence": "cannot take Reactions"}
    assert dedupe([scoped, plain]) == [scoped, plain]
