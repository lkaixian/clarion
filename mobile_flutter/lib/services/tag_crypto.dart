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
class TagCrypto {
  static const _prefix = 'C1';
  static const _nonceLen = 12;
  static const _macLen = 16;

  static bool looksSealed(String text) => text.startsWith('$_prefix.');

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
