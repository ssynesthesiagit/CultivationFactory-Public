"""Consume Fear, Refine Command resolves on Dread Appetite's failed-save path."""
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, FOE, candidate, fixture, reload, settle

DREAD = "TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE"
CONSUME = "TAL_DAEMONIC_CULTIVATION_CONSUME_FEAR_REFINE_COMMAND"
ESSENCE = "resource:named.devoured_essence"
CHOICE = "choice:needle.consume_fear"


def _prepare(bundles):
    add_action(bundles[0], "Start Fear", [
        {"type": "condition", "applies_to": "target", "condition": "frightened",
         "expires_on": "UNTIL_REMOVED"}
    ])
    seal(bundles[0])


def test_failed_dread_appetite_grants_essence_and_only_prior_fear_opens_choice(tmp_path):
    combat, table, mid = fixture(tmp_path, [DREAD, CONSUME], cl=15, owner_dc=30, bundle_transform=_prepare)
    before = reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE]
    settle(table, mid, candidate(combat, mid, "Start Fear", target=FOE).candidate_id)
    prompts = settle(table, mid, candidate(combat, mid,
        "Dread Appetite: Frighten + Consume Fear, Refine Command", target=FOE).candidate_id,
        {CHOICE: "deny_reactions"})
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == before + 1
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in engine.state.actors[FOE].conditions.values())
    save = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["total"] < save.payload["dc"]
