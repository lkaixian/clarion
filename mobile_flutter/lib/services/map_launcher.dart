import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/generated/app_localizations.dart';
import '../widgets/common.dart' show ContextX;

/// Opens [uri] outside the app; true when something handled it.
typedef UrlOpener = Future<bool> Function(Uri uri);

Future<bool> _externalOpen(Uri uri) => launchUrl(uri, mode: LaunchMode.externalApplication);

/// Opens a map at [lat],[lng]. Android: a `geo:` intent (any maps app), then
/// the Google Maps web link; iOS: Apple Maps; elsewhere the web link. Never
/// throws: false means nothing could open it. [platform]/[open] are for tests.
Future<bool> openMap(
  double lat,
  double lng, {
  String label = 'CLARION',
  TargetPlatform? platform,
  UrlOpener? open,
}) async {
  final go = open ?? _externalOpen;
  final q = '${lat.toStringAsFixed(6)},${lng.toStringAsFixed(6)}';
  try {
    switch (platform ?? defaultTargetPlatform) {
      case TargetPlatform.iOS:
        return await go(Uri.parse('https://maps.apple.com/?q=$q'));
      case TargetPlatform.android:
        if (await go(Uri.parse('geo:$q?q=$q(${Uri.encodeComponent(label)})'))) return true;
      default:
        break;
    }
    return await go(Uri.parse('https://maps.google.com/?q=$q'));
  } catch (_) {
    return false;
  }
}

/// [openMap] that tells the user with a snackbar when it fails.
Future<void> openMapOrSnack(BuildContext context, double lat, double lng, {UrlOpener? open}) async {
  final message = AppLocalizations.of(context).mapOpenFailed;
  final ok = await openMap(lat, lng, open: open);
  if (!ok && context.mounted) context.snack(message);
}

/// Opens an https link (a notification's maps URL) externally; snackbar on failure.
Future<void> openExternalLinkOrSnack(BuildContext context, String url, {UrlOpener? open}) async {
  final message = AppLocalizations.of(context).mapOpenFailed;
  var ok = false;
  try {
    final uri = Uri.parse(url);
    ok = uri.scheme == 'https' && await (open ?? _externalOpen)(uri);
  } catch (_) {}
  if (!ok && context.mounted) context.snack(message);
}
