"""Native board nodes without a browser; explicit invisibility is default-inert."""
from pathlib import Path
import subprocess

def test_invisible_zone_has_no_public_board_shape_or_square_card():
    app=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test','--test-name-pattern=invisible source areas',
                           str(app/'static/tabletop/zones.test.mjs')],cwd=app,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_clinical_observer_information_retains_privacy_and_plain_language():
    app=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--test',str(app/'static/tabletop/observer-information.test.mjs')],
                          cwd=app,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
