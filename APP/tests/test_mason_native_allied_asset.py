"""Cross-source allied Asset repair through actual native creation and rays."""
from tests.mason_native_support import *


def test_master_builder_repairs_another_native_sources_allied_asset(tmp_path):
    hearth='tianxia.subpath.qi.hearthfire_cultivator.feature.kindled_hearth'
    combat,table,mid,send,commit=fixture(tmp_path,damage=20,second_features=[hearth])
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',4,5))
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==s.SECOND:break
        commit(table.state(mid)['menu']['end_turn'])
    # Service CELL actions expose a square picker, then bind its persisted
    # placement answer; the menu root deliberately has no destination.
    commit((s.candidate(table,mid,'Kindled Hearth'),(6,5)))
    engine=cold(tmp_path,mid);asset=next(o for o in engine.state.objects.values() if o.object_kind=='cultivation_asset')
    assert asset.owner_id==s.SECOND and asset.component['source_cl']==17
    next_owner(table,mid,commit)
    # The first hearth is behind the Low Wall from this ground-level object
    # attack. Preserve that real ray boundary, then have its actual owner
    # replace it on the near side before the positive repair scenario.
    assert not any(asset.object_id in o.get('target_ids',[]) for g in table.state(mid)['menu']['actions']
                   if 'Damage a structure' in g['label'] for o in g['options'])
    old=asset.object_id
    for _ in range(6):
        if table.state(mid)['menu']['actor_id']==s.SECOND:break
        commit(table.state(mid)['menu']['end_turn'])
    commit((s.candidate(table,mid,'Kindled Hearth'),(3,5)))
    engine=cold(tmp_path,mid)
    assert engine.state.objects[old].destroyed
    asset=next(o for o in engine.state.objects.values() if o.object_kind=='cultivation_asset' and not o.destroyed)
    assert asset.owner_id==s.SECOND and asset.component['source_cl']==17
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',asset.object_id),decline=('choice:needle.mason_intervention',))
    damaged=cold(tmp_path,mid).state.objects[asset.object_id]
    assert damaged.current_hp==31
    next_owner(table,mid,commit)
    after=cold(tmp_path,mid).state.objects[asset.object_id]
    assert 31<after.current_hp<=51
    assert after.owner_id==s.SECOND and after.component['created_by']==asset.component['created_by']

