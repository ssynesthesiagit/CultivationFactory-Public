"""Heaven-Devouring Maw review F3R fix round regressions.

1. Healing Melody CL6 construction gate: the printed heading in rules_text.json
   is the source; the reviewed authority row must carry min_cl 6 (it was null).
2. Regurgitate Calamity: the Body Refining path_passive role row is passive
   metadata only; the single maw_regurgitate action effect is the only action
   effect, so the two rows cannot double-apply.
3. devouring_maw public helper boundary: the family profile helper is public
   (no private helper called across the module boundary).
"""
import json

from combat.ext import devouring_maw
from combat.ext import effects as registered_effects
from tests.h1_support import ROOT

HM = 'tianxia.subpath.qi.sound_cultivator.feature.healing_melody'
REG = 'tianxia.subpath.body.heaven_devouring_maw_body.feature.regurgitate_calamity'


def _mechanic(path, key):
    data = json.loads((ROOT / path).read_text())
    return data['mechanics'][key]


def test_healing_melody_cl6_gate_is_printed_source_backed():
    rules = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    assert rules[HM].startswith('### CL6 — Healing Melody')
    row = _mechanic('authority/typed_mechanics/reviewed_final.d/zz_a2_qi_subpaths_5.json', HM)
    assert row['min_cl'] == 6


def test_regurgitate_path_row_is_passive_and_action_effect_is_single():
    row = _mechanic('authority/typed_mechanics/reviewed_final.d/riders_c7.json', REG)
    types = [effect['type'] for effect in row['effects']]
    assert types == ['path_passive', 'maw_regurgitate']
    assert sum(1 for effect in row['effects'] if effect['type'] == 'maw_regurgitate') == 1
    assert 'maw_regurgitate' in registered_effects()


def test_family_profile_helper_is_public_boundary():
    assert callable(devouring_maw.raw_roles)
    assert not hasattr(devouring_maw, '_raw_roles')
