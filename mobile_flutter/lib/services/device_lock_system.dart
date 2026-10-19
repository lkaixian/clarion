import 'package:local_auth/local_auth.dart';

import 'device_lock.dart';

/// [DeviceLock] wired to the phone's own biometric / PIN / pattern prompt.
DeviceLock systemDeviceLock() {
  final local = LocalAuthentication();
  return DeviceLock(
    isSupported: local.isDeviceSupported,
    authenticate: (reason) async {
      try {
        // Biometric OR the device PIN/pattern (biometricOnly defaults to false).
        // persistAcrossBackgrounding: an NFC tap re-delivering an intent, or a
        // call, backgrounds the app mid-prompt; retry on return instead of
        // failing the read.
        return await local.authenticate(localizedReason: reason, persistAcrossBackgrounding: true);
      } on LocalAuthException catch (e) {
        if (e.code == LocalAuthExceptionCode.noCredentialsSet ||
            e.code == LocalAuthExceptionCode.noBiometricsEnrolled) {
          throw const DeviceLockException(DeviceLockResult.noScreenLock);
        }
        return false;
      }
    },
  );
}
