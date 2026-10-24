"""Newly compiled Active Defense rows use the shared after-roll declaration seam."""
from copy import deepcopy
from . import hook


@hook('compile_bundle')
def timing(bundle, info):
    rows=bundle.get('typed_reactions',())
    if not any(r.get('feature_id')=='SHIELD_BASE_ACTIVE_DEFENSE' for r in rows):return None
    bundle=deepcopy(bundle)
    for row in bundle['typed_reactions']:
        if row.get('feature_id')=='SHIELD_BASE_ACTIVE_DEFENSE':
            row['after_attack_roll']=1
            # Awareness is this row's own printed requirement, decided by reaction_admission below (perceives/pinpoints,
            # or the human's declared awareness). The generic sight veto would refuse an attacker the defender can only
            # pinpoint before that admission ever runs, so this row clears it.
            row['requires_sight']=False
            # Active Defense raises AC only against this already-rolled attack.
            for effect in row.get('effects') or ():
                if isinstance(effect, dict) and effect.get('type') == 'ac_bonus':
                    effect['duration'] = 'triggering_attack'
    return bundle


@hook('reaction_admission')
def shield_facts(engine,row,reactor,attacker,intent,spec):
    if row.get('feature_id')!='SHIELD_BASE_ACTIVE_DEFENSE' or not row.get('after_attack_roll'):return None
    from types import SimpleNamespace
    from ..fact_consent_admission import admit_choice, combat_records
    from .. import senses
    # Mechanical sight/locating senses justify only the automatic seat's own
    # known option. Humans retain the actual awareness/presentation declaration.
    known=senses.perceives(engine,reactor,attacker) or senses.pinpoints(engine,reactor,attacker)
    presentation=combat_records(engine,reactor,source='SHIELD_BASE_ACTIVE_DEFENSE',kind='shield_presentation')
    # Newest by committed integer sequence, never by condition order (unpadded keys sort wrongly).
    if presentation and max(presentation,key=lambda r:int(r['sequence']))['value']=='cannot_present':return False
    if known:return None
    context=SimpleNamespace(engine=engine,intent=intent,source='SHIELD_BASE_ACTIVE_DEFENSE',
        action=SimpleNamespace(display_name='Active Defense'))
    attack=str(spec.get('attack_name') or 'the attack')
    receipt=admit_choice(context,reactor,'SHIELD_BASE_ACTIVE_DEFENSE','shield_readiness',
        str(spec.get('attack_roll_id') or engine.state.event_sequence),['ready','unaware','cannot_present'],
        labels={'ready':f'I am aware of {attacker.display_name} and can present my Shield toward {attack}',
                'unaware':f'I am unaware of {attacker.display_name}','cannot_present':f'I cannot present my Shield toward {attack}'},
        prompt=(f'Active Defense for {reactor.display_name} against {attacker.display_name}\'s {attack}: requires awareness of '
                f'{attacker.display_name} and the ability to present {reactor.display_name}\'s Shield. Record your actual circumstances, or decline.'),
        expires_on='START_OF_SELF_NEXT_TURN',automatic_options=['ready'] if known else [])
    return bool(receipt and receipt['value']=='ready')


@hook('compile_actions')
def presentation_input(info):
    if 'SHIELD_BASE_ACTIVE_DEFENSE' not in info['owned_ids']:return None
    from ..gate2_runtime_models import ActionDefinition,EconomyKind
    return [ActionDefinition(source_definition_id='action:typed.'+info['short']+'.shield.presentation',
        display_name='Record Shield presentation circumstances',owner_id=info['actor_id'],economy=EconomyKind.NONE,
        resolution_kind='TYPED',target_kind='SELF',parameters={'setting_only':True,'player_only':True,
            'description':'Record whether your actual circumstances let you present your Shield toward an incoming attack; this does not free, repair or equip a Shield.',
            'typed':{'source':'SHIELD_BASE_ACTIVE_DEFENSE','effects':[{'type':'shield_presentation_input'}],
                     'numbers':{},'duration':{'kind':'instant'},'riders':[]}})]


from . import effect


@effect('shield_presentation_input')
def presentation_input_effect(ctx,eff):
    from ..fact_consent_admission import admit_choice
    admit_choice(ctx,ctx.actor,'SHIELD_BASE_ACTIVE_DEFENSE','shield_presentation','current_circumstances',
        ['can_present','cannot_present'],labels={'can_present':'My actual circumstances allow presenting my Shield',
            'cannot_present':'My actual circumstances prevent presenting my Shield'},
        prompt='Record your actual Shield presentation circumstances. This declaration does not change your body, equipment or restraints.',
        expires_on='UNTIL_REMOVED',automatic_options=[])
