"""Historical sealed bundles keep their original Formation menus for AI seats.

A saved fight sealed before construction_contract existed has no learning
record at all. Its original Set Array menu must still reach a human and a
model/AI seat: an unknown learning record is not evidence that the creature
knows no pattern.
"""
from combat.gate4_context import build_decision_context
from tests.worker2_support import ALLY, FOE, OWNER, fixture

SET = 'FORMATIONS_BASE_SET_ARRAY'
KIT = {'starting_kit': {'items': [
    {'item_id': 'tianxia.mortal.gear.chalk', 'quantity': 1, 'name': 'Chalk'}]}}


def historical(tmp_path):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    doc = sheet([SET], cl=5, kit=KIT)
    doc.setdefault('spheres_and_talents', {})['formation_patterns'] = ['locking_gate']
    bundle = compile_character(doc, actor_id=OWNER)
    # An old sealed bundle predates the explicit learning contract.
    assert 'construction_contract' in bundle
    bundle.pop('construction_contract')
    return fixture(tmp_path, [], owner_bundle=bundle, cl=5,
                   positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6},
                              FOE: {'x': 6, 'y': 5}})


def set_actions(engine, rows):
    catalogue = engine.action_catalog
    return [c for c in rows if catalogue.get(c.source_definition_id)
            and catalogue[c.source_definition_id].parameters.get('formation') == 'set']


def test_historical_bundle_keeps_its_original_set_array_menu_for_ai(tmp_path):
    combat, table, mid = historical(tmp_path)
    engine = combat._load_session(mid).engine
    owner_bundles = [b for b in engine.typed_bundle_documents if b.get('actor_id') == OWNER]
    assert owner_bundles
    assert all('construction_contract' not in bundle for bundle in owner_bundles)
    human = set_actions(engine, engine.legal_candidates())
    assert human, 'the historical bundle keeps its original Set Array menu'
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    roots = [c for c in context.legal_candidates if c.metadata.get('placement_picker')]
    assert roots, 'an AI seat receives the Set Array placement root'
    assert {c.source_definition_id for c in roots} == {c.source_definition_id for c in human}
    for root in roots:
        assert not root.metadata.get('placement_ai_unavailable'), (
            'unknown learning must not hide the historical Set Array menu from the AI')
        assert root.metadata.get('placement_evaluation')
