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

  /// True right after a login where the backend flagged this account as
  /// needing a password change (staff-issued temp password). `_AuthGate`
  /// (see app.dart) reads this to route to ChangePasswordScreen instead of
  /// Home/SeniorHome. Cleared locally by [changePassword] on success.
  bool get mustChangePassword => user?.mustChangePassword ?? false;

  /// Informational (see MBUser.missingProfileFields) — never used to block
  /// navigation, only to drive the dismissible "complete your profile"
  /// banner on Home/SeniorHome.
  List<String> get missingProfileFields => user?.missingProfileFields ?? [];

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

  /// Handles the forced "must change password" flow: calls
  /// `POST /auth/change-password`, then — on success — clears the flag on
  /// the in-memory user *and* rewrites the cached user JSON in secure
  /// storage (same mechanism `login`/`bootstrap` use) so a cold restart
  /// doesn't resurrect the forced-change screen. No fresh login required:
  /// `_AuthGate` is a `Consumer<AuthProvider>`, so notifyListeners() alone
  /// is enough for it to fall through to Home/SeniorHome.
  Future<bool> changePassword(String currentPassword, String newPassword) async {
    isBusy = true;
    error = null;
    notifyListeners();
    try {
      await _api.changePassword(currentPassword: currentPassword, newPassword: newPassword);
      if (user != null) {
        user = user!.copyWith(mustChangePassword: false);
        await _tokenStorage.saveUser(user!.toJson());
      }
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

  /// Re-fetches `GET /auth/me` and refreshes the in-memory + cached user —
  /// used after EditProfileScreen saves changes so `missingProfileFields`
  /// (and anything else `/auth/me` reports) reflects the update without
  /// requiring a fresh login. Silently does nothing on failure: this is a
  /// best-effort refresh, not something worth surfacing an error for (the
  /// profile edit itself already succeeded by the time this is called).
  Future<void> refreshUser() async {
    try {
      final json = await _api.getMe();
      user = MBUser.fromJson(json);
      await _tokenStorage.saveUser(json);
      notifyListeners();
    } catch (_) {
      // Best-effort only — see doc comment above.
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
