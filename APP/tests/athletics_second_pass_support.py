"""Shared table setup for the athletics second-pass and r9 tests."""
from tests.athletics_action_support import add_action
from tests.auto8f1_table_support import OWNER, candidate_id, reload_identical

POOL = 'condition:typed.athletics_momentum'
SOURCE = 'TAL_ATHLETICS_UNWILLING_BOOST'


def seal_actions(bundles):
    for b in bundles:
        who=b['actor_id']
        if who != OWNER:
            b['actor_template']['strength_score']=18
            continue
        b['actor_template']['armor_class']=1
        for name,effects in [
            ('Become incapacitated',[{'type':'condition','condition':'incapacitated','applies_to':'self'}]),
            ('Become frightened',[{'type':'condition','condition':'frightened','applies_to':'self'}]),
            ('Become stunned',[{'type':'condition','condition':'stunned','applies_to':'self'}]),
            ('Become unconscious',[{'type':'condition','condition':'unconscious','applies_to':'self'}]),
            ('Climb check',[{'type':'contest_against','actor_check':{'ability':'STR','skill':'Athletics','hazards':['climb']},
                             'target_check':{'kind':'dc','basis':'save_dc'}}]),
        ]:
            add_action(b,name,effects)
        for category in ('inhalation','suffocation','forced_march_exhaustion','poison','ordinary'):
            for ability in ('con','dex'):
                add_action(b,f'{ability} {category}',[{'type':'save','ability':ability,'dc':12,'applies_to':'self',
                    'save_categories':[category], 'on_fail':[], 'on_success':[]}])


def commit(g,label,chooser=None):
    return g['commit'](candidate_id(g['menu'](),label),chooser)


def finish(g):
    reload_identical(g['combat'],g['match_id'],g['userdata'])


def momentum(g):
    return [c for c in g['reload_owner']().conditions.values() if c.condition_id==POOL]


