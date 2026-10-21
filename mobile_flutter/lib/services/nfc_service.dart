import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:nfc_manager/ndef_record.dart';
import 'package:nfc_manager/nfc_manager.dart';
import 'package:nfc_manager/nfc_manager_android.dart';

import 'tag_crypto.dart';

/// Thin wrapper around `nfc_manager` for reading/writing a physical NFC
/// card — used by the responder-side "Tap NFC Card" scanner and by staff
/// registering a card. Android-only in this app (iOS NFC reading/writing
/// needs extra entitlements/capabilities this project doesn't set up);
/// other platforms report `unsupported`.
///
/// The UID format returned here (uppercase hex, no separators, e.g.
/// `"04A1B2C3D4"`) is what the web admin console's "Register NFC Card"
/// prompt expects too — both sides need to agree on one canonical string
/// form for the same physical UID bytes.
///
/// Two independent things live on the same physical tag (see
/// `backend/app/routers/emergency.py`'s `_build_compact_tag_text`
/// docstring for the full rationale):
///   - The tag's own hardware UID -- a lookup KEY, resolved server-side
///     against `EmergencyToken.nfc_uid` (POST /emergency/nfc/scan). Needs
///     network.
///   - An optional NDEF TEXT record written directly onto the tag's own
///     memory -- the actual critical data (blood type / allergies /
///     meds), readable with ZERO network, by ANY standard NFC reader, for
///     the case where the entire backend is unreachable, not just a WAN
///     link. This is the true offline fallback.
class NfcService {
  static bool get isSupportedPlatform => defaultTargetPlatform == TargetPlatform.android;

  static Future<NfcAvailability> checkAvailability() {
    if (!isSupportedPlatform) return Future.value(NfcAvailability.unsupported);
    return NfcManager.instance.checkAvailability();
  }

  /// Starts an NFC session and resolves with the first tag's UID as a hex
  /// string, or `null` if the tag couldn't be read as a standard
  /// ISO14443/15693/18092 tag with an identifiable UID. Always stops the
  /// session before resolving (single-shot read, not a continuous stream).
  static Future<String?> readTagUidOnce() async {
    final result = await readTagOnce();
    return result.uid;
  }

  /// Same single tap as [readTagUidOnce], but also returns whatever
  /// compact offline text is already written on the tag's own NDEF memory
  /// (`null` if the tag has no NDEF text record, isn't NDEF-formatted, or
  /// reading failed) -- one tap gets both the online lookup key AND the
  /// offline fallback data, so the caller doesn't have to guess up front
  /// whether the network will be up when it tries the online lookup.
  static Future<NfcReadResult> readTagOnce() async {
    if (!isSupportedPlatform) return const NfcReadResult();

    final completer = Completer<NfcReadResult>();
    await NfcManager.instance.startSession(
      pollingOptions: {
        NfcPollingOption.iso14443,
        NfcPollingOption.iso15693,
        NfcPollingOption.iso18092,
      },
      onDiscovered: (NfcTag tag) async {
        String? uid;
        var kind = NfcTagKind.unknown;
        final androidTag = NfcTagAndroid.from(tag);
        if (androidTag != null) {
          uid = _bytesToHex(androidTag.id);
          kind = classifyTech(androidTag.techList);
        }

        String? ndefText;
        final ndef = NdefAndroid.from(tag);
        if (ndef != null) {
          final message = ndef.cachedNdefMessage ?? await _safeGetNdefMessage(ndef);
          if (message != null) {
            ndefText = extractTextRecord(message);
          }
        }

        await NfcManager.instance.stopSession();
        if (!completer.isCompleted) {
          completer.complete(NfcReadResult(uid: uid, ndefText: ndefText, kind: kind));
        }
      },
    );
    return completer.future;
  }

