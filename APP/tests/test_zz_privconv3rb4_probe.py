"""PRIVCONV3F7 temporary probe 4 (delete before commit)."""


def test_probe_hands():
    from test_riders_lane3 import _beauty_arena, H, _act, ME
    from combat.ext import hand_occupancy as ho
    from combat.ext.weapon_hits import available_weapons, weapon_identity
    from types import SimpleNamespace
    e = _beauty_arena([H.HEWING, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15,
                      extra_spheres=(H.AXES,), foe_at=(5, 6))
    me = H._me(e)
    _act(e, ME, "Mountain-Felling Axe Body")
    sid = "action:typed.7e8ea725e8.weapon.fu.axes_body_reach"
    base_id = "action:typed.7e8ea725e8.weapon.fu"
    act = e.action_catalog[sid]
    base = e.action_catalog[base_id]
    out = {}
    out["ident_var"] = weapon_identity(SimpleNamespace(engine=e, action=act, typed=(act.parameters or {}).get("typed") or {}))
    out["req_var"] = ho.weapon_requirement(e, act)
    out["req_base"] = ho.weapon_requirement(e, base)
    out["avail"] = sorted(available_weapons(e, me))
    out["ready"] = sorted(ho.weapon_grips(e, me))
    out["allowed_var"] = ho.weapon_allowed(e, me, act)
    out["allowed_base"] = ho.weapon_allowed(e, me, base)
    out["typed_keys_var"] = sorted(((act.parameters or {}).get("typed") or {}).keys())[:30]
    out["pair_var"] = ho.pair_attack(act)
    out["grip_var"] = (act.parameters or {}).get("equipment_grip")
    out["basekeys"] = sorted((base.parameters or {}).keys())[:20]
    assert False, repr(out)
