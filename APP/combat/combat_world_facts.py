"""Native world clock/readers from the shared Body source owner.

Consumers are body_modes_scene_resources and source observers. These pure
readers use existing sealed clock/fact fields; absence yields no facts. The
world-input transaction itself belongs to its upstream owner's service.
"""
import copy
import json
from fractions import Fraction
from .journey import require
from .canonical import canonical_sha256
from .fact_consent_admission import declare_world,canonical,digest,KEY

KIND='WORLD_FACT_INPUT_V1'
HISTORY='condition:world.fact_history'


def clock(engine):
    saved=next((b['scene_field_clock'] for b in getattr(engine,'typed_bundle_documents',()) if b.get('scene_field_clock')),None)
    mode_clock=next((b['body_modes_scene_resources'] for b in getattr(engine,'typed_bundle_documents',()) if 'clock_num' in b.get('body_modes_scene_resources',{})),{})
    base=Fraction(saved['num'],saved['den']) if saved else Fraction(mode_clock.get('clock_num',0),mode_clock.get('clock_den',1))
    slots=max(1,len(engine.state.initiative_order))
    return base+Fraction((max(0,engine.state.round_number-1)*slots+engine.state.current_slot_index)*6,slots)


def records(engine):
    found={}
    for bundle in getattr(engine,'typed_bundle_documents',()):
        for row in bundle.get('scene_field_facts',()):
            plain={k:v for k,v in row.items() if k not in ('remaining_num','remaining_den')}
            require(plain['receipt_id']==digest({k:v for k,v in plain.items() if k!='receipt_id'}),'A sealed world record failed its commitment.')
            found[plain['receipt_id']]=plain
    for actor in engine.state.actors.values():
        for condition in actor.conditions.values():
            if condition.condition_id!=HISTORY:
                continue
            for row in json.loads(condition.data['records']):
                require(row['receipt_id']==digest({k:v for k,v in row.items() if k!='receipt_id'}),'A world input failed its replay commitment.')
                found[row['receipt_id']]=row
    return sorted(found.values(),key=lambda r:r['sequence'])