  /// Writes [text] as a single NDEF TEXT record onto the next tapped tag,
  /// replacing whatever NDEF content it currently has (this is meant for a
  /// tag CLARION already controls end-to-end -- the emergency-card
  /// offline fallback -- not a general-purpose NDEF writer). Returns a
  /// [NfcWriteResult] describing what happened; never throws.
  static Future<NfcWriteResult> writeNdefText(String text,
      {String languageCode = 'en', String? publicUrl}) async {
    if (!isSupportedPlatform) return NfcWriteResult.unsupported;
    // Plaintext is never written to a tag (legacy plaintext tags stay readable).
    if (!TagCrypto.isWellFormedBlob(text)) return NfcWriteResult.notEncrypted;

    final completer = Completer<NfcWriteResult>();
    await NfcManager.instance.startSession(
      pollingOptions: {
        NfcPollingOption.iso14443,
        NfcPollingOption.iso15693,
        NfcPollingOption.iso18092,
      },
      onDiscovered: (NfcTag tag) async {
        final ndef = NdefAndroid.from(tag);
        if (ndef == null) {
          await NfcManager.instance.stopSession();
          if (!completer.isCompleted) completer.complete(NfcWriteResult.notNdef);
          return;
        }
        if (!ndef.isWritable) {
          await NfcManager.instance.stopSession();
          if (!completer.isCompleted) completer.complete(NfcWriteResult.notWritable);
          return;
        }

        // Without a public URL: marker FIRST (Android dispatches on the first
        // record, launching CLARION from a locked phone, see MainActivity.kt).
        // With one (register's url_on_tag): the URI record goes first so a
        // phone without the app opens the link.
        final message =
            NdefMessage(records: buildTagRecords(text, languageCode: languageCode, publicUrl: publicUrl));
        if (message.byteLength > ndef.maxSize) {
          await NfcManager.instance.stopSession();
          if (!completer.isCompleted) completer.complete(NfcWriteResult.tooLarge);
          return;
        }

        try {
          await ndef.writeNdefMessage(message);
          await NfcManager.instance.stopSession();
          if (!completer.isCompleted) completer.complete(NfcWriteResult.success);
        } catch (_) {
          await NfcManager.instance.stopSession();
          if (!completer.isCompleted) completer.complete(NfcWriteResult.writeFailed);
        }
      },
    );
    return completer.future;
  }

  /// The records written to a tag, in order: [URI (if [publicUrl]), launch
  /// marker, sealed text]. Public so the layout and size can be tested.
  static List<NdefRecord> buildTagRecords(String text, {String languageCode = 'en', String? publicUrl}) => [
        if (publicUrl != null && publicUrl.trim().isNotEmpty) buildUriRecord(publicUrl.trim()),
        _buildLaunchMarker(),
        _buildTextRecord(text, languageCode),
      ];

  /// True only for `https://<host>/e/<token>` with no userinfo, query or
  /// fragment and token = [A-Za-z0-9_-]{6,64}: what the server's register
  /// call returns as `public_url`. Anything else must never be written.
  static bool isValidPublicUrl(String url) {
    final u = Uri.tryParse(url.trim());
    if (u == null || u.scheme != 'https' || u.host.isEmpty) return false;
    if (u.userInfo.isNotEmpty || u.hasQuery || u.hasFragment) return false;
    final raw = url.trim();
    if (raw.contains('?') || raw.contains('#') || raw.contains('@')) return false;
    final m = RegExp(r'^/e/([A-Za-z0-9_-]{6,64})$').firstMatch(u.path);
    return m != null;
  }

  /// NFC Forum URI record (well-known 'U'): prefix code 0x04 "https://",
  /// 0x03 "http://", else 0x00 + the full URL.
  static NdefRecord buildUriRecord(String url) {
    var code = 0x00;
    var rest = url;
    if (url.startsWith('https://')) {
      code = 0x04;
      rest = url.substring(8);
    } else if (url.startsWith('http://')) {
      code = 0x03;
      rest = url.substring(7);
    }
    return NdefRecord(
      typeNameFormat: TypeNameFormat.wellKnown,
      type: Uint8List.fromList([0x55]), // 'U'
      identifier: Uint8List(0),
      payload: Uint8List.fromList([code, ...utf8.encode(rest)]),
    );
  }

  /// NTAG 424 DNA is an ISO 14443-4 card (IsoDep); NTAG213/215/216 are
  /// Type 2 tags (MifareUltralight) with no tamper-proof read counter.
  /// Everything else is `unknown`. Both known kinds work with CLARION --
  /// the kind only drives the "no read counter" warning.
  static NfcTagKind classifyTech(List<String> techList) {
    if (techList.any((t) => t.endsWith('.IsoDep'))) return NfcTagKind.ntag424;
    if (techList.any((t) => t.endsWith('.MifareUltralight'))) return NfcTagKind.ntag21x;
    return NfcTagKind.unknown;
  }

