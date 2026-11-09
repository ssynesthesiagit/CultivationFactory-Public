"""Native map-owner aperture bounds remain separate from map size."""


def test_aperture_width_does_not_replace_native_map_width(tmp_path):
    from combat.tabletop import TabletopMapStore
    saved=TabletopMapStore(tmp_path).save({'display_name':'Bounded openings','width_squares':8,'height_squares':8,
        'walls':[],'terrain':[],'starts':{'team1':[[1,1]],'team2':[[6,6]]},
        'objects':[{'id':1,'kind':'wall_section','x':4,'y':4,'opening_width_milliinch':1000},
                   {'id':2,'kind':'wall_section','x':9,'y':4}]})
    assert [o['id'] for o in saved['objects']]==[1]
