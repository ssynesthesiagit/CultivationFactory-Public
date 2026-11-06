"""Heaven-Devouring Maw F8 fix round: the five rows carry no stale GM riders.

The F6 review's blocking finding: the branch log said the remaining producer and lifecycle
clauses were "identified but not implemented". Three of the five printed records still carried
top-level GM riders for clauses the Maw plug-in already automates:

* Feast upon Protection: suppressing a temporary ward/barrier (combat/ext/devouring_maw.py
  ``_protections`` reads ward/barrier/damage_reduction condition kinds and resistance modifiers).
* Swallow the Technique: no persistent zone as a whole, no permanent artifact effect, no
  technique explicitly barring consumption (row_allowed + activation_settlement + the typed
  ``unconsumable`` declaration).
* Devour Heaven and Earth: Feast treats Immunity as Resistance on a failed save
  (``immunity_as_resistance`` / ``condition:typed.maw_immunity_as_resistance``).

A combat-automatable clause left as a GM rider is a blocking finding (owner 2026-10-20), so the
rows must type as FULL and carry no riders. This test reads the reviewed source row and the
generated authority the compiler pins.
"""
import json

from tests.h1_support import ROOT

FAMILY = 'tianxia.subpath.body.heaven_devouring_maw_body.feature.'
ROWS = ('swallow_hostile_power', 'regurgitate_calamity', 'swallow_the_technique',
        'feast_upon_protection', 'devour_heaven_and_earth')


def _reviewed():
    data = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/riders_c7.json').read_text())
    return {name: data['mechanics'][FAMILY + name] for name in ROWS}


def _generated():
    data = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    return {name: data['mechanics'][FAMILY + name] for name in ROWS}


def test_five_maw_rows_have_no_gm_riders():
    for name, row in _reviewed().items():
        assert row['riders'] == [], (name, row['riders'])


def test_five_maw_rows_compile_as_fully_typed():
    for name, row in _generated().items():
        assert row['riders'] == [], (name, row['riders'])
        assert row['coverage'] == 'FULL', (name, row['coverage'])
