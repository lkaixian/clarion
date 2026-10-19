import 'dart:convert';

import 'package:cryptography/cryptography.dart';

/// Opens the AES-256-GCM blob a staff member wrote onto an NFC tag
/// (`backend/app/tag_crypto.py` is the sealing side and the wire-format
/// reference):
///
///     C1.<key_id>.<base64url(nonce(12) || ciphertext || tag(16))>
///
/// The AAD is `C1|<key_id>|<UID>`, so a blob copied onto a different tag
/// fails to open. Keys are the ones cached from `GET /emergency/tag-keys`
/// at staff login -- there is deliberately no key in the app binary.
/// What `GET /emergency/tag-keys` hands a device: the data keys, plus what it
/// needs to refuse a revoked card with no network, and how long it may rely on
/// any of it without a refresh.
class TagKeySet {
  const TagKeySet({
    required this.keys,
    required this.revocationKey,
    required this.revokedCardIds,
    required this.maxAgeHours,
    this.validUntil,
  });

  final Map<String, String> keys;
  final String? revocationKey; // base64
  final Set<String> revokedCardIds;
  final int maxAgeHours;

  /// Hard stop (UTC) for a time-boxed account, e.g. a community responder:
  /// nothing cached is used after this, whatever [maxAgeHours] says. Null for
  /// accounts that don't expire.
  final DateTime? validUntil;

  static const defaultMaxAgeHours = 24;

  factory TagKeySet.fromJson(Map<String, dynamic> json) {
    final hours = json['key_max_age_hours'];
    return TagKeySet(
      keys: (json['keys'] as Map<String, dynamic>).cast<String, String>(),
      revocationKey: json['revocation_key'] as String?,
      revokedCardIds: ((json['revoked_card_ids'] as List?) ?? const []).cast<String>().toSet(),
      maxAgeHours: hours is int && hours > 0 ? hours : defaultMaxAgeHours,
      validUntil: DateTime.tryParse((json['valid_until'] as String?) ?? '')?.toUtc(),
    );
  }
}

class TagCrypto {
  static const _prefix = 'C1';

  /// The id the server lists for a revoked card (`tag_crypto.revocation_id`
  /// in the backend): the first 32 hex chars of HMAC-SHA256(key, `rev|UID`).
  /// [uid] is the canonical form NfcService returns (uppercase hex, no separators).
  static Future<String> revocationId(String uid, String revocationKeyB64) async {
    final mac = await Hmac.sha256().calculateMac(
      utf8.encode('rev|$uid'),
      secretKey: SecretKey(base64.decode(revocationKeyB64)),
    );
    return mac.bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join().substring(0, 32);
  }
  static const _nonceLen = 12;
  static const _macLen = 16;

  static bool looksSealed(String text) => text.startsWith('$_prefix.');

  /// Strict shape check for text about to be WRITTEN to a tag: the whole
  /// string must be `C1.<key_id>.<base64url>`, not merely start with `C1.`.
  static final _blobShape = RegExp(r'^C1\.\d+\.[A-Za-z0-9_-]+$');
  static bool isWellFormedBlob(String text) => _blobShape.hasMatch(text);

  /// The key id named in a sealed blob, or null if it isn't one.
  static int? keyIdOf(String blob) {
    final parts = blob.split('.');
    if (parts.length != 3 || parts[0] != _prefix) return null;
    return int.tryParse(parts[1]);
  }

  /// Plaintext, or `null` when the blob is malformed, tampered, bound to a
  /// different tag, or its key isn't cached on this device.
  static Future<String?> open(
    String blob,
    String uidCanonical,
    Map<String, String> keysBase64,
  ) async {
    final kid = keyIdOf(blob);
    if (kid == null) return null;
    final keyB64 = keysBase64['$kid'];
    if (keyB64 == null) return null;
    try {
      final raw = base64Url.decode(base64Url.normalize(blob.split('.')[2]));
      if (raw.length < _nonceLen + _macLen) return null;
      final box = SecretBox(
        raw.sublist(_nonceLen, raw.length - _macLen),
        nonce: raw.sublist(0, _nonceLen),
        mac: Mac(raw.sublist(raw.length - _macLen)),
      );
      final clear = await AesGcm.with256bits().decrypt(
        box,
        secretKey: SecretKey(base64.decode(keyB64)),
        aad: utf8.encode('$_prefix|$kid|$uidCanonical'),
      );
      return utf8.decode(clear);
    } catch (_) {
      return null; // one opaque failure mode, same as the server side
    }
  }
}
