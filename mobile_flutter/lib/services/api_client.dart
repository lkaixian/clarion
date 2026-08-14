import 'package:dio/dio.dart';

import '../config/app_config.dart';
import '../models/emergency_card.dart';
import '../models/patient.dart';
import '../models/audit_log_entry.dart';
import '../models/server_appointment.dart';
import 'api_exception.dart';
import 'token_storage.dart';

/// Thin, typed wrapper around the MediBridge FastAPI backend.
///
/// The base URL is resolved fresh on every request from [AppConfig] (rather
/// than baked into the Dio instance at construction time) so that changing
/// it at runtime via the Settings screen takes effect immediately without
/// recreating the client. The bearer token is attached automatically via an
/// interceptor that reads it from secure storage.
class ApiClient {
  ApiClient({required AppConfig config, required TokenStorage tokenStorage})
      : _config = config,
        _tokenStorage = tokenStorage,
        _dio = Dio(BaseOptions(
          connectTimeout: const Duration(seconds: 12),
          receiveTimeout: const Duration(seconds: 12),
        )) {
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
        onError: (error, handler) {
          // The backend now actually revokes previously-issued JWTs (e.g. on
          // a password change from another device/console), so a 401 here
          // can mean "this token is dead", not just "you never logged in".
          // `onUnauthorized` lets whoever owns the session (AuthProvider,
          // wired up in main.dart) react by clearing local state and
          // bouncing back to the login screen. This is deliberately just an
          // extra side effect — `handler.next(error)` below still runs
          // unconditionally so the original caller's existing try/catch and
          // ApiException.fromDioException mapping keeps working exactly as
          // it did before this was added.
          //
          // Excluded on purpose: `/auth/login` (a 401 there is a normal
          // "wrong password" outcome the login screen already handles
          // itself — treating it as "session expired" would be wrong and
          // would fight with LoginScreen's own error display), and the two
          // password-reset-OTP endpoints, which are public/unauthenticated
          // and can 401 for reasons (bad/expired OTP, rate limiting) that
          // have nothing to do with an existing session.
          final path = error.requestOptions.path;
          const exemptPaths = {
            '/auth/login',
            '/auth/request-password-reset-otp',
            '/auth/reset-password-with-otp',
          };
          if (error.response?.statusCode == 401 && !exemptPaths.contains(path)) {
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

  Future<T> _guard<T>(Future<T> Function() body) async {
    try {
      return await body();
    } on DioException catch (e) {
      throw ApiException.fromDioException(e);
    }
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
    required String currentPassword,
    required String newPassword,
  }) {
    return _guard(() async {
      await _dio.post<Map<String, dynamic>>(
        '/auth/change-password',
        data: {
          'current_password': currentPassword,
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
        if (phone != null) 'phone': phone,
        if (emergencyContactName != null) 'emergency_contact_name': emergencyContactName,
        if (emergencyContactPhone != null) 'emergency_contact_phone': emergencyContactPhone,
        if (emergencyContactRelationship != null)
          'emergency_contact_relationship': emergencyContactRelationship,
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
  Future<Map<String, dynamic>> scanNfcCard({
    required String nfcUid,
    String? responderName,
    String? responderOrg,
  }) {
    return _guard(() async {
      final response = await _dio.post<Map<String, dynamic>>(
        '/emergency/nfc/scan',
        data: {
          'nfc_uid': nfcUid,
          if (responderName != null && responderName.isNotEmpty) 'responder_name': responderName,
          if (responderOrg != null && responderOrg.isNotEmpty) 'responder_org': responderOrg,
        },
      );
      return response.data!;
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
}
