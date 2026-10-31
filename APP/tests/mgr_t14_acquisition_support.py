"""Shared published sphere-component acquisition for the native T14 matrices.

This calls the production CAT3 receipt producer before native compilation and
portable-sheet persistence. It never adds runtime passives, hits or event flags.
Learned talents and unrelated acquisition records remain unchanged.
"""
from copy import deepcopy
from functools import lru_cache
import json

from canonical_catalog.service import CanonicalCatalogAuthorityService
from sphere_component_authority import attach_sphere_automatic_component_receipt
from tests.h1_support import ROOT


@lru_cache(maxsize=None)
def base_ids_for(sphere_id):
    mechanics = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    return {key for key, row in mechanics.items()
        if row.get('sphere_id') == sphere_id and row.get('kind') == 'base_ability'}


def acquire_sphere(doc, actor_id, sphere_id):
    fields = doc.setdefault('spheres_and_talents', {})
    ledger = {key: deepcopy(fields[key]) for key in
        ('automatic_sphere_component_receipts', 'automatic_sphere_components') if key in fields}
    packet = attach_sphere_automatic_component_receipt(ledger,
        CanonicalCatalogAuthorityService(ROOT).get_sphere(sphere_id), {
            'event_id': 'native-t14:' + sphere_id + ':' + actor_id,
            'legal_channel': 'sphere_acquisition',
            'advancement': {'target_cl': int(doc['identity']['cultivation_level'])}})
    base_ids = base_ids_for(sphere_id) | set(packet['component_ids'])
    fields['sphere_record_ids'] = list(dict.fromkeys([*(fields.get('sphere_record_ids') or []), sphere_id]))
    fields['learned_talent_record_ids'] = [key for key in fields.get('learned_talent_record_ids') or [] if key not in base_ids]
    fields['automatic_sphere_component_record_ids'] = list(dict.fromkeys([
        *(key for key in fields.get('automatic_sphere_component_record_ids') or [] if key not in base_ids),
        *packet['component_ids']]))
    fields.update(ledger)


def acquire_owner(sphere_id, owner):
    def edit(doc, actor_id):
        if actor_id == owner:
            acquire_sphere(doc, actor_id, sphere_id)
    return edit


def acquire_declared(sphere_id):
    def edit(doc, actor_id):
        if sphere_id in (doc.get('spheres_and_talents') or {}).get('sphere_record_ids', ()):
            acquire_sphere(doc, actor_id, sphere_id)
    return edit
