import 'package:dio/dio.dart';

import '../config/app_config.dart';
import '../models/emergency_card.dart';
import '../models/patient.dart';
import '../models/audit_log_entry.dart';
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
      ),
    );
  }

  final AppConfig _config;
  final TokenStorage _tokenStorage;
  final Dio _dio;

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

  /// `POST /auth/forgot-password` — public (no bearer token needed, and
  /// none is sent even if one happens to be cached — this is reachable
  /// straight from the pre-login LoginScreen). Patient-only, DOB-based
  /// reset: the backend verifies `national_id` + `date_of_birth` match a
  /// patient record before honouring `new_password`. `dateOfBirth` must be
  /// an ISO date string ("yyyy-MM-dd"), same format Patient.dateOfBirth
  /// already uses.
  Future<void> forgotPassword({
    required String nationalId,
    required String dateOfBirth,
    required String newPassword,
  }) {
    return _guard(() async {
      await _dio.post<Map<String, dynamic>>(
        '/auth/forgot-password',
        data: {
          'national_id': nationalId,
          'date_of_birth': dateOfBirth,
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
