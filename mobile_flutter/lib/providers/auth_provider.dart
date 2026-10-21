import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/user.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/offline_read_log.dart';
import '../services/token_storage.dart';

enum AuthStatus { unknown, authenticated, unauthenticated }

/// Owns the login session: current user, restoring it on cold start, and
/// the persisted "prefer Senior Citizen Mode" flag used to route straight
/// into the simplified hub after login.
class AuthProvider extends ChangeNotifier {
  AuthProvider({required this._api, required this._tokenStorage});

  final ApiClient _api;
  final TokenStorage _tokenStorage;

  /// Cached tag data keys + this device's hash-chained offline-read log.
  /// Keys exist only while a non-patient user is signed in.
  final OfflineReadLog offlineLog = OfflineReadLog();

  static const _seniorPrefKey = 'mb_prefers_senior_mode';
  static const _seniorIsDarkKey = 'mb_senior_is_dark';

  AuthStatus status = AuthStatus.unknown;
  MBUser? user;
  bool isBusy = false;
  String? error;
  bool prefersSeniorMode = false;

  /// Which of [SeniorColors] (dark, default) vs [SeniorColorsLight] the
  /// Senior Mode screens should use — persisted the same way as
  /// [prefersSeniorMode]. Defaults to `true` (dark) so existing users see
  /// no visual change until they explicitly toggle it via the light/dark
  /// button on SeniorHomeScreen.
  bool seniorIsDark = true;

  /// Set by [forceLogout] (never by the deliberate [logout]) so LoginScreen
  /// can show a one-time "you were signed out" message instead of silently
  /// dumping the user back on the login form with no explanation. LoginScreen
  /// reads this once on its first frame and immediately clears it via
  /// [acknowledgeSessionExpired] — it is not meant to persist across a
  /// subsequent login/forceLogout cycle beyond that single display.
  bool sessionExpired = false;

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
    seniorIsDark = prefs.getBool(_seniorIsDarkKey) ?? true;

