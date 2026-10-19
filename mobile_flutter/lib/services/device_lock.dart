enum DeviceLockResult {
  /// The user just proved presence (or did so within [DeviceLock.grace]).
  unlocked,

  /// Cancelled, failed or timed out.
  denied,

  /// The phone has no screen lock / biometric at all, so there is nothing to
  /// prove: reading the cached tag keys is refused rather than left open.
  noScreenLock,
}

class DeviceLockException implements Exception {
  const DeviceLockException(this.result);
  final DeviceLockResult result;
  @override
  String toString() => 'DeviceLockException($result)';
}

/// Biometric / device PIN gate in front of the cached NFC tag keys, so a
/// stolen phone that is merely unlocked-in-the-app (or has the app left open)
/// cannot read cards without the owner proving presence.
///
/// This class is the policy only (grace window, mapping failures to a result);
/// the platform prompt is injected, and `device_lock_system.dart` wires it to
/// `local_auth`. Honest limits: this is an app-level check, not a
/// hardware-bound key. It stops a casual thief and a borrowed phone; a rooted
/// device or an attacker who can extract the secure-storage contents is not
/// stopped by it.
class DeviceLock {
  /// [isSupported]: the phone has a screen lock or biometric to check against.
  /// [authenticate]: shows the prompt; true = passed, false = failed. It may
  /// throw [DeviceLockException] to report [DeviceLockResult.noScreenLock].
  DeviceLock({
    required this.isSupported,
    required this.authenticate,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  /// After a successful check, further reads within this window do not prompt
  /// again, so a responder working through several tags is not interrupted.
  static const grace = Duration(seconds: 60);

  final Future<bool> Function() isSupported;
  final Future<bool> Function(String reason) authenticate;
  final DateTime Function() _now;
  DateTime? _unlockedAt;
  Future<DeviceLockResult>? _pending;
  int _generation = 0;

  /// Prompts (unless inside the grace window). [reason] is shown in the system
  /// dialog, so it must be localized by the caller. Overlapping calls share the
  /// one prompt already on screen instead of starting a second (which the
  /// platform rejects as "already in progress").
  Future<DeviceLockResult> unlock(String reason) {
    final at = _unlockedAt;
    if (at != null && _now().difference(at) < grace) {
      return Future.value(DeviceLockResult.unlocked);
    }
    return _pending ??= _prompt(reason).whenComplete(() => _pending = null);
  }

  Future<DeviceLockResult> _prompt(String reason) async {
    final started = _generation;
    try {
      if (!await isSupported()) return DeviceLockResult.noScreenLock;
      if (await authenticate(reason)) {
        // A sign-out while the prompt was open must not leave a grace window.
        if (started != _generation) return DeviceLockResult.denied;
        _unlockedAt = _now();
        return DeviceLockResult.unlocked;
      }
    } on DeviceLockException catch (e) {
      return e.result;
    } catch (_) {/* any platform failure is a denial */}
    return DeviceLockResult.denied;
  }

  /// Forget a previous success (sign-out), including one still being prompted.
  void lock() {
    _generation++;
    _unlockedAt = null;
  }
}
