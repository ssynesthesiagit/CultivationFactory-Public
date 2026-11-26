import asyncio
import threading

import pytest

from agent_seats import SeatRunner
from app.api import create_app
from app.core import Settings
from combat import fight_stream, journal_feed
from combat.fight_stream import FightStream
from combat.gate3_storage import Gate3MatchStore, LocalMatchWriterLock
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService, _match_lock
from fastapi.testclient import TestClient
from tools.table_speed_probe import ROOT, fixture


def position(sequence):
    return {'match_id': 'a', 'last_sequence': sequence}


def test_match_isolation_and_payload_snapshot():
    async def run():
        stream = FightStream()
        a, b = stream.subscribe('a'), stream.subscribe('b')
        payload = position(1)
        stream.publish('a', 'events', payload)
        payload['last_sequence'] = 7
        message = await anext(a)
        assert message.payload == position(1)
        assert message.sse().startswith('id: 1\nevent: events\n')
        assert not b.queue
        stream.publish('b', 'seat-status', {'running': False})
        assert (await anext(b)).event_id is None
        a.close()
        b.close()
        assert not stream.subscribers
    asyncio.run(run())


def test_slow_subscriber_is_dropped_without_blocking_healthy_one():
    async def run():
        stream = FightStream(queue_size=2)
        slow, fast = stream.subscribe('a'), stream.subscribe('a')
        for i in range(1, 5):
            stream.publish('a', 'events', position(i))
            assert (await anext(fast)).event_id == i
        assert slow.closed and not slow.queue
        with pytest.raises(StopAsyncIteration):
            await anext(slow)
        fast.close()
    asyncio.run(run())


def test_subscribe_only_receives_future_events_above_served_cursor():
    async def run():
        stream = FightStream()
        stream.publish('a', 'events', position(1))
        sub = stream.subscribe('a', after=2)
        assert not sub.queue  # no replay and no synthetic reconciliation
        for sequence in [1, 2, 3]:
            stream.publish('a', 'events', position(sequence))
        assert len(sub.queue) == 1
        assert (await anext(sub)).event_id == 3
        assert not sub.queue
        # Status changes may share the served journal position.
        stream.publish('a', 'seat-status', {'running': False})
        assert (await anext(sub)).payload == {'running': False}
        sub.close()
    asyncio.run(run())


def test_worker_thread_wakes_async_consumer_and_close_wakes_waiter():
    async def run():
        stream = FightStream()
        sub = stream.subscribe('a')
        waiting = asyncio.create_task(anext(sub))
        await asyncio.sleep(0)
        worker = threading.Thread(target=stream.publish, args=('a', 'events', position(7)))
        worker.start()
        assert (await asyncio.wait_for(waiting, 2)).event_id == 7
        worker.join()
        waiting = asyncio.create_task(anext(sub))
        await asyncio.sleep(0)
        sub.close()
        with pytest.raises(StopAsyncIteration):
            await waiting
    asyncio.run(run())


def end_turn(table, match_id):
    menu = table.state(match_id)['menu']
    assert menu['end_turn'], menu
    return menu['end_turn'], menu['decision_id'], menu['state_version']


