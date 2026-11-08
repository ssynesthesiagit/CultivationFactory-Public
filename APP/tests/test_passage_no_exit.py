"""SOL116: occupied starts must not strand accepted AI movement or prompt probes."""
from types import SimpleNamespace
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from combat.diagnostics import CombatGate1Error, error, RecoveryDisposition
from combat.gate5_service import CombatService, CombatServiceError
from combat.creature_passage import finish
from combat.gate2_runtime_models import Position, ActionIntent
from tests import lock8_support as S


def test_inactive_mover_needs_no_exit_when_start_and_stop_are_occupied():
    e = S.fight(S.bundle('SAND_BASE_SCOURING_HAND'), foe_at=(4, 6),
                ally=S.bundle('SAND_BASE_SCOURING_HAND', actor_id=S.ALLY), ally_at=(3, 8))
    mover = e.state.actors[S.ME]
    start = mover.position
    e.state.actors[S.ALLY].position = start
    mover.position = e.state.actors[S.FOE].position
    mover.active = False
    traversed = [start, mover.position]
    occupied = e._occupied_volumes_except(mover.entity_id)
    assert all(not e.grid.volume_legal(p, footprint=e._footprint(mover), occupied_cells=occupied)
               for p in traversed)
    intent = ActionIntent(intent_id='no-exit', decision_id='test', candidate_id='test',
                          state_version=e.state.state_version, actor_id=mover.entity_id)
    before = len(e.events)
    finish(e, mover, traversed, intent)
    assert not mover.active and mover.position == Position(x=4, y=6)
    assert traversed == [start, mover.position] and len(e.events) == before


@pytest.mark.parametrize('phase,recovery,handled', [
    ('INTENT_VALIDATION', RecoveryDisposition.RETRY, True),
    ('INTENT_VALIDATION', RecoveryDisposition.STOP, False),
    ('REPLAY', RecoveryDisposition.RETRY, False),
])
def test_ai_prompt_probe_handles_only_retryable_intent_refusals(phase, recovery, handled):
    refused = error('GATE2_PASSAGE_NO_EXIT', 'No free space remains; choose another move.',
                    phase=phase, subsystem='GATE2_ENGINE', recommended_action='Choose another move.',
                    recovery=recovery)
    class Probe:
        provider = None
        def set_reaction_provider(self, provider):
            self.provider = provider
        def execute_intent(self, intent):
            raise refused
    probe = Probe()
    service = CombatService.__new__(CombatService)
    service.source_root = None
    service._clone_engine = lambda *args: probe
    session = SimpleNamespace(engine=object())
    choice = SimpleNamespace(intent=object())
    if handled:
        assert service._ask_during_ai_step(session, choice, {}) is None
    else:
        with pytest.raises(CombatGate1Error) as caught:
            service._ask_during_ai_step(session, choice, {})
        assert caught.value is refused
    assert probe.provider is None


def test_h104_04_completes_past_step_44(tmp_path):
    """Use retained owner inputs explicitly; never copy them into the repository."""
    retained = os.environ.get('SOL116_HUNT104_DIR')
    if not retained:
        pytest.skip('Set SOL116_HUNT104_DIR to the retained hunt104 evidence directory.')
    reproduction = Path(retained) / 'cmp_crash.py'
    app = Path(__file__).resolve().parents[1]
    source = reproduction.read_text()
    source = source.replace('tt104.OUT = Path("/var/tmp/auto-audit/hunt104")',
                            'tt104.OUT = Path(' + repr(str(tmp_path)) + ')')
    wrapper = ('import sys\nfrom pathlib import Path\n'
               'sys.argv = ' + repr([str(reproduction), str(app), 'sol116']) + '\n'
               'sys.path.insert(0, ' + repr(str(Path(retained))) + ')\n' + source)
    result = subprocess.run([sys.executable, '-c', wrapper], cwd=app, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
    assert result.returncode == 0, result.stdout
    terminal = re.search(r'fight TERMINATED at step (\d+)', result.stdout)
    assert terminal and int(terminal[1]) > 44, result.stdout
    assert 'NO CRASH.' in result.stdout and 'replay=PASS' in result.stdout, result.stdout


def test_real_ai_execution_refusal_is_readable_and_retryable(tmp_path):
    from combat.gate3_reducer import canonical_state_sha256
    from tests.h1_support import ROOT
    service = CombatService(ROOT, tmp_path)
    original = service.persistence.create_match(match_seed='SOL116-REFUSAL')
    actor_id = original.engine.state.current_actor_id
    service.set_controller_mode(original.match_id, actor_id=actor_id, controller_mode='LOCAL_AUTO')
    before = canonical_state_sha256(original.engine.state)
    class RefusingSession:
        def __getattr__(self, name):
            return getattr(original, name)
        def execute_controller_choice(self, *args, **kwargs):
            raise error('GATE2_PASSAGE_NO_EXIT', 'No free space remains along this movement; choose a different move.',
                        phase='INTENT_VALIDATION', subsystem='GATE2_ENGINE',
                        recommended_action='Choose another move.', recovery=RecoveryDisposition.RETRY)
    with pytest.raises(CombatServiceError) as caught:
        service.local_step(original.match_id, session=RefusingSession())
    assert caught.value.status_code == 422
    assert caught.value.diagnostic.code == 'COMBAT_AI_INTENT_INVALID'
    assert caught.value.diagnostic.retry_safe
    assert original.engine.state.actors[actor_id].display_name in str(caught.value)
    assert 'No free space remains' in str(caught.value)
    assert canonical_state_sha256(service._load_session(original.match_id).engine.state) == before
