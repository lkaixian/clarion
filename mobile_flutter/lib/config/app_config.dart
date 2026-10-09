import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Holds the backend API base URL and makes it runtime-editable.
///
/// Precedence:
///   1. A value the user has saved in the in-app Settings screen
///      (persisted via [SharedPreferences]) — wins if present.
///   2. The compile-time `--dart-define=API_BASE_URL=...` value.
///   3. `https://clarion.larmkx.com/api` (the central node's fixed public
///      name, served by the Cloudflare Tunnel) as the fallback. For an emulator
///      against a local backend: --dart-define=API_BASE_URL=http://10.0.2.2:8000
///
/// This makes the app "tunnel-ready": once a `trycloudflare.com` URL is
/// available, point the app at it from the Settings screen without a
/// rebuild — the URL changes every time the tunnel restarts, so baking it
/// into the binary would be a bad fit.
class AppConfig extends ChangeNotifier {
  static const String _compileTimeDefault =
      String.fromEnvironment('API_BASE_URL', defaultValue: 'https://clarion.larmkx.com/api');

  static const String _prefsKey = 'mb_api_base_url_override';

  static const String _pinnedCertSha1 =
      String.fromEnvironment('PINNED_CERT_SHA1', defaultValue: '');

  /// Hex SHA-1 fingerprints of the backend's expected TLS leaf certificate,
  /// comma-separated (list both old+new during a cert renewal window).
  /// Empty (the default) means pinning is off -- same "supplied at deploy"
  /// pattern as the backend's `CLARION_TLS_DIRECTIVE`/`LDAP_CA_CERT_FILE`.
  /// See [ApiClient]'s constructor for where this is enforced and why it's
  /// only checked against [compileTimeDefault], not a Settings override.
  List<String> get pinnedCertSha1Fingerprints => _pinnedCertSha1
      .split(',')
      .map((s) => s.trim().toLowerCase().replaceAll(':', ''))
      .where((s) => s.isNotEmpty)
      .toList(growable: false);

  String _baseUrl = _compileTimeDefault;
  bool _loaded = false;

  String get baseUrl => _baseUrl;
  String get compileTimeDefault => _compileTimeDefault;
  bool get isLoaded => _loaded;
  bool get isOverridden => _baseUrl != _compileTimeDefault;

  /// Must be called once at startup before the API client is used for real
  /// requests (a splash/loading screen should await this).
  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_prefsKey);
    if (saved != null && saved.trim().isNotEmpty) {
      _baseUrl = saved.trim();
    }
    _loaded = true;
    notifyListeners();
  }

  Future<void> setBaseUrl(String url) async {
    final trimmed = _normalize(url);
    final prefs = await SharedPreferences.getInstance();
    if (trimmed.isEmpty || trimmed == _compileTimeDefault) {
      await prefs.remove(_prefsKey);
      _baseUrl = _compileTimeDefault;
    } else {
      await prefs.setString(_prefsKey, trimmed);
      _baseUrl = trimmed;
    }
    notifyListeners();
  }

  Future<void> resetToDefault() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefsKey);
    _baseUrl = _compileTimeDefault;
    notifyListeners();
  }

  String _normalize(String url) {
    var trimmed = url.trim();
    while (trimmed.endsWith('/')) {
      trimmed = trimmed.substring(0, trimmed.length - 1);
    }
    return trimmed;
  }
}
