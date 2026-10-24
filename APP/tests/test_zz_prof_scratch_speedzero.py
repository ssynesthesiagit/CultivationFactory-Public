"""SCRATCH profiling only (not to be committed)."""
import cProfile, io, pstats, time
import tests.test_mgr_t16_athletics4_review as A
import tests.test_mgr_t16_athletics_3srb2 as B


def _report(pr, label, secs):
    out = io.StringIO()
    out.write(f"== {label}: wall {secs:.1f}s\n")
    st = pstats.Stats(pr, stream=out)
    out.write("---- by cumulative\n")
    st.sort_stats('cumulative').print_stats(25)
    out.write("---- by own time\n")
    st.sort_stats('tottime').print_stats(25)
    return out.getvalue()


def test_prof_offer_enum(tmp_path, monkeypatch):
    pr = cProfile.Profile(); t = time.time()
    pr.enable()
    try:
        A.test_every_zero_movement_horizontal_offer_commits_its_endpoint(tmp_path, monkeypatch)
        err = 'PASSED'
    except BaseException as e:
        err = repr(e)[:500]
    pr.disable()
    assert False, 'PROFILE_OFFER ' + err + '\n' + _report(pr, 'offer', time.time() - t)


def test_prof_swim(tmp_path, monkeypatch):
    pr = cProfile.Profile(); t = time.time()
    pr.enable()
    try:
        B.test_material_swim_keeps_close_quarters_endpoint_and_reload(tmp_path, monkeypatch)
        err = 'PASSED'
    except BaseException as e:
        err = repr(e)[:500]
    pr.disable()
    assert False, 'PROFILE_SWIM ' + err + '\n' + _report(pr, 'swim', time.time() - t)
