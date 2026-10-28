"""PRIVCONV3F7 temporary probe 2 (delete before commit)."""


def test_probe_axes_denials():
    from test_riders_lane3 import _beauty_arena, H, _act, ME
    from combat.gate2_runtime_models import CandidateKind
    e = _beauty_arena([H.HEWING, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15,
                      extra_spheres=(H.AXES,), foe_at=(5, 6))
    me = H._me(e)
    _act(e, ME, "Mountain-Felling Axe Body")
    src = "action:typed.7e8ea725e8.weapon.fu.axes_body_reach"
    sid = [k for k in e.action_catalog if k.endswith("weapon.fu.axes_body_reach")]
    out = {"ids": sid, "action_ids": [a for a in me.action_ids if "axes_body" in a or "weapon.fu" in a][:10]}
    cands = [c for c in e.legal_candidates() if c.source_definition_id.endswith("axes_body_reach")]
    out["cands"] = len(cands)
    out["in_action_ids"] = [a for a in me.action_ids if "weapon.fu" in a][:5]
    try:
        from combat import action_legality as al
        out["denials"] = repr(getattr(al, "_LAST", None))[:300]
    except Exception as ex:
        out["denials"] = repr(ex)
    gen = e._candidate(CandidateKind.ACTION, me, sid[0], "x", target_ids=(H.FOE,)) if sid else None
    out["gen_built"] = gen is not None
    if sid:
        act = e.action_catalog[sid[0]]
        from combat.ext import any_false
        out["cand_allowed"] = str(any_false("candidate_allowed", e, me, gen, act)) if gen else None
    assert False, repr(out)
