"""The native acquisition repair retains the pinned protocol's other rules."""
from copy import deepcopy
import hashlib
import json
import zipfile

import pytest
from app.core import FoundryError
from factory_authoring.command5_profile import current_view_schema
from tests.h1_support import ROOT


def actual_schemas(factory_zip):
    with zipfile.ZipFile(factory_zip) as z:
        name=next(n for n in z.namelist() if n.endswith('/04_SCHEMAS/gm_character_view_model.schema.json'))
        raw=z.read(name)
    model=json.loads((ROOT/'factory_authoring/contracts/Tianxia_C2B3_GM_Character_Model_Profile_R1.schema.json').read_text())
    return json.loads(raw),hashlib.sha256(raw).hexdigest(),model


def test_actual_owner_amendment_retires_only_the_obsolete_view_field(factory_zip):
    pinned,digest,model=actual_schemas(factory_zip)
    original=deepcopy(pinned)
    effective=current_view_schema(pinned,digest,model)
    assert pinned==original
    assert 'composites' in pinned['required'] and 'composites' not in model['required']
    assert effective['required']==[k for k in pinned['required'] if k!='composites']
    assert effective['properties']['composites'] is False
    assert {k:v for k,v in effective['properties'].items() if k!='composites'}=={
        k:v for k,v in pinned['properties'].items() if k!='composites'}
    assert {k:v for k,v in effective.items() if k not in {'required','properties'}}=={
        k:v for k,v in pinned.items() if k not in {'required','properties'}}


def test_view_schema_without_an_owner_amendment_remains_the_exact_pinned_contract(factory_zip):
    pinned,digest,model=actual_schemas(factory_zip)
    model.pop('x-tianxia-view-schema-amendment')
    assert current_view_schema(pinned,digest,model) is pinned


def test_view_schema_amendment_cannot_silently_apply_to_another_source_version(factory_zip):
    pinned,digest,model=actual_schemas(factory_zip)
    with pytest.raises(FoundryError) as error:
        current_view_schema(pinned,'0'*64,model)
    assert error.value.code=='GM_VIEW_SCHEMA_AMENDMENT_INVALID'
    model['x-tianxia-view-schema-amendment']['retired_properties']=['missing_source_property']
    with pytest.raises(FoundryError) as error:
        current_view_schema(pinned,digest,model)
    assert error.value.code=='GM_VIEW_SCHEMA_AMENDMENT_INVALID'
