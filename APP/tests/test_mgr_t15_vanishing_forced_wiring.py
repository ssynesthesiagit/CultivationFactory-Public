"""Sol review F14R3 blocking item 4: the consent flag must travel from the printed forced-movement row through
typed_executor.block_forced_movement into the Vanishing reveal. The direct-hook tests in
test_mgr_t15_vanishing_forced_consent.py pick the flag by hand; these drive the typed executor with a real row,
so they fail if the willingness wiring is removed or inverted."""
import pytest
from combat import typed_executor
from combat.canonical import canonical_sha256
from tests.worker2_support import candidate, settle
from tests.test_mgr_t15_vanishing_native import setup, activate, held
from tests.worker2_support import OWNER, FOE, reload


def _push_row(engine, owner, foe, **extra):
    action = next(engine.action_catalog[a] for a in owner.action_ids)
    ctx = typed_executor.Context(engine, owner, action, None, {"numbers": {}, "effects": []}, [foe], foe)
    typed_executor.run_effects(ctx, [{"type": "forced_movement", "distance_ft": 5, "direction": "away",
                                      "applies_to": "target", **extra}])


def _ready(tmp_path):
    combat, table, mid = setup(tmp_path)
    activate(combat, table, mid)
    engine = reload(tmp_path, mid)
    return engine, engine.state.actors[OWNER], engine.state.actors[FOE]


def test_willing_row_push_through_typed_executor_does_not_reveal_owner(tmp_path):
    engine, owner, foe = _ready(tmp_path)
    assert held(owner, "invisible")
    start = (foe.position.x, foe.position.y)
    _push_row(engine, owner, foe, willing=True)
    assert (foe.position.x, foe.position.y) != start, "the typed push did not move the creature"
    assert held(engine.state.actors[OWNER], "invisible"), "a willing creature's typed push revealed the owner"


def test_row_without_willing_push_through_typed_executor_reveals_owner(tmp_path):
    engine, owner, foe = _ready(tmp_path)
    assert held(owner, "invisible")
    start = (foe.position.x, foe.position.y)
    _push_row(engine, owner, foe)
    assert (foe.position.x, foe.position.y) != start, "the typed push did not move the creature"
    assert not held(engine.state.actors[OWNER], "invisible"), "an unwilling typed push did not reveal the owner"
    assert held(engine.state.actors[OWNER], "vanishing_state")


@pytest.mark.parametrize("row_willing,answer,revealed", [(True, None, False), (False, "accept", False), (False, "refuse", True)])
def test_table_push_willingness_and_recipient_choice_survive_reload(tmp_path, row_willing, answer, revealed):
    def install(bundles):
        bundle = bundles[0]
        source = "action:test.vanishing.push"
        row = {"type": "forced_movement", "distance_ft": 5, "direction": "away", "applies_to": "target"}
        if row_willing:
            row["willing"] = True
        bundle["action_catalog"].append({
            "source_definition_id": source, "display_name": "Test Push", "owner_id": OWNER,
            "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "ANY_CREATURE",
            "range_ft": 60, "costs": [], "parameters": {"typed": {
                "effects": [row], "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}})
        bundle["actor_template"]["action_ids"].append(source)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = setup(tmp_path, bundle_transform=install, named=True)
    activate(combat, table, mid)
    before = reload(tmp_path, mid).state.actors[FOE].position
    prompts = settle(table, mid, candidate(combat, mid, "Test Push", target=FOE).candidate_id,
                     choices={"choice:willing.consent": answer} if answer else {})
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert bool(consent) == (not row_willing)
    if consent:
        assert consent[0]["context"]["reactor_id"] == FOE
        assert all(name in str(consent[0]) for name in ("Vanishing Technique", "Test Push", "Mara"))
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].position != before
    assert bool(held(after.state.actors[OWNER], "invisible")) is not revealed
    assert held(after.state.actors[OWNER], "vanishing_state")
