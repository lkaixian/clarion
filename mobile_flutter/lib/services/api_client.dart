import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:dio/io.dart';

import '../config/app_config.dart';
import '../models/booking.dart';
import '../models/emergency_card.dart';
import '../models/patient.dart';
import '../models/audit_log_entry.dart';
import '../models/queue_ticket.dart';
import '../models/server_appointment.dart';
import 'api_exception.dart';
import 'token_storage.dart';

/// Thin, typed wrapper around the CLARION FastAPI backend.
///
/// The base URL is resolved fresh on every request from [AppConfig] (rather
/// than baked into the Dio instance at construction time) so that changing
/// it at runtime via the Settings screen takes effect immediately without
/// recreating the client. The bearer token is attached automatically via an
/// interceptor that reads it from secure storage.
class ApiClient {
  ApiClient({required this._config, required this._tokenStorage})
      : _dio = Dio(BaseOptions(
          connectTimeout: const Duration(seconds: 12),
          receiveTimeout: const Duration(seconds: 12),
        )) {
    final adapter = _dio.httpClientAdapter;
    if (adapter is IOHttpClientAdapter) {
      adapter.createHttpClient = () {
        final client = HttpClient();
        // ponytail: SHA-1 *leaf-cert* pin via dart:io's built-in
        // X509Certificate.sha1 -- no crypto package needed. Two known
        // ceilings, both accepted for now: (1) pins the leaf, not the
        // SPKI/CA, so ops must roll the dart-define on every cert
        // renewal -- upgrade to SPKI SHA-256 pinning if that becomes
        // painful; (2) badCertificateCallback only fires when the OS
        // does NOT already trust the signing CA, which is true for
        // CLARION's private CAMPUS-CA today but would silently stop being
        // enforced if the deployment ever switched to a publicly-trusted
        // CA. Only pins the compile-time production endpoint -- a
        // Settings-screen tunnel/dev override (see AppConfig) is
        // deliberately never pinned. NOTE: badCertificateCallback fires
        // for ANY validation failure (expired/revoked/hostname-mismatch,
        // not just untrusted-CA) -- a pin match overrides all of those at
        // once. Accepted: leaf-pinning already requires the attacker to
        // also hold the matching private key.
        client.badCertificateCallback = (cert, host, port) {
          // If a release build forgets --dart-define=PINNED_CERT_SHA1,
          // pinning silently no-ops (falls back to default OS trust only)
          // -- assert it's set in the release checklist, not here.
          final pins = _config.pinnedCertSha1Fingerprints;
          if (pins.isEmpty || _config.isOverridden) return false;
          final fingerprint =
              cert.sha1.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
          return pins.contains(fingerprint.toLowerCase());
        };
        return client;
      };
    }
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          options.baseUrl = _config.baseUrl;
          final token = await _tokenStorage.readToken();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
        onError: (error, handler) async {
          // The backend now actually revokes previously-issued JWTs (e.g. on
          // a password change from another device/console), so a 401 here
          // can mean "this token is dead", not just "you never logged in".
          //
          // P2.5 (Security Audit M4): access tokens are now short-lived (15
          // minutes, not 8 hours), so a 401-because-expired is now a
          // routine, frequent event rather than an edge case — before
          // treating it as a dead session, try ONCE to silently recover via
          // the stored refresh token (mirrors web/src/api/client.js's
          // interceptor). Only on that failing does `onUnauthorized` fire
          // (lets whoever owns the session -- AuthProvider, wired up in
          // main.dart -- clear local state and bounce back to the login
          // screen). `handler.next(error)` / `handler.resolve(response)`
          // below still runs so the original caller's existing try/catch
          // and ApiException.fromDioException mapping keeps working
          // exactly as it did before any of this was added.
          //
          // Excluded on purpose: `/auth/login` (a 401 there is a normal
          // "wrong password" outcome the login screen already handles
          // itself — treating it as "session expired" would be wrong and
          // would fight with LoginScreen's own error display), `/auth/refresh`
          // itself (a 401 there must fall straight through, not try to
          // refresh its own way out of failing), the two password-reset-OTP
          // endpoints, and the four self-registration endpoints — all
          // public/unauthenticated and can 401 for reasons (bad/expired
          // OTP, rate limiting) that have nothing to do with an existing
          // session (there is no session yet during self-registration at
          // all).
          final path = error.requestOptions.path;
          const exemptPaths = {
            '/auth/login',
            '/auth/refresh',
            '/auth/request-password-reset-otp',
            '/auth/reset-password-with-otp',
            '/auth/self-register/start',
            '/auth/self-register/verify-otp',
            '/auth/self-register/verify-photos',
            '/auth/self-register/complete',
          };
          final alreadyRetried = error.requestOptions.extra['retriedAfterRefresh'] == true;

          if (error.response?.statusCode == 401 && !exemptPaths.contains(path)) {
            if (!alreadyRetried) {
              final newAccessToken = await _attemptTokenRefresh();
              if (newAccessToken != null) {
                final retryOptions = error.requestOptions
                  ..headers['Authorization'] = 'Bearer $newAccessToken'
                  ..extra = {...error.requestOptions.extra, 'retriedAfterRefresh': true};
                try {
                  final response = await _dio.fetch(retryOptions);
                  return handler.resolve(response);
                } on DioException {
                  // Retried request itself failed for some other reason --
                  // fall through to onUnauthorized below, same as a
                  // refresh failure.
                }
              }
            }
            onUnauthorized?.call();
          }
          handler.next(error);
        },
      ),
    );
  }

  final AppConfig _config;
  final TokenStorage _tokenStorage;
  final Dio _dio;

  /// Fired whenever any non-exempt request comes back 401, meaning the
  /// current session's token is no longer valid (expired, or revoked
  /// server-side by a password change elsewhere). Left unset (no-op) by
  /// default to avoid a circular constructor dependency — `ApiClient` is
  /// built before `AuthProvider` in main.dart, so it can't take an
  /// `AuthProvider` in its own constructor. main.dart wires this up as
  /// `apiClient.onUnauthorized = () => authProvider.forceLogout();` once
  /// both exist.
  void Function()? onUnauthorized;

  // P2.5 (Security Audit M4): single-flight refresh, same reasoning as
  // web/src/api/client.js's `refreshInFlight` -- if several requests 401
  // around the same moment, they must all await the SAME refresh call
  // rather than each independently racing the backend's single-use
  // rotation (a second caller presenting an already-rotated-away token
  // would be treated as a reuse/compromise signal by
  // auth.rotate_refresh_token, revoking the whole session instead of just
  // refreshing it).
  Future<String?>? _refreshInFlight;

  Future<String?> _attemptTokenRefresh() {
    return _refreshInFlight ??= _doTokenRefresh().whenComplete(() => _refreshInFlight = null);
  }

  Future<String?> _doTokenRefresh() async {
    final refreshToken = await _tokenStorage.readRefreshToken();
    if (refreshToken == null || refreshToken.isEmpty) return null;
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/refresh',
        data: {'refresh_token': refreshToken},
      );
      final data = response.data!;
      final newAccessToken = data['access_token'] as String;
      final newRefreshToken = data['refresh_token'] as String?;
      final userJson = data['user'] as Map<String, dynamic>?;
      await _tokenStorage.saveToken(newAccessToken);
      if (newRefreshToken != null && newRefreshToken.isNotEmpty) {
        await _tokenStorage.saveRefreshToken(newRefreshToken);
      }
      if (userJson != null) {
        await _tokenStorage.saveUser(userJson);
      }
      return newAccessToken;
    } on DioException {
      return null;
    }
  }

  /// `POST /auth/logout` — best-effort, revokes the stored refresh token
  /// server-side (Security Audit M4 -- there was no real server-side
  /// logout before P2.5). Never throws: callers (AuthProvider.logout /
  /// forceLogout) must clear local state unconditionally regardless of
  /// whether this network call succeeds.
  Future<void> logout() async {
    final refreshToken = await _tokenStorage.readRefreshToken();
    if (refreshToken == null || refreshToken.isEmpty) return;
    try {
      await _dio.post('/auth/logout', data: {'refresh_token': refreshToken});
    } on DioException {
      // Best-effort -- see doc comment above.
    }
  }

  Future<T> _guard<T>(Future<T> Function() body) async {
    try {
      return await body();
    } on DioException catch (e) {
      throw ApiException.fromDioException(e);
    }
  }

  /// `GET /app/version` -- public update check (see services/update_check.dart).
  Future<Map<String, dynamic>> getAppVersion() {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/app/version');
      return response.data!;
    });
  }

  /// `POST /auth/login` — form-urlencoded (OAuth2PasswordRequestForm style).
  /// Returns the raw decoded JSON: `{access_token, token_type, user: {...}}`.
  Future<Map<String, dynamic>> login(String email, String password) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/login',
        data: {'username': email, 'password': password},
        options: Options(contentType: Headers.formUrlEncodedContentType),
      );
      return response.data!;
    });
  }

  /// `POST /auth/mfa/verify` -- second step of a login that answered with an
  /// MFA challenge. Same response shape as [login] on success.
  Future<Map<String, dynamic>> verifyMfa(String mfaToken, String code) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/mfa/verify',
        data: {'mfa_token': mfaToken, 'code': code},
      );
      return response.data!;
    });
  }

  /// `POST /auth/request-password-reset-otp` — public (no bearer token
  /// needed, and none is sent even if one happens to be cached — this is
  /// reachable straight from the pre-login LoginScreen). Step 1 of the
  /// two-step, DOB-free self-service reset flow: the backend emails a
  /// 6-digit OTP to whatever email is on file for this NRIC, if any.
  /// `nationalId` is passed through exactly as typed (with or without
  /// dashes) — the backend normalizes it, so this deliberately does no
  /// client-side dash stripping/validation. The response is always the
  /// same generic shape regardless of whether the NRIC/email actually
  /// exists (anti-enumeration by design) — callers should treat any
  /// success here as "if this account has an email on file, a code was
  /// sent", not as confirmation the NRIC is real. May also throw
  /// [ApiException] for a rate-limit error if requested too often; callers
  /// should just surface [ApiException.message] generically.
  Future<void> requestPasswordResetOtp({required String nationalId}) {
    return _guard(() async {
      await _dio.post<Map<String, dynamic>>(
        '/auth/request-password-reset-otp',
        data: {'national_id': nationalId},
      );
    });
  }

  /// `POST /auth/reset-password-with-otp` — public (no bearer token).
  /// Step 2: verifies `otpCode` against the code most recently requested
  /// for `nationalId`, and if valid, sets `newPassword`. A wrong/expired
  /// code, or too many wrong attempts, surfaces as a generic
  /// [ApiException] with a plain-string message from the backend.
  Future<void> resetPasswordWithOtp({
    required String nationalId,
    required String otpCode,
    required String newPassword,
  }) {
    return _guard(() async {
      await _dio.post<Map<String, dynamic>>(
        '/auth/reset-password-with-otp',
        data: {
          'national_id': nationalId,
          'otp_code': otpCode,
          'new_password': newPassword,
        },
      );
    });
  }

  /// `POST /auth/change-password` — authenticated; the bearer token is
  /// attached automatically by the interceptor set up in the constructor,
  /// same as every other call on this client. Used both for the forced
  /// "must change password" flow after a staff-issued temp password and
  /// (in principle) any future voluntary password change from Settings.
  Future<void> changePassword({
    String? currentPassword,
    required String newPassword,
  }) {
    return _guard(() async {
      await _dio.post<Map<String, dynamic>>(
        '/auth/change-password',
        data: {
          'current_password': ?currentPassword,
          'new_password': newPassword,
        },
      );
    });
  }

  Future<Map<String, dynamic>> getMe() {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/auth/me');
      return response.data!;
    });
  }

  Future<Patient> getPatient(String patientId) {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/patients/$patientId');
      return Patient.fromJson(response.data!);
    });
  }

  /// `PATCH /patients/{patient_id}/profile` — authenticated; a patient may
  /// only edit their own record (enforced server-side). Accepts any subset
  /// of the contact/profile fields below — full name, date of birth, and
  /// NRIC are deliberately NOT accepted here (immutable via self-service,
  /// see EditProfileScreen's read-only fields). Only the parameters that
  /// are non-null are sent, so callers can update just one field at a time
  /// if they want; pass an empty string (not null) to explicitly clear a
  /// field — EXCEPT `email`, which the backend validates as `EmailStr`
  /// (see backend/app/schemas.py::PatientProfileUpdate) and therefore
  /// rejects an empty string for with a 422; a blank/empty `email` is
  /// always omitted from the request body here regardless of whether the
  /// caller passed `null` or `''`, since there is no supported way to
  /// clear it back to blank via this endpoint.
  Future<Patient> updatePatientProfile({
    required String patientId,
    String? email,
    String? phone,
    String? emergencyContactName,
    String? emergencyContactPhone,
    String? emergencyContactRelationship,
  }) {
    return _guard(() async {
      final body = <String, dynamic>{
        if (email != null && email.trim().isNotEmpty) 'email': email,
        'phone': ?phone,
        'emergency_contact_name': ?emergencyContactName,
        'emergency_contact_phone': ?emergencyContactPhone,
        'emergency_contact_relationship': ?emergencyContactRelationship,
      };
      final response = await _dio.patch<Map<String, dynamic>>(
        '/patients/$patientId/profile',
        data: body,
      );
      return Patient.fromJson(response.data!);
    });
  }

  /// `GET /ai/summary/{patient_id}` — note: the backend currently restricts
  /// this endpoint to staff roles (admin/clinician/records_officer), so a
  /// patient-role token will get a 403 here. Callers should treat failure as
  /// "no AI brief available" rather than a hard error (see PatientProvider).
  Future<String?> getSummary(String patientId) {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/ai/summary/$patientId');
      return response.data?['handover_brief'] as String?;
    });
  }

  /// `GET /patients/{patient_id}/appointments` — a patient reads only their
  /// own (staff may read any patient's, but that path isn't needed by this
  /// app). Returns clinic-published appointments ordered by `scheduled_at`
  /// ascending, each carrying a server-computed, future-only `reminders`
  /// list (see [ServerAppointment] / [AppointmentReminderInfo] doc
  /// comments for why this app deliberately doesn't reimplement that
  /// offset calculation client-side). Used by
  /// RemindersProvider.syncServerAppointments to (re)schedule local
  /// notifications for these, distinct from the patient's own
  /// device-local, self-added appointment reminders.
  Future<List<ServerAppointment>> getAppointments(String patientId) {
    return _guard(() async {
      final response = await _dio.get<List<dynamic>>('/patients/$patientId/appointments');
      return (response.data ?? [])
          .map((e) => ServerAppointment.fromJson(e as Map<String, dynamic>))
          .toList();
    });
  }

  /// `POST /patients/{patient_id}/appointments/{appointment_id}
  /// /reschedule-requests` — patient JWT, own record only. `reasonCode` must
  /// be one of `schedule_conflict` | `unwell_or_cannot_travel` |
  /// `transport_issue` | `other` (the backend 422s `other` without a
  /// non-empty `reasonOther`). Fails with a 400 [ApiException] if a pending
  /// request already exists for this appointment, or the appointment isn't
  /// `status == "scheduled"` — callers should surface [ApiException.message]
  /// as-is, it's already a user-facing string from the backend.
  Future<RescheduleRequestInfo> requestAppointmentReschedule({
    required String patientId,
    required String appointmentId,
    required String reasonCode,
    String? reasonOther,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/patients/$patientId/appointments/$appointmentId/reschedule-requests',
        data: {
          'reason_code': reasonCode,
          if (reasonOther != null && reasonOther.trim().isNotEmpty) 'reason_other': reasonOther.trim(),
        },
      );
      return RescheduleRequestInfo.fromJson(response.data!);
    });
  }

  /// `GET /patients/appointment-slots` — P3.10. Bookable
  /// slots for one Malaysia-local calendar `date` ("YYYY-MM-DD"), already
  /// excluding anything already booked. `department`/`clinicianId` narrow
  /// the search; omitting `clinicianId` returns the union of every matching
  /// clinician's free slots (see backend/app/routers/patients.py::
  /// list_appointment_slots).
  Future<List<AppointmentSlot>> getAppointmentSlots({
    required String facilityName,
    required String date,
    String? department,
    String? clinicianId,
  }) {
    return _guard(() async {
      final response = await _dio.get<List<dynamic>>(
        '/patients/appointment-slots',
        queryParameters: {
          'facility_name': facilityName,
          'date': date,
          'department': ?department,
          'clinician_id': ?clinicianId,
        },
      );
      return (response.data ?? [])
          .map((e) => AppointmentSlot.fromJson(e as Map<String, dynamic>))
          .toList();
    });
  }

  /// `GET /patients/booking-options` — the department/clinician pickers a
  /// self-booking flow needs for one facility.
  Future<BookingOptions> getBookingOptions(String facilityName) {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>(
        '/patients/booking-options',
        queryParameters: {'facility_name': facilityName},
      );
      return BookingOptions.fromJson(response.data!);
    });
  }

  /// `POST /patients/{patient_id}/appointments/self-book` — patient JWT,
  /// own record only. `scheduledAt` MUST be one of the exact values
  /// [getAppointmentSlots] just returned (copied verbatim, not reformatted)
  /// -- the backend re-validates it's still a real offered slot and 409s
  /// otherwise (someone else took it in the meantime).
  Future<ServerAppointment> selfBookAppointment({
    required String patientId,
    required String facilityName,
    String? department,
    String? clinicianId,
    required DateTime scheduledAt,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/patients/$patientId/appointments/self-book',
        data: {
          'facility_name': facilityName,
          'department': ?department,
          'clinician_id': ?clinicianId,
          'scheduled_at': scheduledAt.toUtc().toIso8601String(),
        },
      );
      return ServerAppointment.fromJson(response.data!);
    });
  }

  /// `GET /patients/announcements` — P3.10. Already filtered
  /// server-side to currently-live ones; no client-side expiry check needed.
  Future<List<Announcement>> getAnnouncements(String facilityName) {
    return _guard(() async {
      final response = await _dio.get<List<dynamic>>(
        '/patients/announcements',
        queryParameters: {'facility_name': facilityName},
      );
      return (response.data ?? [])
          .map((e) => Announcement.fromJson(e as Map<String, dynamic>))
          .toList();
    });
  }

  /// `GET /patients/{patient_id}/encounters/{encounter_id}/visit-summary.pdf`
  /// — P3.10, raw PDF bytes for the caller to write to a temp
  /// file and hand to [Share.shareXFiles] (see BookAppointmentScreen's
  /// sibling usage in home_screen.dart's encounter card) -- the endpoint is
  /// Bearer-authed like everything else here, so a plain url_launcher can't
  /// fetch it directly.
  Future<List<int>> getVisitSummaryPdfBytes({
    required String patientId,
    required String encounterId,
  }) {
    return _guard(() async {
      final response = await _dio.get<List<int>>(
        '/patients/$patientId/encounters/$encounterId/visit-summary.pdf',
        options: Options(responseType: ResponseType.bytes),
      );
      return response.data!;
    });
  }

  Future<List<AuditLogEntry>> getAuditLog(String patientId) {
    return _guard(() async {
      final response = await _dio.get<List<dynamic>>('/patients/$patientId/audit-log');
      return (response.data ?? [])
          .map((e) => AuditLogEntry.fromJson(e as Map<String, dynamic>))
          .toList();
    });
  }

  Future<EmergencyCard> issueEmergencyCard({
    required String patientId,
    required List<String> scope,
    int validMinutes = 43200,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/emergency/issue',
        data: {
          'patient_id': patientId,
          'scope': scope,
          'valid_minutes': validMinutes,
        },
      );
      return EmergencyCard.fromJson(response.data!);
    });
  }

  Future<void> revokeEmergencyCard(String cardReference) {
    return _guard(() async {
      await _dio.post('/emergency/revoke/$cardReference');
    });
  }

  /// `GET /emergency/current/{patient_id}` — read-only, no side effects.
  /// Lets a viewer that *didn't* itself issue the card (this device after
  /// a fresh launch, or after a different device/the web console issued
  /// one) find out whether a QR card is currently live and render it,
  /// without needing to click "Issue" again. Returns `null` when there is
  /// no active card. This is the fix for "a card issued on the web
  /// console / another device never shows up in the app" — see
  /// PatientProvider.refreshCurrentCard, which polls this.
  Future<EmergencyCard?> getCurrentEmergencyCard(String patientId) {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/emergency/current/$patientId');
      final data = response.data!;
      if (data['active'] != true) return null;
      return EmergencyCard.fromJson(data);
    });
  }

  /// `POST /emergency/scan` — no auth required. Used by the QR/manual
  /// responder scanner.
  Future<Map<String, dynamic>> scanEmergencyCard({
    required String cardReference,
    String? responderName,
    String? responderOrg,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/emergency/scan',
        data: {
          'card_reference': cardReference,
          if (responderName != null && responderName.isNotEmpty) 'responder_name': responderName,
          if (responderOrg != null && responderOrg.isNotEmpty) 'responder_org': responderOrg,
        },
      );
      return response.data!;
    });
  }

  /// `POST /emergency/nfc/scan` — no auth required. Used by the NFC-tap
  /// responder scanner (physical card, e.g. for a senior citizen without a
  /// smartphone).
  ///
  /// [timeout] caps the WHOLE request (connect + response). The tap-to-read
  /// flow passes a short one when the tag itself carries offline data, so a
  /// dead network falls back to the on-tag record in ~1.5 s instead of the
  /// client's default 12 s. A cancelled call surfaces as an [ApiException]
  /// with `statusCode == null`, exactly like any other no-response failure.
  Future<Map<String, dynamic>> scanNfcCard({
    required String nfcUid,
    String? responderName,
    String? responderOrg,
    Duration? timeout,
  }) {
    return _guard(() async {
      final cancel = CancelToken();
      final timer = timeout == null ? null : Timer(timeout, () => cancel.cancel('scan timeout'));
      try {
        final response = await _dio.post<Map<String, dynamic>>(
          '/emergency/nfc/scan',
          data: {
            'nfc_uid': nfcUid,
            if (responderName != null && responderName.isNotEmpty) 'responder_name': responderName,
            if (responderOrg != null && responderOrg.isNotEmpty) 'responder_org': responderOrg,
          },
          cancelToken: cancel,
        );
        return response.data!;
      } finally {
        timer?.cancel();
      }
    });
  }

  /// `GET /emergency/tag-keys` -- staff only. `{key_id: base64 key}` the
  /// device caches to open encrypted NFC tags with no network.
  Future<Map<String, String>> getTagKeys() {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/emergency/tag-keys');
      return (response.data!['keys'] as Map<String, dynamic>).cast<String, String>();
    });
  }

  /// `POST /emergency/offline-reads` -- uploads this user's hash-chained log
  /// of reads done with no network (see OfflineReadLog).
  Future<Map<String, dynamic>> uploadOfflineReads(String deviceId, List<Map<String, dynamic>> entries) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/emergency/offline-reads',
        data: {'device_id': deviceId, 'entries': entries},
      );
      return response.data ?? const <String, dynamic>{};
    });
  }

  /// `GET /emergency/nfc/{patient_id}` — a patient can view (read-only)
  /// which physical NFC cards staff have registered against their own
  /// record.
  Future<List<Map<String, dynamic>>> listNfcCards(String patientId) {
    return _guard(() async {
      final response = await _dio.get<List<dynamic>>('/emergency/nfc/$patientId');
      return (response.data ?? []).cast<Map<String, dynamic>>();
    });
  }

  /// `GET /reception/queue/status/{patient_id}` — a patient reads only their
  /// own (enforced server-side; staff may read any patient's, but that path
  /// isn't needed by this app). Reflects whether the patient has an active
  /// (`waiting`/`called`) reception queue ticket checked in today, plus the
  /// facility's current `now_serving` number and `people_ahead` count. See
  /// [QueueStatus.fromJson] for the `{"active": false}` "nothing to show"
  /// shape, mirroring [getCurrentEmergencyCard]'s equivalent convention.
  Future<QueueStatus> getQueueStatus(String patientId) {
    return _guard(() async {
      final response = await _dio.get<Map<String, dynamic>>('/reception/queue/status/$patientId');
      return QueueStatus.fromJson(response.data!);
    });
  }

  /// `POST /reception/self-checkin` — patient JWT. The QR a patient scans at
  /// a reception self-check-in station encodes `CLARION-STATION:<token>`
  /// (see ScanCheckinScreen._onQrDetect, which strips that prefix before
  /// calling this — mirrors how EmergencyScannerScreen strips
  /// `CLARION-EMERGENCY:`). Response shape is `{ticket: {...QueueTicketOut
  /// fields...}, patient_full_name, patient_date_of_birth}`; this app
  /// already knows the caller's own name/DOB, so only the [QueueTicket] is
  /// returned here — reusing the exact same model
  /// [getQueueStatus]/[QueueStatusScreen] already parse rather than
  /// inventing a separate response shape. A 404 means the station code is
  /// expired/revoked/unknown; a 403 would mean this account isn't a patient
  /// (shouldn't normally happen — only patients use this app) — both
  /// surface as the usual [ApiException] with the backend's message.
  Future<QueueTicket> selfCheckin({required String stationToken, String? reason}) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/reception/self-checkin',
        data: {
          'station_token': stationToken,
          if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim(),
        },
      );
      return QueueTicket.fromJson(response.data!['ticket'] as Map<String, dynamic>);
    });
  }

  // ---------------------------------------------------------------------
  // Self-service registration (NRIC-OCR identity verification)
  //
  // Today only staff can create a patient login, in person, via the web
  // console. This four-step flow lets a patient create their own account:
  // (1) submit their details, (2) verify an emailed OTP, (3) photograph
  // both sides of their physical NRIC for the backend to OCR and
  // cross-check against the existing hospital record (never client-side —
  // this app is purely capture-and-upload for the photo steps, see
  // SelfRegisterScreen's doc comment), (4) set a password. All four calls
  // are public (no bearer token) — there is no session yet.
  // ---------------------------------------------------------------------

  /// `POST /auth/self-register/start`. Success:
  /// `{"status": "ok", "detail": "...", "next_step": "verify_otp"}`.
  /// Failures (NRIC not found / account already exists / details don't
  /// match / rate limited) surface as [ApiException] per the usual
  /// pattern; callers should just display [ApiException.message].
  Future<Map<String, dynamic>> selfRegisterStart({
    required String nationalId,
    required String fullName,
    required String email,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/self-register/start',
        data: {
          'national_id': nationalId,
          'full_name': fullName,
          'email': email,
        },
      );
      return response.data!;
    });
  }

  /// `POST /auth/self-register/verify-otp`. Success:
  /// `{"status": "ok", "detail": "...", "next_step": "verify_photos",
  /// "photo_attempts_remaining": 5}`.
  Future<Map<String, dynamic>> selfRegisterVerifyOtp({
    required String nationalId,
    required String otpCode,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/self-register/verify-otp',
        data: {'national_id': nationalId, 'otp_code': otpCode},
      );
      return response.data!;
    });
  }

  /// `POST /auth/self-register/verify-photos` — multipart/form-data (the
  /// first multipart call on this client; mirrors the web console's
  /// `digitiseDocument` `Content-Type: multipart/form-data` idiom, see
  /// `web/src/api/client.js`). `frontImagePath`/`backImagePath` are local
  /// file paths from `image_picker`'s `XFile.path`.
  ///
  /// Success: `{"status": "verified", "detail": "...", "next_step":
  /// "complete"}`.
  ///
  /// Failure with attempts remaining surfaces as a 400 [ApiException]
  /// whose [ApiException.data] carries `next_step: "verify_photos"` and
  /// `photo_attempts_remaining: N` — callers should let the user retake
  /// photos and show the remaining-attempts count.
  ///
  /// Failure on the 5th (final) attempt surfaces as a 403 [ApiException]
  /// whose [ApiException.data] carries `next_step:
  /// "manual_registration_required"` — this is terminal; callers must not
  /// offer a further retry (see SelfRegisterScreen).
  Future<Map<String, dynamic>> selfRegisterVerifyPhotos({
    required String nationalId,
    required String frontImagePath,
    required String backImagePath,
  }) {
    return _guard(() async {
      final formData = FormData.fromMap({
        'national_id': nationalId,
        'front_image': await MultipartFile.fromFile(
          frontImagePath,
          filename: 'nric_front.jpg',
        ),
        'back_image': await MultipartFile.fromFile(
          backImagePath,
          filename: 'nric_back.jpg',
        ),
      });
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/self-register/verify-photos',
        data: formData,
        options: Options(contentType: Headers.multipartFormDataContentType),
      );
      return response.data!;
    });
  }

  /// `POST /auth/self-register/complete`. Success returns the SAME shape
  /// as `POST /auth/login` (`{access_token, token_type, user}`) — callers
  /// should treat it exactly like a login response (see
  /// `AuthProvider.completeWithLoginResponse`), not bounce the user back
  /// to the login screen.
  Future<Map<String, dynamic>> selfRegisterComplete({
    required String nationalId,
    required String newPassword,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/auth/self-register/complete',
        data: {'national_id': nationalId, 'new_password': newPassword},
      );
      return response.data!;
    });
  }
}
