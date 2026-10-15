from tests.mason_native_support import *

def test_native_open_school_acquisition_drives_table_build(catalog_environment,tmp_path):
    from character_builder import CharacterBuilderService
    from non_sphere_authority.service import NonSphereAuthorityService
    from project_store.service import ProjectStore
    db=catalog_environment['db'];parent='tianxia.subpath.qi.mason_cultivator';path='tianxia.path.qi_cultivation'
    project=CharacterBuilderService(db).create_project(working_name='Native Mason source acquisition',
        concept='Open School construction progression',target_cl=18,power_band='standard',source_reference=None,
        creation_mode='detailed',ability_scores={},selections={'path_choice':[path],'subpath_choice':[parent]})
    pid=project['project_id'];authority=NonSphereAuthorityService(db)
    state=authority.get_state(pid)
    selection=next(row for row in state['paths'] if row['path_id']==path)
    assert selection['subpath_or_tradition_id']==parent
    assert selection['attainment']==18
    assert selection['subpath_or_tradition_acquisition_provenance']['recorded'] is True
    store=ProjectStore(db)
    with db.connection() as conn:
        store.project_lock_proof(conn,pid)
        record=store._resolve_locked_record_after_proof(conn,pid,parent,authority_service=authority)
    source=record['compatibility']['factory']['stage2_authority']
    assert source['owning_path_id']==path
    # Source-bound progression is derived from the acquired parent's immutable
    # authority, rather than constructing an ability ownership receipt.
    raw=record
    def all_features(value):
        if isinstance(value,str):return [value] if value.startswith(BASE) and '.component.' not in value else []
        result=[]
        if isinstance(value,dict):
            for k,v in value.items():
                result.extend(all_features(k));result.extend(all_features(v))
        elif isinstance(value,list):
            for v in value:result.extend(all_features(v))
        return result
    acquired=list(dict.fromkeys(all_features(raw)))
    assert set(acquired)==set(FEATURES)
    combat,table,mid,send,commit=fixture(tmp_path,features=acquired)
    commit(at(table,mid,'Raise Barrier: Low Wall',6,8))
    assert len(works(cold(tmp_path,mid)))==1
