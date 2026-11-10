"""A14: attacks on the encrypted NFC tag blob (tag_crypto.py). Pure functions, no DB.

Known limit (documented, xfail): NTAG213/215 have no tamper-proof read counter, so a valid blob copied
byte-for-byte from the SAME tag opens again. Only the offline-read audit chain (and NTAG 424 DNA later) helps.
"""
import base64
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app import tag_crypto

UID, OTHER = "04A1B2C3D4E5F6", "04A1B2C3D4E5F7"
PLAIN = "BT:O+|AL:Penicillin(severe)|ME:Warfarin"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("CLARION_TAG_KEY_SECRET", "test-master-secret")
    monkeypatch.setenv("CLARION_TAG_KEY_ID", "1")
    monkeypatch.delenv("CLARION_TAG_MIN_KEY_ID", raising=False)


def _refused(blob, uid=UID):
    with pytest.raises(ValueError):
        tag_crypto.open_blob(blob, uid)


def test_a14_every_flipped_byte_is_rejected():
    blob = tag_crypto.seal(PLAIN, UID)
    head, body = blob.rsplit(".", 1)
    raw = bytearray(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    for i in range(len(raw)):                      # nonce, ciphertext and GCM tag
        bad = bytearray(raw); bad[i] ^= 0x01
        _refused(head + "." + base64.urlsafe_b64encode(bytes(bad)).decode().rstrip("="))


@pytest.mark.parametrize("junk", ["", ".", "C1", "C1.1", "C1.1.", "C2.1.AAAA", "C1.x.AAAA", "C1.1.!!!!", "A" * 5000])
def test_a14_malformed_blobs_rejected(junk):
    _refused(junk)


def test_a14_truncated_and_extended_rejected():
    blob = tag_crypto.seal(PLAIN, UID)
    _refused(blob[:-4]); _refused(blob + "AAAA")


def test_a14_blob_is_bound_to_its_tag_uid():
    blob = tag_crypto.seal(PLAIN, UID)
    _refused(blob, OTHER); _refused(blob, UID.lower())


def test_a14_key_id_in_header_is_authenticated():
    blob = tag_crypto.seal(PLAIN, UID, key_id=1)
    _refused(blob.replace("C1.1.", "C1.2.", 1))      # claim a different key id
    _refused(blob.replace("C1.1.", "C1.0.", 1))


def test_a14_wrong_master_secret_cannot_open(monkeypatch):
    blob = tag_crypto.seal(PLAIN, UID)
    monkeypatch.setenv("CLARION_TAG_KEY_SECRET", "attacker-guess")
    _refused(blob)


def test_a14_retired_key_is_not_handed_to_devices(monkeypatch):
    old = tag_crypto.seal(PLAIN, UID)                # sealed under key 1
    monkeypatch.setenv("CLARION_TAG_KEY_ID", "2")
    monkeypatch.setenv("CLARION_TAG_MIN_KEY_ID", "2")
    keys = tag_crypto.active_keys()
    assert set(keys) == {"2"}, "devices must not receive retired keys"
    raw = tag_crypto._b64d(old.split(".", 2)[2])      # a device holding only active keys cannot open it
    with pytest.raises(Exception):
        AESGCM(base64.b64decode(keys["2"])).decrypt(raw[:12], raw[12:], tag_crypto._aad(1, UID))


def test_a14_nonces_never_repeat():
    nonces = {tag_crypto._b64d(tag_crypto.seal(PLAIN, UID).split(".", 2)[2])[:12] for _ in range(2000)}
    assert len(nonces) == 2000
    assert tag_crypto.seal(PLAIN, UID) != tag_crypto.seal(PLAIN, UID)


def test_a14_revocation_id_is_stable_per_card_and_independent_of_key_rotation(monkeypatch):
    a = tag_crypto.revocation_id(UID)
    assert a == tag_crypto.revocation_id(UID) and a != tag_crypto.revocation_id(OTHER) and UID not in a
    monkeypatch.setenv("CLARION_TAG_KEY_ID", "5")
    assert tag_crypto.revocation_id(UID) == a


@pytest.mark.xfail(strict=False, reason="NTAG213/215 have no tamper-proof read counter: a copied blob replays (needs NTAG 424 DNA)")
def test_a14_replayed_blob_from_same_tag_is_refused():
    blob = tag_crypto.seal(PLAIN, UID)
    tag_crypto.open_blob(blob, UID)
    _refused(blob)