  static Future<void> cancelSession() async {
    if (!isSupportedPlatform) return;
    try {
      await NfcManager.instance.stopSession();
    } catch (_) {
      // No active session — fine to ignore.
    }
  }

  static Future<NdefMessage?> _safeGetNdefMessage(NdefAndroid ndef) async {
    try {
      return await ndef.getNdefMessage();
    } catch (_) {
      // Not every discovered tag actually speaks NDEF even if it exposed
      // the tech -- a read failure here just means "no offline text",
      // never a crash.
      return null;
    }
  }

  static String _bytesToHex(Uint8List bytes) {
    return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join().toUpperCase();
  }

  /// Builds a standard NDEF "Text" well-known-type record (RTD_TEXT):
  /// payload = [status byte][language-code bytes][UTF-8 text bytes].
  /// Status byte bit 7 = 0 selects UTF-8 (not UTF-16); bits 0-5 = the
  /// language-code's byte length. This is a fixed, stable wire format
  /// (NFC Forum RTD spec) -- readable by any generic NFC reader/app, not
  /// just this one, which is the entire point of writing it onto the tag.
  static NdefRecord _buildTextRecord(String text, String languageCode) {
    final langBytes = utf8.encode(languageCode);
    final textBytes = utf8.encode(text);
    final statusByte = langBytes.length & 0x3F;
    final payload = Uint8List.fromList([statusByte, ...langBytes, ...textBytes]);
    return NdefRecord(
      typeNameFormat: TypeNameFormat.wellKnown,
      type: Uint8List.fromList([0x54]), // 'T'
      identifier: Uint8List(0),
      payload: payload,
    );
  }

  /// MIME record `application/vnd.clarion` -- the launch trigger. 1-byte
  /// payload; ~26 bytes on the tag.
  static NdefRecord _buildLaunchMarker() => NdefRecord(
        typeNameFormat: TypeNameFormat.media,
        type: Uint8List.fromList(utf8.encode('application/vnd.clarion')),
        identifier: Uint8List(0),
        payload: Uint8List.fromList([1]),
      );

  /// Inverse of [_buildTextRecord] -- the first well-formed Text record
  /// found in [message], or `null` if there isn't one.
  @visibleForTesting
  static String? extractTextRecord(NdefMessage message) {
    for (final record in message.records) {
      if (record.typeNameFormat != TypeNameFormat.wellKnown) continue;
      if (record.type.length != 1 || record.type[0] != 0x54) continue;
      if (record.payload.isEmpty) continue;
      final statusByte = record.payload[0];
      final langLen = statusByte & 0x3F;
      if (record.payload.length < 1 + langLen) continue;
      try {
        return utf8.decode(record.payload.sublist(1 + langLen));
      } catch (_) {
        continue; // malformed text bytes -- try the next record, if any
      }
    }
    return null;
  }
}

/// Result of a single tag tap: the hardware UID (lookup key) and/or
/// whatever compact offline text is already written on it. Either field
/// may be `null` independently -- a blank/never-registered tag has a UID
/// but no text; a UID read failure with a readable NDEF text is unusual
/// but handled the same way (both fields are simply best-effort).
class NfcReadResult {
  const NfcReadResult({this.uid, this.ndefText, this.kind = NfcTagKind.unknown});
  final String? uid;
  final String? ndefText;
  final NfcTagKind kind;
}

/// What kind of physical tag was tapped. Only [ntag424] has the tamper-proof
/// read counter; [ntag21x] (NTAG213/215/216) and [unknown] work but get a
/// warning, because offline reads of them can't be checked for omissions.
enum NfcTagKind { ntag21x, ntag424, unknown }

extension NfcTagKindX on NfcTagKind {
  bool get hasReadCounter => this == NfcTagKind.ntag424;
}

enum NfcWriteResult {
  success,
  unsupported,
  notNdef,
  notWritable,
  tooLarge,
  notEncrypted,
  writeFailed,
}
