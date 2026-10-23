"""Public synthetic tests for explicit spiritual object profile permissions."""
from combat.spiritual_profiles import normalize


def test_explicitly_immune_external_anchor_remains_unaffectable():
    profile = normalize({"external_anchor": 1, "affectable": 0, "known_to": ["actor"]})
    assert profile["external_anchor"] == 1
    assert profile["affectable"] == 0


def test_external_anchor_infers_affectability_when_unspecified():
    profile = normalize({"external_anchor": 1})
    assert profile["affectable"] == 1


def test_world_contact_requires_both_attacker_and_ally_inside_domain(monkeypatch):
    """Only a hostile subject in the Domain triggers Contact Cannot Be Stolen."""
    from types import SimpleNamespace
    from combat.ext import last_inch_palm

    palm = SimpleNamespace(active=True, team_id='allies', entity_id='palm')
    attacker = SimpleNamespace(active=True, team_id='foes', entity_id='attacker')
    defender = SimpleNamespace(active=True, team_id='allies', entity_id='ally')
    engine = SimpleNamespace(state=SimpleNamespace(actors={'palm': palm}),
                              _distance_actor_to_actor=lambda first, second: 0)
    monkeypatch.setattr(last_inch_palm, 'is_subject', lambda engine, owner, target: target is attacker)
    monkeypatch.setattr(last_inch_palm, '_world', lambda owner: object())
    inside = {defender.entity_id}
    monkeypatch.setattr(last_inch_palm, 'in_world', lambda engine, owner, target: target.entity_id in inside)
    monkeypatch.setattr(last_inch_palm.st, 'row', lambda *args: None)
    seen = []
    def protect(engine, owner, source, ally, context, reach):
        seen.append((owner, source, ally))
        return {'mode': 'DISADVANTAGE'}
    monkeypatch.setattr(last_inch_palm, '_contact_not_stolen', protect)

    result = last_inch_palm.nothing_crosses(engine, attacker, defender, object(), {'range_ft': 5})
    assert result is None
    assert not seen

    inside.add(attacker.entity_id)
    result = last_inch_palm.nothing_crosses(engine, attacker, defender, object(), {'range_ft': 5})
    assert result == {'mode': 'DISADVANTAGE'}
    assert seen == [(palm, attacker, defender)]
