"""Focused regressions for Mantra condition, sound and player-facing behavior."""
from types import SimpleNamespace


def test_renewal_discovers_condition_carried_by_named_feature(monkeypatch):
    from combat.ext import end_effect, condition_ownership, rider_choices, mantra_syllable

    poisoned = SimpleNamespace(condition_id='condition:typed.poison_touch', instance_id='poison-1',
                               data={}, source_definition_id='poison-touch')
    actor = SimpleNamespace(conditions={'poison-1': poisoned}, display_name='Cultivator')
    seen = {}
    monkeypatch.setattr(end_effect, 'condition_rule', lambda c, fallback: {'condition':'poisoned'})
    monkeypatch.setattr(end_effect, 'known_source_cl', lambda ctx, c: 18)
    monkeypatch.setattr(condition_ownership, 'remove_instance', lambda *args: seen.setdefault('removed', args[2]))
    monkeypatch.setattr(rider_choices, 'pick', lambda *args, **kwargs: (seen.update(options=args[4]) or ['0']))
    mantra_syllable.cleanse(SimpleNamespace(actor=SimpleNamespace(display_name='Cultivator'), target=actor,
                                            engine=object(), numbers={'cl':18}, source='syllable', intent=None))
    assert seen['options'] == ['0']
    assert seen['removed'] == 'poison-1'


def test_syllable_sound_admission_checks_every_occupied_cell(monkeypatch):
    from combat.ext import mantra_syllable

    cells = [SimpleNamespace(x=1,y=1,z=0), SimpleNamespace(x=2,y=1,z=0)]
    actor = SimpleNamespace(position=cells[0])
    recipient = SimpleNamespace(position=cells[0])
    ctx = SimpleNamespace(engine=object(), actor=actor)
    calls=[]
    monkeypatch.setattr('combat.spatial_areas.actor_positions', lambda engine, subject: cells)

    def boundaries(engine, source, target, *, origin, at=None):
        calls.append(at)
        return [] if at == cells[1] else None

    monkeypatch.setattr('combat.sound_transmission.boundaries', boundaries)
    monkeypatch.setattr('combat.sound_transmission.path_allowed', lambda ctx, rows: True)
    assert mantra_syllable.receives(ctx, recipient, cells[0])
    assert calls == cells


def test_foundation_flame_help_discloses_object_targets():
    from combat.ext.mantra_foundation import foundation_help

    text = foundation_help({'parameters': {'foundation_mantra':'flame'}})
    assert 'creatures or eligible objects' in text
    assert 'damaged target' in text


def test_silence_caster_is_a_selectable_creature_and_can_choose_exemption(monkeypatch):
    from combat.ext import mantra_silence, needle, placed

    caster = SimpleNamespace(entity_id='caster', team_id='blue', active=True, position='cell',
                             display_name='Caster')
    ally = SimpleNamespace(entity_id='ally', team_id='blue', active=True, position='near',
                           display_name='Ally')
    engine = SimpleNamespace(state=SimpleNamespace(actors={'caster':caster,'ally':ally}))
    ctx = SimpleNamespace(engine=engine, actor=caster, numbers={'pb':2}, source='silence',
                          intent=object())
    picked = {}
    placed_row = {}
    monkeypatch.setattr('combat.stealth.sees', lambda engine, source, target: True)
    monkeypatch.setattr(needle, 'checkpoint_id', lambda *args: 'silence-exempt')
    def ask(engine, intent, checkpoint, actor, choice_type, options, **kwargs):
        picked['options'] = options
        picked['prompt'] = kwargs['prompt']
        return ['caster']
    monkeypatch.setattr(needle, 'ask', ask)
    monkeypatch.setattr(placed, 'area', lambda engine, center, shape, size: [])
    monkeypatch.setattr(placed, 'place', lambda *args, **kwargs: placed_row.update(kwargs['placed']))
    mantra_silence.silence(ctx, {})
    assert 'caster' in picked['options']
    assert placed_row['exempt'] == ['caster']
    assert 'including yourself' in picked['prompt']
    assert 'unless you choose to leave yourself unaffected' in picked['prompt']
