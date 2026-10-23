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
            # Awareness is admitted below, including an owned declaration for
            # an unseen attacker; a sight-only prefilter would bypass that gate.
            row['requires_sight']=False
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
    if presentation and presentation[-1]['value']=='cannot_present':return False
    if known:return None
    context=SimpleNamespace(engine=engine,intent=intent,source='SHIELD_BASE_ACTIVE_DEFENSE',
        action=SimpleNamespace(display_name='Active Defense'))
    attack=engine.action_catalog.get(spec.get('source_definition_id'))
    attack_name=attack.display_name if attack else 'an attack'
    receipt=admit_choice(context,reactor,'SHIELD_BASE_ACTIVE_DEFENSE','shield_readiness',
        str(spec.get('attack_roll_id') or engine.state.event_sequence),['ready','unaware','cannot_present'],
        labels={'ready':'I am aware of this attacker and can present my Shield toward this attack',
                'unaware':'I am unaware of the attacker','cannot_present':'I cannot present my Shield toward this attack'},
        prompt=(f'Active Defense: {attacker.display_name} uses {attack_name} against {reactor.display_name}. '
                'Are you aware of this attacker and able to present your Shield toward this attack? '
                'Record your actual circumstances, or decline; this declaration spends no Reaction or Martial Focus.'),
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
        expires_on='UNTIL_REMOVED',automatic_options=[],
        condition_labels={'can_present':'Shield presentation: can present your Shield toward an incoming attack; remains until you change this declaration',
                          'cannot_present':'Shield presentation: cannot present your Shield toward an incoming attack; remains until you change this declaration'})
