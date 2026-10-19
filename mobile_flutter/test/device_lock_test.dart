import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_flutter/services/device_lock.dart';

DeviceLock _lock({
  bool supported = true,
  Future<bool> Function(String)? auth,
  required DateTime Function() now,
  List<String>? prompts,
}) {
  return DeviceLock(
    isSupported: () async => supported,
    authenticate: (reason) async {
      prompts?.add(reason);
      if (auth == null) return true;
      return auth(reason);
    },
    now: now,
  );
}

void main() {
  var t = DateTime.utc(2026, 10, 19, 12);
  DateTime now() => t;
  setUp(() => t = DateTime.utc(2026, 10, 19, 12));

  test('prompts with the given reason and unlocks on success', () async {
    final prompts = <String>[];
    final lock = _lock(now: now, prompts: prompts);
    expect(await lock.unlock('Confirm it is you'), DeviceLockResult.unlocked);
    expect(prompts, ['Confirm it is you']);
  });

  test('does not prompt again inside the grace window, but does after it', () async {
    final prompts = <String>[];
    final lock = _lock(now: now, prompts: prompts);
    await lock.unlock('r');
    t = t.add(DeviceLock.grace - const Duration(seconds: 1));
    expect(await lock.unlock('r'), DeviceLockResult.unlocked);
    expect(prompts.length, 1);
    t = t.add(const Duration(seconds: 2));
    expect(await lock.unlock('r'), DeviceLockResult.unlocked);
    expect(prompts.length, 2);
  });

  test('a failed or cancelled check is denied and never opens the grace window', () async {
    final lock = _lock(now: now, auth: (_) async => false);
    expect(await lock.unlock('r'), DeviceLockResult.denied);
    expect(await lock.unlock('r'), DeviceLockResult.denied);
  });

  test('a phone with no screen lock is refused without prompting', () async {
    final prompts = <String>[];
    final lock = _lock(supported: false, now: now, prompts: prompts);
    expect(await lock.unlock('r'), DeviceLockResult.noScreenLock);
    expect(prompts, isEmpty);
  });

  test('the platform reporting no credentials maps to noScreenLock', () async {
    final lock = _lock(
      now: now,
      auth: (_) async => throw const DeviceLockException(DeviceLockResult.noScreenLock),
    );
    expect(await lock.unlock('r'), DeviceLockResult.noScreenLock);
  });

  test('any other platform error is a denial, not a crash', () async {
    final lock = _lock(now: now, auth: (_) async => throw StateError('boom'));
    expect(await lock.unlock('r'), DeviceLockResult.denied);
  });

  test('overlapping unlocks share one prompt', () async {
    final prompts = <String>[];
    final lock = _lock(now: now, prompts: prompts);
    final results = await Future.wait([lock.unlock('r'), lock.unlock('r'), lock.unlock('r')]);
    expect(results, everyElement(DeviceLockResult.unlocked));
    expect(prompts.length, 1);
  });

  test('a sign-out during the prompt leaves no grace window', () async {
    late DeviceLock lock;
    final prompts = <String>[];
    lock = _lock(
      now: now,
      prompts: prompts,
      auth: (_) async {
        lock.lock(); // user logs out while the dialog is open
        return true;
      },
    );
    expect(await lock.unlock('r'), DeviceLockResult.denied);
    await lock.unlock('r'); // still has to prompt again
    expect(prompts.length, 2);
  });

  test('lock() ends the grace window (sign-out)', () async {
    final prompts = <String>[];
    final lock = _lock(now: now, prompts: prompts);
    await lock.unlock('r');
    lock.lock();
    await lock.unlock('r');
    expect(prompts.length, 2);
  });

  test('backgrounding ends the grace window, but not a prompt already on screen', () async {
    final prompts = <String>[];
    final lock = _lock(now: now, prompts: prompts);
    await lock.unlock('r');
    lock.lockIfIdle(); // app paused
    await lock.unlock('r');
    expect(prompts.length, 2);

    late DeviceLock shown;
    shown = _lock(now: now, prompts: prompts, auth: (_) async {
      shown.lockIfIdle(); // the platform backgrounds the app while its dialog is up
      return true;
    });
    // The prompt was passed, but the app went to the background meanwhile: no grace window.
    expect(await shown.unlock('r'), DeviceLockResult.denied);
    await shown.unlock('r');
    expect(prompts.length, 4);
  });
}
