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

  Future<void> saveToken(String token) => _storage.write(key: _tokenKey, value: token);

  Future<String?> readToken() => _storage.read(key: _tokenKey);

  Future<void> saveUser(Map<String, dynamic> user) =>
      _storage.write(key: _userKey, value: jsonEncode(user));

  Future<Map<String, dynamic>?> readUser() async {
    final raw = await _storage.read(key: _userKey);
    if (raw == null) return null;
    return jsonDecode(raw) as Map<String, dynamic>;
  }

  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _userKey);
  }
}
