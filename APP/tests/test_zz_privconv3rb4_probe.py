"""PRIVCONV3F7 temporary probe 3 (delete before commit)."""


def test_probe_veto_source():
    from test_riders_lane3 import _beauty_arena, H, _act, ME
    from combat.gate2_runtime_models import CandidateKind
    from combat import ext
    e = _beauty_arena([H.HEWING, "TAL_AXES_MOUNTAIN_FELLING_AXE_BODY"], cl=15,
                      extra_spheres=(H.AXES,), foe_at=(5, 6))
    me = H._me(e)
    _act(e, ME, "Mountain-Felling Axe Body")
    sid = "action:typed.7e8ea725e8.weapon.fu.axes_body_reach"
    act = e.action_catalog[sid]
    gen = e._candidate(CandidateKind.ACTION, me, sid, "x", target_ids=(H.FOE,))
    ext._load()
    fns = list(ext._selected("candidate_allowed", (e, me, gen, act)))
    res = []
    for f in fns:
        try:
            r = ext.invoke("candidate_allowed", f, e, me, gen, act)
        except Exception as ex:
            r = "EXC " + repr(ex)[:200]
        if r is False or (isinstance(r, str)):
            res.append((getattr(f, "__module__", "?"), getattr(f, "__qualname__", "?"), str(r)[:200]))
    assert False, repr({"n": len(fns), "vetoes": res, "gen_kind": str(gen.kind), "tgt": str(gen.target_ids)})
