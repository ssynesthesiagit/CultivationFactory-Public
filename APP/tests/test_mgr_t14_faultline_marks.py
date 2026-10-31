"""Real tempered-body attacks deliver owner-selected mark replacement and replay."""
import pytest

from tests.worker2_support import (FOE, OWNER, candidate, fixture, reload, sealed_native_attack,
                                   settle, turn)
from tests.mgr_t14_acquisition_support import acquire_owner

BASE = "GLASS_BASE_FAULTLINE_MARKS"
KEY = "choice:needle.glass_faultline_replace"


@pytest.mark.parametrize("ask", [True, False])
def test_tempered_attacks_replace_owned_mark_at_pb_limit(tmp_path, ask):
    def prepare(bundles):
        for bundle in bundles[2:]:
            sealed_native_attack(bundle, "Surface attack", range_ft=120,
                                 count=1, sides=2, modifier=0)

    combat, table, mid = fixture(tmp_path, [BASE], owner_pb=2, ask=ask,
                                 extra_foes=2, bundle_transform=prepare, named=True,
                                 sheet_edit=acquire_owner('tianxia.sphere.glass', OWNER))
    settle(table, mid, candidate(combat, mid, "Temper Glass Surface").candidate_id)
    engine = reload(tmp_path, mid)
    foes = [aid for aid in engine.state.initiative_order
            if aid.startswith("actor:factory.worker2-foe")]
    # Visit in cyclic initiative order after the owner, avoiding a second owner
    # turn (and therefore retaining all three attacks inside the mark deadline).
    order = list(engine.state.initiative_order)
    start = order.index(OWNER)
    foes.sort(key=lambda aid: (order.index(aid) - start) % len(order))
    all_prompts = []
    condition_id = "condition:typed.mark.faultline_mark." + OWNER
    for index, foe in enumerate(foes):
        turn(table, mid, foe)
        before = reload(tmp_path, mid)
        previous = [(aid, c) for aid, actor in before.state.actors.items()
                    for c in actor.conditions.values() if c.condition_id == condition_id]
        picks = {}
        if index == 2:
            # Deliberately choose the newest, proving this is not oldest eviction.
            newest = max(previous, key=lambda pair: pair[1].applied_sequence)
            picks[KEY] = newest[1].instance_id
        prompts = settle(table, mid, candidate(combat, mid, "Surface attack", target=OWNER).candidate_id, picks)
        all_prompts.extend(prompts)
        after = reload(tmp_path, mid)
        marks = [(aid, c) for aid, actor in after.state.actors.items()
                 for c in actor.conditions.values() if c.condition_id == condition_id]
        assert len(marks) == min(index + 1, 2)
        assert any(aid == foe for aid, _ in marks)
        if index == 2:
            assert not any(aid == newest[0] for aid, _ in marks)
            choice = next(p for p in prompts if p['context']['reaction_source_id'] == KEY)
            assert len(choice['choice']['options']) == 2
    # Both fixtures use MANUAL control. A standing reaction-plan preference
    # cannot silently answer a mandatory owner choice, even when ask=False.
    assert any(p['context']['reaction_source_id'] == KEY for p in all_prompts)


def test_second_surface_trigger_refreshes_the_owners_existing_mark(tmp_path):
    """A second qualifying trigger on a creature already bearing this owner's mark is offered as a
    refresh (no silent no-op): one mark is kept and its clock restarts, across commit and reload."""
    from combat.typed_executor import mark_condition_id
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    surface = 'choice:needle.glass_surface_mark'
    condition_id = mark_condition_id('Faultline Mark', OWNER)

    def prepare(bundles):
        for bundle in bundles[2:]:
            # Two strikes in one action: each strike at the tempered body is its own qualifying trigger.
            sealed_native_attack(bundle, "Surface attack", range_ft=120, attacks=2, sides=2, modifier=0)

    combat, table, mid = fixture(tmp_path, [BASE], owner_pb=2, bundle_transform=prepare, named=True,
                                 sheet_edit=acquire_owner('tianxia.sphere.glass', OWNER))
    settle(table, mid, candidate(combat, mid, "Temper Glass Surface").candidate_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, "Surface attack", target=OWNER).candidate_id, {surface: 'mark'})
    offers = [p for p in prompts if p['context']['reaction_source_id'] == surface]
    assert 'Place your Faultline Mark' in str(offers[0])
    assert any('Refresh your Faultline Mark' in str(p) for p in offers[1:])
    engine = reload(tmp_path, mid)
    marks = [(aid, c) for aid, actor in engine.state.actors.items()
             for c in actor.conditions.values() if c.condition_id == condition_id]
    assert [aid for aid, _ in marks] == [FOE]
    placements = [e for e in engine.events if e.event_type == 'CONDITION_APPLIED'
                  and e.payload.get('condition_id') == condition_id]
    assert len(placements) >= 2 and placements[-1].sequence > placements[0].sequence
    assert marks[0][1].applied_sequence > placements[0].sequence
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'


def test_decoded_source_pin():
    import hashlib
    import json
    from tests.h1_support import ROOT
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[BASE]
    assert hashlib.sha256(text.encode()).hexdigest() == 'afbd58fbbdef68df4897b493ba0450effa0cf7bc99cc5e6b356b3e638b2d1167'
