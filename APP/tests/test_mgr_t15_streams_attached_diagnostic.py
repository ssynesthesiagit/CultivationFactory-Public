"""Retain the precise failing frame in the compact public-CI receipt."""
import pytest

from tests.test_hunt27_water import test_returning_streams_move_preserves_attached_effects_reload as attached_case


@pytest.mark.parametrize('mixed', [False, True])
def test_native_attached_preservation_failure_location(tmp_path, mixed):
    try:
        attached_case(tmp_path, True, mixed)
    except AssertionError as error:
        frame = error.__traceback__
        while frame.tb_next:
            frame = frame.tb_next
        raise AssertionError(f'attached preservation mixed={mixed}: '
                             f'{frame.tb_frame.f_code.co_filename}:{frame.tb_lineno}: {error}') from error
