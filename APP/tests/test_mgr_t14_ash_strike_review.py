"""Review regressions for legacy no-cost variants and settled table consent."""
import pytest

from combat.ext import subscribers
from combat.ext.foundations3 import defer_declared_strike
from tests.test_mgr_t14_ash_strike import setup, strike, packets, STRIKE, POOL
from tests.worker2_support import OWNER, FOE, candidate, reload, settle

HIT_SETTLED = 'foundation_hit_settled'


def _ignite(tmp_path, *, owned, choice):
    """One ordinary Ignite, declined or accepted, in its own cold-reloadable fight."""
    tmp_path.mkdir()
    combat, table, mid = setup(tmp_path, owned=owned)
    if not owned:
        settle(table, mid, candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id)
    else:
        strike(combat, table, mid, choice)
    return reload(tmp_path, mid)


def test_declined_strike_is_an_ordinary_ignite(tmp_path):
    # The behaviour diff from main (MGR-T14-1F7R) showed main applying the old
    # unreviewed Strike automatically: DAMAGE_COMMITTED with
    # display_source_id 'passive:...ash_returning_strike' and no RESOURCE_SPENT.
    # A declined Strike must instead be exactly the same Ignite as an actor who
    # does not own it: same packets, same HP, no spend, one inert receipt.
    control = _ignite(tmp_path / 'control', owned=False, choice=None)
    declined = _ignite(tmp_path / 'declined', owned=True, choice=None)
    hits = lambda engine: [(e.payload['hp_damage'], e.payload['damage_type'])
                           for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']
    assert hits(declined) == hits(control)
    assert declined.state.actors[FOE].current_hp == control.state.actors[FOE].current_hp
    assert not packets(declined)
    assert declined.state.actors[OWNER].resources[POOL] == 1
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == STRIKE
                   for e in declined.events)
    assert [e.event_type for e in declined.events
            if e.event_type not in {x.event_type for x in control.events}] == ['PASSIVE_TRIGGERED']
    receipt = next(e for e in declined.events if (e.payload or {}).get('trigger') == HIT_SETTLED)
    assert receipt.payload['qualifies'] == 1


def test_accepted_strike_lowers_hp_by_exactly_the_printed_total(tmp_path):
    # Same seed and dice as the declined control: the accepted Strike must add
    # one signed packet of PB (2) + Path key modifier (-1) and spend one Ash.
    declined = _ignite(tmp_path / 'declined', owned=True, choice=None)
    accepted = _ignite(tmp_path / 'accepted', owned=True, choice='slashing')
    assert accepted.state.actors[FOE].current_hp == declined.state.actors[FOE].current_hp - 1
    assert len(packets(accepted)) == 1
    assert packets(accepted)[0].payload['hp_damage'] == 1
    assert packets(accepted)[0].payload['damage_type'] == 'SLASHING'
    spends = [e for e in accepted.events if e.event_type == 'RESOURCE_SPENT'
              and e.payload.get('resource_id') == POOL]
    assert len(spends) == 1
    assert accepted.state.actors[OWNER].resources[POOL] == 0


def test_deferred_cost_rewrites_only_the_strike_variant(tmp_path):
    # The reviewer suspected defer_declared_strike lowered every variant's
    # costs. It must only touch a variant that carries this Strike's effect.
    _, _, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    variant = next(a for a in engine.action_catalog.values()
                   if a.parameters.get("typed", {}).get("ash_strike_declared"))
    costs = ((POOL, 1), ('resource:test.other', 2))
    base_typed = variant.parameters['typed']
    # Another technique's optional variant carries no Strike effect: untouched.
    other_typed = {k: v for k, v in base_typed.items()
                   if k not in ('ash_strike_declared', 'effects')}
    other_typed['effects'] = [{'type': 'damage', 'applies_to': 'target', 'flat': 3}]
    other = variant.model_copy(update={'costs': costs,
        'parameters': {**variant.parameters, 'typed': other_typed}})
    assert defer_declared_strike(other, {'owned_ids': [STRIKE]}) is other
    # The Strike's own variant removes exactly its one Ash and keeps the
    # technique's unrelated cost, instead of rewriting every variant's costs.
    strike_typed = {**base_typed, 'effects': [{'type': 'foundations3_ash_strike', 'effects': []}]}
    strike_variant = variant.model_copy(update={'costs': costs,
        'parameters': {**variant.parameters, 'typed': strike_typed}})
    rewritten = defer_declared_strike(strike_variant, {'owned_ids': [STRIKE]})
    assert rewritten.costs == (('resource:test.other', 2),)


def test_paid_value_hook_documents_arguments_and_inert_contract():
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "combat/ext/__init__.py"
    doc = ast.get_docstring(ast.parse(path.read_text()))
    for text in ("foundation_paid_value_bonus(ctx, target, source, signed_value, payment_event)",
                 "signed_value the raw integer base", "Providers are pure",
                 "no subscribers leaves the signed base unchanged"):
        assert text in doc
    # The documented contract must also hold at runtime, not only in prose.
    from combat.ext import foundations3
    from combat.ext.foundation_paid import paid_value
    assert foundations3.heart_ash_strike_value in subscribers('foundation_paid_value_bonus')
    assert foundations3.heart_ash_strike_value(None, None, 'FIRE_BASE_IGNITE', 5, None) is None
    assert paid_value(type('NoPayment', (), {'attack_damage_context': None,
                                             'hit_snapshots': {}, 'engine': None})(),
                      None, STRIKE, POOL, 4) is None


def test_owned_strike_variant_without_recorded_upfront_cost(tmp_path):
    _, _, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    action = next(a for a in engine.action_catalog.values()
                  if a.parameters.get("typed", {}).get("ash_strike_declared"))
    # Legacy optional modifiers did not always record the printed resource cost.
    # Reconstruct that input, retaining an unrelated technique cost verbatim.
    typed = {**action.parameters["typed"], "effects": [
        {"type": "foundations3_ash_strike", "effects": []}]}
    action = action.model_copy(update={"costs": (("resource:test.other", 2),),
        "parameters": {**action.parameters, "typed": typed}})
    result = defer_declared_strike(action, {"owned_ids": [STRIKE]})
    assert result.costs == (("resource:test.other", 2),)
    assert result.parameters["typed"]["ash_strike_declared"] == 1
    assert result.parameters["typed"]["effects"] == []


@pytest.mark.parametrize("choice", [None, "slashing"])
def test_paid_and_declined_hit_survive_table_reload(tmp_path, choice):
    combat, table, mid = setup(tmp_path)
    before = reload(tmp_path, mid)
    hp = before.state.actors[FOE].current_hp
    prompts = strike(combat, table, mid, choice)
    engine = reload(tmp_path, mid)
    assert prompts
    assert engine.state.actors[FOE].current_hp < hp
    assert engine.state.actors[OWNER].resources[POOL] == (1 if choice is None else 0)
    assert len(packets(engine)) == (0 if choice is None else 1)
    if choice:
        assert packets(engine)[0].payload["hp_damage"] == 1
        assert packets(engine)[0].payload["damage_type"] == "SLASHING"
