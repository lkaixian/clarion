import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:cryptography/cryptography.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api_client.dart';
import 'api_exception.dart';
import 'device_lock.dart';
import 'device_lock_system.dart';
import 'tag_crypto.dart';

/// Result of checking a card's UID against the cached revoked-card list.
enum RevocationCheck { clear, revoked, unknown }

/// Device-side half of the offline emergency-tag audit trail.
///
/// When a tag is read with no network the app decrypts it locally (see
/// `TagCrypto`) -- nothing reaches the server at that moment. Each such read
/// is appended here as a hash-chained entry (per signed-in user, so an
/// upload is always attributed to the person who actually did the read) and
/// uploaded to `POST /emergency/offline-reads` the next time that user is
/// online. `backend/app/tag_crypto.py::read_entry_hash` is the reference for
/// the chain's canonical string.
///
/// Honest limits: a device owner can wipe this log before upload. The chain
/// only exposes edits/deletions in the *middle* of what was uploaded; the
/// tag-side read counter (NTAG 424 DNA, a later phase) is what detects a
/// dropped tail.
class OfflineReadLog {
  OfflineReadLog({FlutterSecureStorage? storage, DeviceLock? lock})
      : _s = storage ?? const FlutterSecureStorage(),
        _lock = lock ?? systemDeviceLock();

  final FlutterSecureStorage _s;
  final DeviceLock _lock;

  static const genesisHash =
      '0000000000000000000000000000000000000000000000000000000000000000';
  static const _deviceKey = 'clarion_device_id';
  static const _keysKey = 'clarion_tag_keys';
  static const _keysAtKey = 'clarion_tag_keys_at';
  static const _revocationKey = 'clarion_tag_revocation';

  /// Cached keys (and the revoked-card list) stop being used for offline reads
  /// this long after the last successful refresh, so a disabled account /
  /// stolen phone cannot keep decrypting indefinitely. The server sets the
  /// value (`key_max_age_hours`, default 24); this is the fallback until the
  /// first sync stores one.
  static const defaultKeyMaxAge = Duration(hours: TagKeySet.defaultMaxAgeHours);

  // Serialises every read-modify-write of the chain so a background
  // acknowledge can never overwrite a concurrent append (lost entry /
  // forked chain), and so two syncs can't upload the same batch at once.
  static Future<void> _tail = Future<void>.value();
  static Future<T> _serial<T>(Future<T> Function() body) {
    final run = _tail.then((_) => body());
    _tail = run.then((_) {}, onError: (_) {});
    return run;
  }
  static String _logKey(String userId) => 'clarion_offline_log_$userId';

  // ---- data keys -----------------------------------------------------