    final token = await _tokenStorage.readToken();
    final userJson = await _tokenStorage.readUser();
    if (token != null && userJson != null) {
      user = MBUser.fromJson(userJson);
      status = AuthStatus.authenticated;
      syncOfflineTagData();
    } else {
      status = AuthStatus.unauthenticated;
    }
    notifyListeners();
  }

  /// Best-effort, fire-and-forget: refresh the cached tag data keys and
  /// upload this user's pending offline reads. Staff-side roles only -- the
  /// backend refuses keys to a patient account, and a forced password
  /// change has to finish first.
  void syncOfflineTagData() {
    final u = user;
    if (u == null || u.role == 'patient' || u.mustChangePassword) return;
    unawaited(offlineLog.sync(_api, u.id));
  }

  /// Set between a password step that needs a second factor and the code
  /// step. While non-null the login screen shows the code form.
  String? mfaToken;
  bool get awaitingMfa => mfaToken != null;

  /// What the code step may offer. `mfaAuthenticatorOk` is false when the
  /// account has no authenticator yet (the email code is then the only way).
  bool mfaAuthenticatorOk = true;
  bool mfaEmailAvailable = false;
  String? mfaEmailHint;

  /// True once a code was emailed: the next [verifyMfa] checks that code.
  bool mfaEmailSent = false;

  /// The last submitted code was refused (as opposed to a network/lockout
  /// problem): the screen shows the "codes change every 30 seconds" hint.
  bool codeRejected = false;

  void _resetMfa() {
    mfaToken = null;
    mfaAuthenticatorOk = true;
    mfaEmailAvailable = false;
    mfaEmailHint = null;
    mfaEmailSent = false;
    codeRejected = false;
  }

  void cancelMfa() {
    _resetMfa();
    error = null;
    notifyListeners();
  }

  /// Back to the authenticator-app code box after asking for an email code.
  void useAuthenticator() {
    mfaEmailSent = false;
    codeRejected = false;
    error = null;
    notifyListeners();
  }

  /// Emails a sign-in code for the pending challenge.
  Future<bool> sendMfaEmail() async {
    final token = mfaToken;
    if (token == null || isBusy) return false;
    isBusy = true;
    error = null;
    codeRejected = false;
    notifyListeners();
    try {
      final data = await _api.sendMfaEmailCode(token);
      mfaEmailHint = (data['email_hint'] as String?) ?? mfaEmailHint;
      mfaEmailSent = true;
      return true;
    } on ApiException catch (e) {
      error = e.message;
      if (e.statusCode == 401) _resetMfa();
      return false;
    } catch (_) {
      error = 'Could not send the code. Check your connection and try again.';
      return false;
    } finally {
      isBusy = false;
      notifyListeners();
    }
  }

  /// Second step: exchange the challenge token + a TOTP/recovery code for a
  /// session. A failed code keeps the challenge so the user can retry; an
  /// expired challenge (401 "start again") drops back to the password step.
  Future<bool> verifyMfa(String code) async {
    final token = mfaToken;
    if (token == null) return false;
    isBusy = true;
    error = null;
    codeRejected = false;
    notifyListeners();
    try {
      final data = mfaEmailSent
          ? await _api.verifyMfaEmail(token, code)
          : await _api.verifyMfa(token, code);
      await _adoptSession(data);
      _resetMfa();
      return true;
    } on ApiException catch (e) {
      error = e.message;
      if (e.statusCode == 401 && e.message.toLowerCase().contains('start again')) {
        _resetMfa();
      } else {
        codeRejected = e.statusCode == 401;
      }
      return false;
    } catch (e) {
      error = 'Unexpected error: $e';
      return false;
    } finally {
      isBusy = false;
      notifyListeners();
    }
  }

  Future<void> _adoptSession(Map<String, dynamic> data) async {
    final token = data['access_token'] as String;
    final userJson = data['user'] as Map<String, dynamic>;
    await _tokenStorage.saveToken(token);
    final refreshToken = data['refresh_token'] as String?;
    if (refreshToken != null && refreshToken.isNotEmpty) {
      await _tokenStorage.saveRefreshToken(refreshToken);
    }
    await _tokenStorage.saveUser(userJson);
    await _tokenStorage.saveActivePatient(null); // a fresh login starts on its own profile
    user = MBUser.fromJson(userJson);
    status = AuthStatus.authenticated;
    syncOfflineTagData();
  }

  Future<bool> login(String email, String password) async {
    isBusy = true;
    error = null;
    _resetMfa();
    notifyListeners();
    try {
      final data = await _api.login(email, password);
      if (data['mfa_required'] == true) {
        final enrol = data['mfa_enrol'] == true;
        final emailOk = data['email_available'] == true;
        if (enrol && !emailOk) {
          // Authenticator enrolment (QR + recovery codes) lives in the web console.
          error = 'Your role requires two-step verification. Set it up in the '
              'CLARION web console first, then sign in here.';
          return false;
        }
        mfaToken = data['mfa_token'] as String?;
        mfaAuthenticatorOk = !enrol;
        mfaEmailAvailable = emailOk;
        mfaEmailHint = data['email_hint'] as String?;
        return false;
      }
      // P2.5 (Security Audit M4): native clients get the refresh token as a
      // plain JSON field (the web console's equivalent is an HttpOnly
      // cookie), stored in the OS keychain like the access token.
      await _adoptSession(data);
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
  Future<bool> changePassword(String newPassword) async {
    isBusy = true;
    error = null;
    notifyListeners();
    try {
      await _api.changePassword(newPassword: newPassword);
      if (user != null) {
        user = user!.copyWith(mustChangePassword: false);
        await _tokenStorage.saveUser(user!.toJson());
        syncOfflineTagData();
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

  /// Same effect as a successful [login], but for a caller that already
  /// has a `POST /auth/login`-shaped response in hand from a *different*
  /// endpoint — currently only `POST /auth/self-register/complete`, which
  /// deliberately returns the identical `{access_token, token_type,
  /// user}` shape so a freshly self-registered patient is signed straight
  /// in, exactly like a normal login, rather than being bounced back to
  /// the login screen to sign in again with the password they just chose.
  /// See SelfRegisterScreen.
  Future<void> completeWithLoginResponse(Map<String, dynamic> data) async {
    final token = data['access_token'] as String;
    final userJson = data['user'] as Map<String, dynamic>;
    await _tokenStorage.saveToken(token);
    final refreshToken = data['refresh_token'] as String?;
    if (refreshToken != null && refreshToken.isNotEmpty) {
      await _tokenStorage.saveRefreshToken(refreshToken);
    }
    await _tokenStorage.saveUser(userJson);
    user = MBUser.fromJson(userJson);
    status = AuthStatus.authenticated;
    error = null;
    notifyListeners();
  }

  /// Set when the link to the profile we were acting for was removed and we
  /// fell back to the own profile; MainShell shows a notice once and clears it.
  bool actingLinkRemoved = false;

  /// `POST /profiles/switch`: replaces the stored access token + user with the
  /// response and remembers the active profile (sent as `act_as` on refresh).
  /// Returns an error message, or null on success. Callers clear cached
  /// patient data afterwards (see switchToProfile in widgets/profile_switcher.dart).
  Future<String?> switchProfile(String patientId) async {
    try {
      final data = await _api.switchProfile(patientId);
      final userJson = data['user'] as Map<String, dynamic>;
      final next = MBUser.fromJson(userJson);
      await _tokenStorage.saveToken(data['access_token'] as String);
      await _tokenStorage.saveUser(userJson);
      await _tokenStorage.saveActivePatient(next.actingFor ? next.patientId : null);
      user = next;
      notifyListeners();
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (e) {
      return 'Unexpected error: $e';
    }
  }

  /// Adopts the user from a token refresh. If we asked to act for a profile
  /// but the server answered with the own profile (it refused `act_as`), drop
  /// the stored active id and flag the notice; the keyed MainShell rebuilds,
  /// clears cached data and shows it once.
  void adoptRefreshedUser(Map<String, dynamic> json, bool askedActAs) {
    final next = MBUser.fromJson(json);
    final flipped = askedActAs && !next.actingFor;
    if (flipped) {
      actingLinkRemoved = true;
      unawaited(_tokenStorage.saveActivePatient(null));
    }
    user = next;
    notifyListeners();
  }

  /// 403 "You can no longer act for this profile": go back to the own profile.
  /// If the explicit switch fails, keep the session and fall back to a plain
  /// refresh (no act_as); only if that fails too, sign out.
  Future<void> handleActingLinkRemoved() async {
    final home = user?.homePatientId;
    if (home == null || !(user?.actingFor ?? false)) return;
    actingLinkRemoved = true; // read by the rebuilt MainShell
    if (await switchProfile(home) == null) return;
    await _tokenStorage.saveActivePatient(null);
    if (await _api.refreshSession()) return;
    actingLinkRemoved = false;
    await forceLogout();
  }

  /// Approve / remove carers (see FamilyScreen).
  Future<void> approveGuardian(String linkId) => _api.approveGuardian(linkId);

  Future<void> logout() async {
    // Best-effort server-side revocation (Security Audit M4) BEFORE
    // clearing local storage -- once cleared, the refresh token this call
    // needs is gone. Never blocks/fails the actual sign-out on a network
    // problem; see ApiClient.logout's own doc comment.
    // Flush this user's queued offline reads first (short cap -- never let a
    // dead network stall sign-out), then drop the offline keys.
    final u = user;
    if (u != null && u.role != 'patient') {
      await offlineLog.sync(_api, u.id).timeout(const Duration(seconds: 3), onTimeout: () {});
    }
    await _api.logout();
    await _tokenStorage.clear();
    await offlineLog.clearKeys();
    user = null;
    status = AuthStatus.unauthenticated;
    notifyListeners();
  }

  /// Same effect as [logout], but for the *involuntary* case: `ApiClient`
  /// calls this (wired up in main.dart as `apiClient.onUnauthorized`)
  /// whenever a request comes back 401 for a token that used to be valid —
  /// most commonly because the backend revoked it after a password change
  /// on another device/console. Sets [sessionExpired] so LoginScreen (which
  /// `_AuthGate` in app.dart already routes to automatically the moment
  /// `status` flips to `unauthenticated` — no manual navigation needed here)
  /// can surface a one-time explanatory message, unlike the deliberate
  /// Sign Out button on Home, which goes through plain [logout] and shows
  /// nothing extra.
  Future<void> forceLogout() async {
    await _api.logout(); // best-effort -- see AuthProvider.logout's doc comment
    await _tokenStorage.clear();
    await offlineLog.clearKeys();
    user = null;
    status = AuthStatus.unauthenticated;
    sessionExpired = true;
    notifyListeners();
  }

  /// Called once by LoginScreen after it has displayed the "you were signed
  /// out" snackbar, so the message doesn't reappear on a later cold start or
  /// after the user logs back in and out again deliberately.
  void acknowledgeSessionExpired() {
    sessionExpired = false;
  }

  Future<void> setPrefersSeniorMode(bool value) async {
    prefersSeniorMode = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_seniorPrefKey, value);
    notifyListeners();
  }

  /// Flips the Senior Mode colour palette between [SeniorColors] (dark) and
  /// [SeniorColorsLight] — see [seniorIsDark] doc comment.
  Future<void> setSeniorIsDark(bool value) async {
    seniorIsDark = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_seniorIsDarkKey, value);
    notifyListeners();
  }
}