@pytest.mark.parametrize('route', ['combat', 'tabletop'])
def test_saved_action_publishes_once_after_writer_reservations(route, tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    app = create_app(Settings.from_env(ROOT, tmp_path))
    table = app.state.agent_seats.table
    app.state.agent_seats.background = False
    match_id = fixture(table.combat, tmp_path, 2, 'FIGHT-STREAM-SAVED')
    candidate, decision, version = end_turn(table, match_id)
    match_dir = table._match_dir(match_id)
    before = journal_feed.last_sequence(match_dir)
    publish = fight_stream.publish

    store = Gate3MatchStore(table.combat.userdata_root, match_id)

    def publish_after_release(mid, kind, payload):
        if kind == 'events':
            assert mid == match_id
            assert not _match_lock(mid)._is_owned()
            with (LocalMatchWriterLock(match_dir / '.tabletop_action.lock', mid),
                  store.writer_lock()):
                assert payload['last_sequence'] == journal_feed.last_sequence(match_dir)
        publish(mid, kind, payload)

    monkeypatch.setattr(fight_stream, 'publish', publish_after_release)

    async def run():
        sub = fight_stream.subscribe(match_id, after=before)
        try:
            if route == 'combat':
                with TestClient(app) as client:
                    token = client.get('/api/session').json()['token']
                    actor = table.combat.decision(match_id)['context']['active_actor_id']
                    response = client.post(f'/api/combat/matches/{match_id}/intent',
                        headers={'x-foundry-token': token},
                        json={'intent': {'candidate_id': candidate, 'decision_id': decision,
                                         'state_version': version, 'actor_id': actor}})
                    assert response.status_code == 200, response.text
            else:
                assert table.act(match_id, candidate, decision, version, before)['status'] == 'COMMITTED'

            assert len(sub.queue) == 1
            message = await anext(sub)
            assert message.kind == 'events'
            assert message.event_id == journal_feed.last_sequence(match_dir) > before
            assert message.payload == {'match_id': match_id, 'last_sequence': message.event_id}
        finally:
            sub.close()

    asyncio.run(run())


def test_seat_pause_publishes_once(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    match_id = fixture(combat, tmp_path, 2, 'FIGHT-STREAM-PAUSE')
    seats = SeatRunner(table, background=False)

    async def run():
        sub = fight_stream.subscribe(match_id)
        try:
            assert seats.set_paused(match_id, True) == seats.status(match_id)
            assert len(sub.queue) == 1
            message = await anext(sub)
            assert message.kind == 'seat-status'
            assert message.event_id is None
            assert message.payload == seats.status(match_id)
        finally:
            sub.close()

    asyncio.run(run())


def test_stream_resume_deduplicates_catch_up_and_closes_on_disconnect(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    monkeypatch.setattr(fight_stream, 'HEARTBEAT_SECONDS', 0.05)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    seats = app.state.agent_seats
    seats.background = False
    table = seats.table
    match_id = fixture(table.combat, tmp_path, 2, 'FIGHT-STREAM-RESUME')
    command = end_turn(table, match_id)
    before = journal_feed.last_sequence(table._match_dir(match_id))
    assert before > 0
    events = table.events
    caught_up = []

    def load_with_race(mid, after, *, engine=None):
        if engine is None:
            assert mid == match_id and after == before  # Last-Event-ID wins over after=0.
            assert fight_stream.has_subscribers(mid)
            # The same durable commit is now in both the subscription and the catch-up.
            assert table.act(mid, *command, before, _receipt=True)['status'] == 'COMMITTED'
            fight_stream.publish(mid, 'menu-ready', {})
            caught_up.append(events(mid, after))
            return caught_up[-1]
        return events(mid, after, engine=engine)

    monkeypatch.setattr(table, 'events', load_with_race)

    async def disconnect_after_heartbeat(scope, receive, send):
        # TestClient buffers the body. Inject the ASGI disconnect after the
        # initial/queued frames and one idle heartbeat have actually been sent.
        disconnect = asyncio.Event()
        request_read = False
        body_finished = False

        async def receive_request():
            nonlocal request_read
            if not request_read:
                request_read = True
                return await receive()
            await disconnect.wait()
            return {'type': 'http.disconnect'}

        async def send_frame(message):
            nonlocal body_finished
            await send(message)
            if message['type'] == 'http.response.body':
                body_finished = not message.get('more_body', False)
                if message.get('body') == b': hb\n\n':
                    disconnect.set()

        await asyncio.wait_for(app(scope, receive_request, send_frame), 45)
        assert disconnect.is_set()
        if not body_finished:  # Rewind TestClient's buffer after the transport closes.
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})

    with TestClient(disconnect_after_heartbeat).stream(
        'GET', f'/api/tabletop/matches/{match_id}/stream?after=0',
        headers={'Last-Event-ID': str(before)},
    ) as response:
        assert response.status_code == 200
        assert response.headers['Content-Type'].startswith('text/event-stream')
        assert response.headers['Cache-Control'] == 'no-cache'
        assert response.headers['X-Accel-Buffering'] == 'no'
        frames = '\n'.join(response.iter_lines()).strip().split('\n\n')

    assert len(caught_up) == 1
    assert caught_up[0] == events(match_id, before)
    assert frames == [
        fight_stream.Message.from_payload('events', {
            'match_id': match_id, 'last_sequence': caught_up[0]['last_sequence'],
        }).sse().strip(),
        fight_stream.Message.from_payload('seat-status', seats.status(match_id)).sse().strip(),
        'event: menu-ready\ndata: {}',
        ': hb',
    ]
    assert not fight_stream.has_subscribers(match_id)
