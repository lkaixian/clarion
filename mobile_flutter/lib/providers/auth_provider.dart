import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/token_storage.dart';

enum AuthStatus { unknown, authenticated, unauthenticated }

/// Owns the login session: current user, restoring it on cold start, and
/// the persisted "prefer Senior Citizen Mode" flag used to route straight
/// into the simplified hub after login.
class AuthProvider extends ChangeNotifier {
  AuthProvider({required ApiClient api, required TokenStorage tokenStorage})
      : _api = api,
        _tokenStorage = tokenStorage;

  final ApiClient _api;
  final TokenStorage _tokenStorage;

  static const _seniorPrefKey = 'mb_prefers_senior_mode';

  AuthStatus status = AuthStatus.unknown;
  MBUser? user;
  bool isBusy = false;
  String? error;
  bool prefersSeniorMode = false;

  bool get isAuthenticated => status == AuthStatus.authenticated && user != null;

  Future<void> bootstrap() async {
    final prefs = await SharedPreferences.getInstance();
    prefersSeniorMode = prefs.getBool(_seniorPrefKey) ?? false;

    final token = await _tokenStorage.readToken();
    final userJson = await _tokenStorage.readUser();
    if (token != null && userJson != null) {
      user = MBUser.fromJson(userJson);
      status = AuthStatus.authenticated;
    } else {
      status = AuthStatus.unauthenticated;
    }
    notifyListeners();
  }

  Future<bool> login(String email, String password) async {
    isBusy = true;
    error = null;
    notifyListeners();
    try {
      final data = await _api.login(email, password);
      final token = data['access_token'] as String;
      final userJson = data['user'] as Map<String, dynamic>;
      await _tokenStorage.saveToken(token);
      await _tokenStorage.saveUser(userJson);
      user = MBUser.fromJson(userJson);
      status = AuthStatus.authenticated;
      return true;
    } on ApiException catch (e) {
      error = e.message;
      return false;
    } catch (e) {
      error = 'Unexpected error: $e';
      return false;
    } finally {
      isBusy = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    await _tokenStorage.clear();
    user = null;
    status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  Future<void> setPrefersSeniorMode(bool value) async {
    prefersSeniorMode = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_seniorPrefKey, value);
    notifyListeners();
  }
}
