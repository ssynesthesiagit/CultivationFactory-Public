"""Review F8R finding 2: attributed attack-mode replies accept an optional owner.

effect and why must be strings; owner may be missing, None, or an actor object
(barrage_second_pass passes actors). Each must collect without ValueError and
keep the reply's why as the receipt reason.
"""
from types import SimpleNamespace

import pytest

from combat import attack_modes, zones
from combat import ext as combat_ext


def _engine():
    return SimpleNamespace(state=SimpleNamespace(actors={}, zones={}), action_catalog={})


@pytest.mark.parametrize('owner,expected_owner', [
    (None, ''),
    ('Mira', 'Mira'),
    (SimpleNamespace(display_name='Oren'), 'Oren'),
    (SimpleNamespace(name='Tove'), 'Tove'),
])
def test_attributed_attack_mode_collects_with_optional_or_actor_owner(monkeypatch, owner, expected_owner):
    reply = {'mode': 'DISADVANTAGE', 'effect': 'Covering Volley', 'why': 'the cover imposes Disadvantage'}
    if owner is not None:
        reply['owner'] = owner
    monkeypatch.setattr(zones, 'attack_modes', lambda *_: ())
    monkeypatch.setattr(combat_ext, 'run_strict', lambda point, *args, **kwargs: [reply] if point == 'attack_geometry_mode' else [])
    reasons = []
    modes = attack_modes.geometry_modes(_engine(), None, None, False, reasons=reasons)
    assert any(m == 'DISADVANTAGE' and not c for m, c in modes)
    assert len(reasons) == 1
    assert reasons[0]['effect'] == 'Covering Volley'
    assert reasons[0]['owner'] == expected_owner
    assert reasons[0]['why'] == 'the cover imposes Disadvantage'


def test_owner_is_not_required_for_typed_contribution():
    mode, cause = attack_modes.typed_contribution({'mode': 'ADVANTAGE', 'effect': 'Lone Lantern', 'why': 'a reason'})
    assert mode == 'ADVANTAGE' and not cause


def test_missing_why_or_effect_still_rejected():
    with pytest.raises(ValueError):
        attack_modes.typed_contribution({'mode': 'ADVANTAGE', 'effect': 'Lone Lantern'})
    with pytest.raises(ValueError):
        attack_modes.typed_contribution({'mode': 'ADVANTAGE', 'why': 'a reason', 'effect': 3})
