import 'package:external_app_launcher/external_app_launcher.dart';
import 'package:url_launcher/url_launcher.dart';

/// Deep link out to the MySejahtera app to book/manage a medical
/// appointment there, since this MVP's backend has no appointment
/// -booking feature of its own.
///
/// HONESTY NOTE (updated): the Android package ID
/// (`my.gov.onegovappstore.mysejahtera`) below is now a **verified fact**,
/// confirmed against the live Google Play Store listing
/// (https://play.google.com/store/apps/details?id=my.gov.onegovappstore.mysejahtera)
/// — not a guess. An earlier version of this file guessed
/// `com.mysejahtera.government` / a `mysejahtera://` custom scheme, both
/// of which were wrong, which is almost certainly why the button
/// previously did nothing useful.
///
/// What's still **unconfirmed**: whether MySejahtera exposes any internal
/// deep-link scheme for jumping straight to its appointment-booking
/// screen specifically (as opposed to just opening the app to wherever it
/// last was) — no public documentation of one was found. This launcher
/// only opens the app itself; the user still has to navigate to
/// "appointments" inside MySejahtera themselves.
///
/// Uses `external_app_launcher`'s `LaunchApp.openApp` (the idiomatic
/// Flutter way to open another app by verified package name) instead of
/// `url_launcher` + a guessed custom scheme: it opens the app directly if
/// installed, or the Play Store listing for that exact package if not —
/// no scheme-guessing involved either way.
class MySejahteraLauncher {
  static const _androidPackage = 'my.gov.onegovappstore.mysejahtera'; // verified — see note above
  static const _webFallbackUrl = 'https://www.mysejahtera.gov.my/';

  /// Returns true if something useful was launched: the app itself, or
  /// (if not installed) its Play Store listing, or — only if the plugin
  /// call itself throws — the official website as a last resort.
  static Future<bool> open() async {
    try {
      final result = await LaunchApp.openApp(
        androidPackageName: _androidPackage,
        openStore: true,
      );
      // `openApp` returns 1 for "app opened", 0 for "navigated to the
      // Play Store instead" (app not installed) — both are a legitimate,
      // useful outcome for this button now that the package name is
      // verified correct, so don't treat 0 as a failure requiring the
      // website fallback.
      return result == 1 || result == 0;
    } catch (_) {
      // Only reached if the platform channel call itself fails (e.g. no
      // Play Store on this device at all) — fall back to the website,
      // which should work in any browser.
      try {
        return await launchUrl(Uri.parse(_webFallbackUrl), mode: LaunchMode.externalApplication);
      } catch (_) {
        return false;
      }
    }
  }
}
