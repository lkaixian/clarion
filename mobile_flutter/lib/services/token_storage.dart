import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Wraps [FlutterSecureStorage] for the auth token + a cached copy of the
/// logged-in user's profile JSON, so the app can restore a session on
/// cold start without re-hitting the network.
class TokenStorage {
  TokenStorage() : _storage = const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _tokenKey = 'mb_token';
  static const _userKey = 'mb_user';
  // P2.5 (Security Audit M4): the long-lived refresh token. A native app
  // has no browser cookie jar (the mechanism the web console uses instead
  // -- an HttpOnly cookie), so the backend returns this to native clients
  // as a plain JSON field on login/refresh (see schemas.Token's
  // docstring) and it's stored here, in the OS keychain/keystore via
  // FlutterSecureStorage -- already a stronger storage location than a
  // browser's cookie jar, so no separate hardening needed for this value.
  static const _refreshTokenKey = 'mb_refresh_token';

  Future<void> saveToken(String token) => _storage.write(key: _tokenKey, value: token);

  Future<String?> readToken() => _storage.read(key: _tokenKey);

  Future<void> saveRefreshToken(String refreshToken) =>
      _storage.write(key: _refreshTokenKey, value: refreshToken);

  Future<String?> readRefreshToken() => _storage.read(key: _refreshTokenKey);

  Future<void> saveUser(Map<String, dynamic> user) =>
      _storage.write(key: _userKey, value: jsonEncode(user));

  Future<Map<String, dynamic>?> readUser() async {
    final raw = await _storage.read(key: _userKey);
    if (raw == null) return null;
    return jsonDecode(raw) as Map<String, dynamic>;
  }

  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _refreshTokenKey);
    await _storage.delete(key: _userKey);
  }
}
