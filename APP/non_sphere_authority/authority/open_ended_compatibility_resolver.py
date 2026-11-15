from __future__ import annotations
from typing import Any, Iterable

STATES={"NATURAL_AFFINITY","WORKABLE","WORKABLE_WITH_FRICTION","STRAINED","INCOMPATIBLE","CORRECTIVE_OPPORTUNITY","TRANSFORMATION_OPPORTUNITY","GM_REVIEW_REQUIRED"}

_ALLOWED_CLASSES={
    ('METHOD','ordinary_operation_tags'):{'METHOD_POSITIVE_CULTIVATION_BEHAVIOR','METHOD_POSITIVE_BREAKTHROUGH_CLAUSE'},
    ('METHOD','affinity_sphere_ids'):{'METHOD_CANONICAL_SPHERE_INTERFACE'},
    ('METHOD','foundation_form_affinity_tags'):{'METHOD_CULTIVATION_FORM'},
    ('METHOD','correction_interface_tags'):{'METHOD_CORRECTION_INTERFACE'},
    ('METHOD','transformation_mode_tags'):{'METHOD_TRANSFORMATION_ROUTE'},
    ('METHOD','imposed_strain_targets'):{'METHOD_DIRECTIONAL_STRAIN'},
    ('FOUNDATION','ordinary_operation_tags'):{'FOUNDATION_POSITIVE_CULTIVATION_BEHAVIOR'},
    ('FOUNDATION','affinity_sphere_ids'):{'FOUNDATION_CANONICAL_SPHERE_INTERFACE'},
    ('FOUNDATION','form_tags'):{'FOUNDATION_CULTIVATION_FORM'},
    ('FOUNDATION','repair_interfaces'):{'FOUNDATION_REPAIR_INTERFACE'},
    ('FOUNDATION','transformation_routes'):{'FOUNDATION_TRANSFORMATION_ROUTE'},
    ('FOUNDATION','directional_identity_tags'):{'FOUNDATION_DIRECTIONAL_IDENTITY'},
}


def _set(obj:dict,key:str)->set[str]:
    return set(obj.get(key,[]) or [])


def _entries(obj:dict,surface:str,tag:str)->list[dict]:
    return list((obj.get('trait_provenance',{}) or {}).get(surface,{}).get(tag,[]) or [])


def _provenance_eligible(obj:dict,role:str,surface:str,tag:str,eligibility:str,polarities:set[str])->bool:
    allowed=_ALLOWED_CLASSES[(role,surface)]
    return any(
        p.get('source_surface_class') in allowed
        and p.get('polarity') in polarities
        and p.get('scoring_eligibility')==eligibility
        for p in _entries(obj,surface,tag)
    )


def _eligible_tag_set(obj:dict,role:str,surface:str,eligibility:str,polarities:set[str])->set[str]:
    return {tag for tag in _set(obj,surface) if _provenance_eligible(obj,role,surface,tag,eligibility,polarities)}


def _eligible_interface_tags(obj:dict,role:str,surface:str,active:set[str],eligibility:str,polarities:set[str])->set[str]:
    out=set()
    for item in obj.get(surface,[]) or []:
        tag=item['tag']
        if active <= set(item.get('applicable_path_ids',[]) or []) and _provenance_eligible(obj,role,surface,tag,eligibility,polarities):
            out.add(tag)
    return out


def _eligible_strain_targets(method:dict,active:set[str])->set[str]:
    out=set()
    for item in method.get('imposed_strain_targets',[]) or []:
        tag=item['target_tag']
        if active <= set(item.get('applicable_path_ids',[]) or []) and _provenance_eligible(method,'METHOD','imposed_strain_targets',tag,'DIRECTIONAL_STRAIN',{'NEGATIVE'}):
            out.add(tag)
    return out