  Map<String, dynamic>? _decodeRevocation(String? raw) {
    if (raw == null) return null;
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  /// True while the last successful refresh is within the server-set lifetime.
  Future<bool> _fresh() async {
    final at = DateTime.tryParse(await _s.read(key: _keysAtKey) ?? '');
    if (at == null) return false;
    final stored = _decodeRevocation(await _s.read(key: _revocationKey));
    final hours = stored?['max_age_hours'];
    final maxAge = hours is int && hours > 0 ? Duration(hours: hours) : defaultKeyMaxAge;
    final now = DateTime.now().toUtc();
    final until = DateTime.tryParse((stored?['valid_until'] as String?) ?? '');
    if (until != null && !now.isBefore(until)) return false; // time-boxed account has ended
    return now.difference(at) <= maxAge;
  }

  /// Cached keys, or empty if none / past the key lifetime. The device
  /// biometric / PIN check comes FIRST, before secure storage is touched; it
  /// throws [DeviceLockException] when the user does not pass it (or the
  /// phone has no screen lock). [reason] is the localized prompt text.
  Future<Map<String, String>> readKeys({required String reason}) async {
    final unlocked = await _lock.unlock(reason);
    if (unlocked != DeviceLockResult.unlocked) throw DeviceLockException(unlocked);
    final raw = await _s.read(key: _keysKey);
    if (raw == null || !await _fresh()) return {};
    try {
      return (jsonDecode(raw) as Map<String, dynamic>).cast<String, String>();
    } catch (_) {
      return {};
    }
  }

  /// The app went to the background: the next read prompts again.
  void relockIfIdle() => _lock.lockIfIdle();

  Future<void> saveKeys(TagKeySet set) async {
    await _s.write(key: _keysKey, value: jsonEncode(set.keys));
    await _s.write(
      key: _revocationKey,
      value: jsonEncode({
        'key': set.revocationKey,
        'ids': set.revokedCardIds.toList(),
        'max_age_hours': set.maxAgeHours,
        'valid_until': set.validUntil?.toIso8601String(),
      }),
    );
    await _s.write(key: _keysAtKey, value: DateTime.now().toUtc().toIso8601String());
  }

  /// Checks [uid] (canonical hex, as read from the tag) against the cached
  /// revoked-card list. [RevocationCheck.unknown] means there is no fresh list
  /// to check against (never synced, or past the key lifetime): a sealed tag
  /// cannot open then anyway (no usable keys), but a legacy plaintext tag needs
  /// no key, so the caller must refuse it on `unknown`. Fresh keys from before
  /// this feature carry no revocation key and count as `revoked` (fail safe)
  /// until the next sync stores one.
  Future<RevocationCheck> checkRevocation(String uid) async {
    if (uid.isEmpty || !await _fresh()) return RevocationCheck.unknown;
    final stored = _decodeRevocation(await _s.read(key: _revocationKey));
    final key = stored?['key'];
    if (key is! String) return RevocationCheck.revoked;
    final ids = (stored!['ids'] as List?)?.cast<String>() ?? const <String>[];
    return ids.contains(await TagCrypto.revocationId(uid, key))
        ? RevocationCheck.revoked
        : RevocationCheck.clear;
  }

  /// Called on sign-out: a signed-out device must not keep offline access.
  Future<void> clearKeys() async {
    _lock.lock();
    await _s.delete(key: _keysKey);
    await _s.delete(key: _keysAtKey);
    await _s.delete(key: _revocationKey);
  }

  Future<void> _rotateDeviceId() => _s.delete(key: _deviceKey);

  // ---- chained log ---------------------------------------------------

  Future<String> deviceId() async {
    var id = await _s.read(key: _deviceKey);
    if (id == null) {
      final r = Random.secure();
      id = List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
      await _s.write(key: _deviceKey, value: id);
    }
    return id;
  }

  Future<Map<String, dynamic>> _state(String userId) async {
    final raw = await _s.read(key: _logKey(userId));
    if (raw == null) return {'next_seq': 0, 'head': genesisHash, 'pending': <dynamic>[]};
    return jsonDecode(raw) as Map<String, dynamic>;
  }

  static Future<String> entryHash(
    String prevHash, int seq, String readAt, String uid, int keyId, String outcome,
  ) async {
    final h = await Sha256().hash(utf8.encode('$prevHash|$seq|$readAt|$uid|$keyId|$outcome'));
    return h.bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
  }

  /// Appends one read to [userId]'s chain. [outcome] is `decrypted` or `failed`.
  Future<void> append({
    required String userId,
    required String uid,
    required int keyId,
    required String outcome,
  }) {
    return _serial(() async {
      final st = await _state(userId);
      final seq = st['next_seq'] as int;
      final prev = st['head'] as String;
      final readAt = DateTime.now().toUtc().toIso8601String();
      final hash = await entryHash(prev, seq, readAt, uid, keyId, outcome);
      (st['pending'] as List).add({
        'seq': seq,
        'read_at': readAt,
        'nfc_uid': uid,
        'key_id': keyId,
        'outcome': outcome,
        'prev_hash': prev,
        'entry_hash': hash,
      });
      st['next_seq'] = seq + 1;
      st['head'] = hash;
      await _s.write(key: _logKey(userId), value: jsonEncode(st));
    });
  }

  Future<List<Map<String, dynamic>>> pending(String userId) async =>
      ((await _state(userId))['pending'] as List).cast<Map<String, dynamic>>();

  Future<void> acknowledge(String userId, int maxSeq) => _serial(() async {
        final st = await _state(userId);
        (st['pending'] as List).removeWhere((e) => (e as Map)['seq'] <= maxSeq);
        await _s.write(key: _logKey(userId), value: jsonEncode(st));
      });

  // ---- sync (best effort, never throws) -------------------------------

  /// Refreshes the cached data keys and uploads this user's pending reads.
  Future<void> sync(ApiClient api, String userId) {
    // One sync at a time: login, scanner-open and bootstrap all fire it.
    return _serialSync(() async {
      try {
        final keys = await api.getTagKeys();
        if (keys.keys.isNotEmpty) await saveKeys(keys);
      } on ApiException catch (e) {
        // The server said no (disabled account, role change): drop offline
        // access now rather than at the key-lifetime expiry. A network failure
        // keeps the cache.
        if (e.statusCode == 401 || e.statusCode == 403) await clearKeys();
      } catch (_) {/* keep whatever is cached */}
      try {
        var batch = await pending(userId);
        while (batch.isNotEmpty) {
          final chunk = batch.take(25).toList();
          final res = await api.uploadOfflineReads(await deviceId(), chunk);
          if ((res['conflicts'] as num? ?? 0) > 0) {
            // The server already holds different entries for these seqs
            // (this device's log state was reset). Re-upload under a fresh
            // device id so nothing is silently dropped; the chain itself
            // doesn't include the device id, so it stays valid.
            await _rotateDeviceId();
            await api.uploadOfflineReads(await deviceId(), chunk);
          }
          await acknowledge(userId, chunk.last['seq'] as int);
          batch = await pending(userId);
        }
      } catch (_) {/* try again next time */}
    });
  }

  static Future<void>? _inFlight;
  static Future<void> _serialSync(Future<void> Function() body) {
    final running = _inFlight;
    if (running != null) return running;
    final f = body().whenComplete(() => _inFlight = null);
    _inFlight = f;
    return f;
  }
}
