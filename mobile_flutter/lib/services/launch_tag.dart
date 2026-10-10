import 'package:flutter/services.dart';

import 'nfc_service.dart';

/// A CLARION emergency card tapped while the phone was locked / the app was
/// closed: Android launches us via the card's `application/vnd.clarion`
/// record and MainActivity hands the UID + on-tag text over this channel
/// (see MainActivity.kt). Dart-side handoff only; the lookup/decrypt is the
/// normal EmergencyScannerScreen path.
class LaunchTag {
  static const _channel = MethodChannel('clarion/launch_tag');

  /// The tag that launched the app, once (null if none / unsupported).
  static Future<NfcReadResult?> take() async {
    try {
      return _decode(await _channel.invokeMethod<Map<Object?, Object?>>('take'));
    } on MissingPluginException {
      return null;
    }
  }

  /// Taps that arrive while the app is already running.
  static void listen(void Function(NfcReadResult) onTag) {
    _channel.setMethodCallHandler((call) async {
      if (call.method != 'tag') return;
      final tag = _decode(call.arguments as Map<Object?, Object?>?);
      if (tag != null) onTag(tag);
    });
  }

  static NfcReadResult? _decode(Map<Object?, Object?>? m) {
    final uid = m?['uid'] as String?;
    if (uid == null || uid.isEmpty) return null;
    return NfcReadResult(
      uid: uid,
      ndefText: m?['text'] as String?,
      kind: NfcTagKind.ntag21x,
    );
  }
}