def resolve(method:dict, foundation:dict, active_path_ids:list[str], overrides:dict|None=None)->dict:
    active=set(active_path_ids); granted=_set(method,'granted_path_ids'); supported=_set(foundation,'compatible_path_ids')
    if not active:
        return result('GM_REVIEW_REQUIRED',['No active Path expression supplied.'],method,foundation,active)
    if foundation.get('usable') is False:
        return result('INCOMPATIBLE',['Foundation authority marks this record unusable.'],method,foundation,active)
    if not active <= granted:
        return result('INCOMPATIBLE',['At least one active Path is not granted by the Primary Method. Compatibility cannot grant AP.'],method,foundation,active)
    if not active <= supported:
        return result('INCOMPATIBLE',['At least one active Path expression is not supported by the Foundation.'],method,foundation,active)

    key=f"{method['method_id']}::{foundation['foundation_id']}"
    if overrides and key in overrides:
        o=overrides[key]
        return result(o['result'],['Direct authored named override.',o['reason']],method,foundation,active,override_id=o['override_id'])

    # Only provenance-eligible semantic surfaces may participate in generalized resolution.
    forms=_eligible_tag_set(foundation,'FOUNDATION','form_tags','ORDINARY_COMPATIBILITY',{'POSITIVE'})
    fops=_eligible_tag_set(foundation,'FOUNDATION','ordinary_operation_tags','ORDINARY_COMPATIBILITY',{'POSITIVE'})
    faff=_eligible_tag_set(foundation,'FOUNDATION','affinity_sphere_ids','ORDINARY_COMPATIBILITY',{'POSITIVE'})
    fident=_eligible_tag_set(foundation,'FOUNDATION','directional_identity_tags','DIRECTIONAL_STRAIN_TARGET',{'NEUTRAL','POSITIVE'})

    required_forms=_set(method,'required_foundation_form_tags')
    required_ops=_set(method,'required_foundation_operation_tags')
    missing_forms=required_forms-forms; missing_ops=required_ops-fops
    if missing_forms or missing_ops:
        ev=[]
        if missing_forms: ev.append('missing_required_foundation_forms='+','.join(sorted(missing_forms)))
        if missing_ops: ev.append('missing_required_foundation_operations='+','.join(sorted(missing_ops)))
        return result('INCOMPATIBLE',ev,method,foundation,active)

    forbidden=_set(method,'forbidden_foundation_trait_tags') & (forms|fops|fident)
    if forbidden:
        return result('INCOMPATIBLE',['Explicit forbidden Foundation trait conflict: '+','.join(sorted(forbidden))],method,foundation,active)

    mrepair=_eligible_tag_set(method,'METHOD','correction_interface_tags','CORRECTION_INTERFACE',{'CORRECTIVE'})
    frepair=_eligible_interface_tags(foundation,'FOUNDATION','repair_interfaces',active,'CORRECTION_INTERFACE',{'CORRECTIVE'})
    repair_match=mrepair&frepair
    if repair_match:
        return result('CORRECTIVE_OPPORTUNITY',['matched_repair_interface='+','.join(sorted(repair_match)),'Correction requires the printed repair practice and does not cure automatically.'],method,foundation,active)

    mtrans=_eligible_tag_set(method,'METHOD','transformation_mode_tags','TRANSFORMATION_ROUTE',{'POSITIVE'})
    ftrans=_eligible_interface_tags(foundation,'FOUNDATION','transformation_routes',active,'TRANSFORMATION_ROUTE',{'POSITIVE'})
    trans_match=mtrans&ftrans
    if trans_match:
        return result('TRANSFORMATION_OPPORTUNITY',['matched_transformation_route='+','.join(sorted(trans_match)),'Transformation remains a Foundation Challenge or GM-authored cultivation event.'],method,foundation,active)

    directional=_eligible_strain_targets(method,active)&fident
    mops=_eligible_tag_set(method,'METHOD','ordinary_operation_tags','ORDINARY_COMPATIBILITY',{'POSITIVE'})
    maff=_eligible_tag_set(method,'METHOD','affinity_sphere_ids','ORDINARY_COMPATIBILITY',{'POSITIVE'})
    mforms=_eligible_tag_set(method,'METHOD','foundation_form_affinity_tags','ORDINARY_COMPATIBILITY',{'POSITIVE'})
    shared_ops=mops&fops
    shared_aff=maff&faff
    shared_forms=mforms&forms
    ev=[]
    if shared_ops: ev.append('shared_ordinary_operations='+','.join(sorted(shared_ops)))
    if shared_aff: ev.append('shared_affinities='+','.join(sorted(shared_aff)))
    if shared_forms: ev.append('shared_forms='+','.join(sorted(shared_forms)))
    if directional: ev.append('directional_strain_conflicts='+','.join(sorted(directional)))
    if directional and (shared_ops or shared_aff or shared_forms): return result('STRAINED',ev,method,foundation,active)
    if directional: return result('GM_REVIEW_REQUIRED',ev+['Directional conflict exists, but no positive relationship is established.'],method,foundation,active)
    if len(shared_ops)>=2 and (len(shared_aff)>=2 or bool(shared_forms)): return result('NATURAL_AFFINITY',ev,method,foundation,active)
    if shared_ops and shared_aff: return result('WORKABLE',ev,method,foundation,active)
    if len(shared_aff)>=2 or (shared_ops and shared_forms): return result('WORKABLE_WITH_FRICTION',ev,method,foundation,active)
    if len(shared_aff)==1: return result('GM_REVIEW_REQUIRED',ev+['One shared Sphere is insufficient for a stronger result.'],method,foundation,active)
    if shared_ops: return result('GM_REVIEW_REQUIRED',ev+['One or more ordinary operations without affinity/form corroboration are insufficient.'],method,foundation,active)
    return result('GM_REVIEW_REQUIRED',['Insufficient generalized trait evidence.'],method,foundation,active)


def result(state:str,evidence:list[str],method:dict,foundation:dict,active:set[str],override_id:str|None=None)->dict:
    assert state in STATES
    return {
      'schema':'Tianxia.MethodFoundationCompatibilityResult.v0.6','state':state,
      'method_id':method['method_id'],'foundation_id':foundation['foundation_id'],'active_path_ids':sorted(active),
      'evidence':evidence,'exact_override_id':override_id,
      'grants_path_ap':False,'grants_resource_conversion':False,'grants_sphere_or_talent':False,
      'grants_method':False,'grants_combat_action':False,'activates_dormant_path_expression':False,
      'satisfies_method_acquisition':False,
    }
