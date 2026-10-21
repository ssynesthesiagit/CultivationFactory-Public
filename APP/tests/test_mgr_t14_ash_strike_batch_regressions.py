"""Public synthetic regressions for the integration review's Strike contracts."""
import ast
from pathlib import Path

import pytest

from combat.ext import foundation_paid
from tests.test_mgr_t14_ash_strike import setup, strike, packets, STRIKE, POOL
from tests.worker2_support import OWNER, FOE, candidate, reload, settle

CONTEXT = 'choice:needle.foundation_event_context'


def test_shared_payment_helper_names_its_consumers():
    doc = ast.get_docstring(ast.parse(Path(foundation_paid.__file__).read_text()))
    assert "shared" in doc.lower()
    assert "foundations3" in doc
    # Behaviour behind the documented contract: no validated payment, no value.
    assert foundation_paid.paid_value(type('NoPayment', (), {
        'attack_damage_context': None, 'hit_snapshots': {}, 'engine': None})(),
        None, STRIKE, POOL, 3) is None


def test_alignment_metadata_is_inert_without_a_foundation_consumer(tmp_path):
    # Ignite's reviewed 'ash' alignment is sealed data. Without the Strike or
    # Meridian consumer it must publish no receipt, spend nothing and generate
    # nothing, so an ordinary technique owner is untouched.
    combat, table, mid = setup(tmp_path, owned=False)
    settle(table, mid, candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    ignite = next(a for a in engine.action_catalog.values()
                  if (a.parameters.get('typed') or {}).get('source') == 'FIRE_BASE_IGNITE')
    assert 'ash' in ignite.parameters['typed']['foundation_alignment']
    assert not any((e.payload or {}).get('trigger') == 'foundation_hit_settled' for e in engine.events)
    assert not any(e.event_type in ('RESOURCE_SPENT', 'RESOURCE_GAINED') for e in engine.events)


@pytest.mark.parametrize("dtype", ["fire", "necrotic", "poison", "slashing"])
def test_unspecified_scene_facts_do_not_refill_a_paid_strike(tmp_path, dtype):
    combat, table, mid = setup(tmp_path)
    prompts = strike(combat, table, mid, dtype)
    engine = reload(tmp_path, mid)
    assert len(packets(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == POOL
                   for e in engine.events)
    # The helper must decline unknown facts, not select the first ("real") answer.
    assert any(p['context']['reaction_source_id'] == CONTEXT for p in prompts)


def test_real_battlefield_event_can_regenerate_after_not_before_payment(tmp_path):
    combat, table, mid = setup(tmp_path)
    cid = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id
    settle(table, mid, cid, choices={
        'choice:needle.ash_strike': 'slashing',
        CONTEXT: 'real',
        CONTEXT + '.detail': 'battlefield',
    })
    engine = reload(tmp_path, mid)
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.source_definition_id == STRIKE and e.payload.get('resource_id') == POOL]
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
             and e.payload.get('resource_id') == POOL]
    assert len(spends) == len(gains) == len(packets(engine)) == 1
    assert spends[0].sequence < packets(engine)[0].sequence < gains[0].sequence
    assert engine.state.actors[OWNER].resources[POOL] == 1


def test_strike_payment_is_mechanical_not_inferred_from_long_prose():
    import copy
    import json
    from combat.factory_compiler import TYPED_AUTHORITY, compile_character
    from tests.h1_support import sheet
    authority = copy.deepcopy(json.loads(TYPED_AUTHORITY.read_text()))
    row = authority["mechanics"][STRIKE]
    row["modifier"]["precondition"] = "Qualifying hit"
    row["description"] = ["Fixture qualification"]
    bundle = compile_character(sheet([STRIKE, "FIRE_BASE_IGNITE"],
        foundation={"foundation_id": "red_lotus_ash_returning_v0_2B", "stage": "Awakened",
                    "resource": {"name": "Funeral Ash", "resource_id": "tianxia.resource.test",
                                 "maximum": 1, "current": 1}}),
        actor_id=OWNER, typed_authority=authority)
    groups = [g for a in bundle["action_catalog"]
              for g in a.get("parameters", {}).get("typed", {}).get("attack_modifier_loadout", [])
              if g["id"] == STRIKE]
    assert groups
    assert all(o["payments"] == [[[POOL, 1]]] for g in groups for o in g["options"])


def test_fact_admission_hook_contracts_are_in_the_module_docstring():
    from combat import ext
    from combat.ext import foundations3
    doc = ast.get_docstring(ast.parse(Path(ext.__file__).read_text()))
    for name in ("fact_admission_schema", "fact_admission_validate", "fact_admitted",
                 "combat_fact_admission_allowed"):
        assert name + "(session," in doc
        assert ext.subscribers(name)
    # Documented defaults are inert for any source without an owned provider.
    assert foundations3.pulse_combat_fact_allowed(None, 'some.other.source', None, 'kind') is None
    assert foundations3.pulse_fact_schema(None, 'some.other.source', None, 'kind') is None
    assert foundations3.pulse_combat_fact_allowed(
        None, foundations3.GENTLE_PULSE, None, foundations3.PULSE_FACT_KIND) is True


def test_human_variant_is_reachable_through_its_native_toggle(tmp_path):
    combat, table, mid = setup(tmp_path)
    source = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).source_definition_id
    engine = reload(tmp_path, mid)
    variants = {a.source_definition_id for a in engine.action_catalog.values()
                if a.parameters.get('typed', {}).get('variant_of') == source
                and a.parameters.get('typed', {}).get('ash_strike_declared')}
    assert variants
    assert not variants.intersection(c.source_definition_id for c in engine.legal_candidates())
    toggle = next(a for a in engine.action_catalog.values()
                  if (s := a.parameters.get('attack_modifier_setting') or {}).get('family') == source
                  and s.get('modifier') == STRIKE and s.get('field') == 'on')
    settle(table, mid, next(c.candidate_id for c in engine.legal_candidates()
                           if c.source_definition_id == toggle.source_definition_id))
    engine = reload(tmp_path, mid)
    assert variants <= {c.source_definition_id for c in engine.legal_candidates()}
