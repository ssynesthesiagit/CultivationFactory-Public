"""PRIVCONV3F7 temporary probe (delete before commit)."""


def test_probe_axes_variant():
    from test_riders_lane3 import _beauty_arena, H, _act, ME
    from combat.attack_reach import maximum, melee
    from combat.ext.axes_body_reach import active
    e = _beauty_arena([H.HEWING, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15,
                      extra_spheres=(H.AXES,), foe_at=(5, 6))
    me = H._me(e)
    foe = e.state.actors[H.FOE]
    _act(e, ME, "Mountain-Felling Axe Body")
    out = {"active": active(me), "conds": sorted(c.condition_id for c in me.conditions.values()),
           "dist": e._effect_distance(me, foe), "dist_actor": e._distance_actor_to_actor(me, foe)}
    rows = []
    for a in e.action_catalog.values():
        if a.owner_id != me.entity_id or "Short Axe" not in a.display_name:
            continue
        typed = (a.parameters or {}).get("typed") or {}
        rows.append({"name": a.display_name, "src": a.source_definition_id, "range_ft": a.range_ft,
                     "reach_ft": a.reach_ft, "target_kind": str(a.target_kind), "res": str(a.resolution_kind),
                     "typed_range": typed.get("range_ft"), "typed_long": typed.get("long_range_ft"),
                     "melee": melee(a), "max": maximum(e, me, a),
                     "in_range": e._target_in_range(me, foe, a),
                     "axes_flag": bool((a.parameters or {}).get("axes_body_reach"))})
    out["rows"] = rows
    out["legal_short_axe"] = sorted(n for n in H._legal(e) if "Short Axe" in n)
    assert False, repr(out)
