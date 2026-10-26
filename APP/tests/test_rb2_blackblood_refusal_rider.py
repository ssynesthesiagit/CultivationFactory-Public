"""Blackblood Refusal's GM rider must not send the GM to resolve the Venom-Dark Marrow PB.

The selected Refined expression (Venom-Dark Marrow) is added to the roll by the
game, so a GM who also applies it would add the same PB twice. Perfected
Self-Owned Impurity has no game path yet, so it stays with the GM.
"""
import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
KEY = 'foundation.true_blackblood_physique_v0_2C.blackblood_refusal'
REVIEWED = APP / 'authority/typed_mechanics/reviewed_final.d/a2_foundations4.json'
MIRROR = APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json'
SENTENCE = re.compile(r'(?<=[.;])\s+')


def _reviewed_rider():
    riders = json.loads(REVIEWED.read_text(encoding='utf-8'))[KEY]['riders']
    assert len(riders) == 1
    return riders[0]


def _gm_resolution_sentences(rider):
    return [s for s in SENTENCE.split(rider) if 'still need to be resolved' in s]


def test_gm_rider_does_not_ask_the_gm_to_resolve_refined_venom_pb():
    rider = _reviewed_rider()
    gm_sentences = _gm_resolution_sentences(rider)
    assert gm_sentences, 'the rider must still hand something to the GM'
    assert not any('Refined' in s for s in gm_sentences), gm_sentences


def test_gm_rider_keeps_perfected_self_owned_impurity_with_the_gm():
    rider = _reviewed_rider()
    assert any('Perfected Self-Owned Impurity' in s for s in _gm_resolution_sentences(rider))


def test_gm_rider_says_the_selected_refined_expression_is_already_on_the_roll():
    assert 'selected Refined Venom-Dark Marrow is already added to the roll' in _reviewed_rider()


def test_built_authority_carries_the_same_refusal_rider():
    mirror = json.loads(MIRROR.read_text(encoding='utf-8'))
    rows = mirror['mechanics'] if isinstance(mirror, dict) and 'mechanics' in mirror else mirror
    row = rows[KEY] if isinstance(rows, dict) else next(r for r in rows if r.get('id') == KEY)
    assert _reviewed_rider() in json.dumps(row, ensure_ascii=False)
