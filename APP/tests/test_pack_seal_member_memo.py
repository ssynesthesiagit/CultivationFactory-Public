"""A remembered membership verification never hides changed bytes."""

import pytest

from app.core import FoundryError
from content_packs.membership import verify_pack_seal
from security.integrity import IntegrityService


def _sealed_pack(conn):
    return conn.execute(
        """SELECT p.pack_id, p.version, p.pack_hash FROM content_packs p
           JOIN content_pack_install_receipts r ON r.pack_id=p.pack_id AND r.version=p.version
           WHERE EXISTS (SELECT 1 FROM content_pack_record_membership m WHERE m.pack_hash=p.pack_hash)
           ORDER BY p.pack_id LIMIT 1"""
    ).fetchone()


def test_tampered_member_is_rejected_after_a_remembered_success(stage1_db):
    integrity = IntegrityService.for_database(stage1_db)
    with stage1_db.connection() as conn:
        pack = _sealed_pack(conn)
        assert pack is not None
        kwargs = dict(pack_id=pack["pack_id"], version=pack["version"], expected_pack_hash=pack["pack_hash"], integrity=integrity)
        first = verify_pack_seal(conn, **kwargs)
        # The second, remembered verification returns the identical seal.
        assert verify_pack_seal(conn, **kwargs) == first
        member = conn.execute(
            "SELECT rowid, record_json FROM content_pack_record_membership WHERE pack_hash=? ORDER BY record_id LIMIT 1",
            (pack["pack_hash"],),
        ).fetchone()
        # Simulate out-of-band tampering: the immutability trigger is lifted
        # only in this scratch copy.
        conn.execute("DROP TRIGGER IF EXISTS trg_hf2_membership_no_update")
        conn.execute(
            "UPDATE content_pack_record_membership SET record_json=? WHERE rowid=?",
            (member["record_json"].replace('"record_id"', '"record_id" ', 1), member["rowid"]),
        )
        with pytest.raises(FoundryError):
            verify_pack_seal(conn, **kwargs)
