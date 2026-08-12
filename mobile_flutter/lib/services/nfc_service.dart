import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:nfc_manager/nfc_manager.dart';
import 'package:nfc_manager/nfc_manager_android.dart';

/// Thin wrapper around `nfc_manager` for reading a physical NFC card's UID
/// — used by the responder-side "Tap NFC Card" scanner. Android-only in
/// this app (iOS NFC reading needs extra entitlements/capabilities this
/// project doesn't set up); other platforms report `unsupported`.
///
/// The UID format returned here (uppercase hex, no separators, e.g.
/// `"04A1B2C3D4"`) is what the web admin console's "Register NFC Card"
/// prompt expects too — both sides need to agree on one canonical string
/// form for the same physical UID bytes.
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
    if (!isSupportedPlatform) return null;

    final completer = Completer<String?>();
    await NfcManager.instance.startSession(
      pollingOptions: {
        NfcPollingOption.iso14443,
        NfcPollingOption.iso15693,
        NfcPollingOption.iso18092,
      },
      onDiscovered: (NfcTag tag) async {
        String? uid;
        final androidTag = NfcTagAndroid.from(tag);
        if (androidTag != null) {
          uid = _bytesToHex(androidTag.id);
        }
        await NfcManager.instance.stopSession();
        if (!completer.isCompleted) completer.complete(uid);
      },
    );
    return completer.future;
  }

  static Future<void> cancelSession() async {
    if (!isSupportedPlatform) return;
    try {
      await NfcManager.instance.stopSession();
    } catch (_) {
      // No active session — fine to ignore.
    }
  }

  static String _bytesToHex(Uint8List bytes) {
    return bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join().toUpperCase();
  }
}
