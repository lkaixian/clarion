import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/audit_log_entry.dart';
import '../models/emergency_card.dart';
import '../models/patient.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';

/// Owns the logged-in patient's own record, AI handover brief, the
/// currently-issued emergency card (if any), and the audit log.
class PatientProvider extends ChangeNotifier {
  PatientProvider({required ApiClient api}) : _api = api;

  final ApiClient _api;

  Patient? patient;
  String? handoverBrief;
  bool isLoadingRecord = false;
  String? recordError;

  EmergencyCard? emergencyCard;
  bool isIssuingCard = false;
  bool isLoadingCurrentCard = false;
  String? emergencyError;

  List<AuditLogEntry> auditLog = [];
  bool isLoadingAuditLog = false;

  /// Read-only view of physical NFC cards staff have registered against
  /// this patient (see backend `GET /emergency/nfc/{patient_id}`) — a
  /// patient can't register/revoke these themselves (admin-only, via the
  /// web console), but should be able to see they exist.
  List<Map<String, dynamic>> nfcCards = [];
  bool isLoadingNfcCards = false;

  Timer? _cardPollTimer;

  Future<void> loadRecord(String patientId) async {
    isLoadingRecord = true;
    recordError = null;
    notifyListeners();
    try {
      patient = await _api.getPatient(patientId);
      // The AI summary endpoint is currently staff-only on the backend
      // (admin/clinician/records_officer) — a patient-role token gets a
      // 403. Degrade gracefully rather than surfacing an error, mirroring
      // the reference React Native app's behavior.
      try {
        handoverBrief = await _api.getSummary(patientId);
      } catch (_) {
        handoverBrief = null;
      }
      try {
        nfcCards = await _api.listNfcCards(patientId);
      } catch (_) {
        nfcCards = [];
      }
    } on ApiException catch (e) {
      recordError = e.message;
    } catch (e) {
      recordError = 'Unexpected error: $e';
    } finally {
      isLoadingRecord = false;
      notifyListeners();
    }
  }

  bool isUpdatingProfile = false;
  String? profileUpdateError;

  /// `PATCH /patients/{id}/profile` — see EditProfileScreen. Only the
  /// editable contact fields the endpoint returns are folded back into
  /// [patient] (via [Patient.copyWith]) rather than replacing it outright,
  /// since the PATCH response is PatientOut-shaped and doesn't include
  /// conditions/medications/allergies/encounters — replacing [patient]
  /// wholesale would make those vanish from Home/SeniorHome until the next
  /// full [loadRecord].
  Future<bool> updateProfile({
    required String patientId,
    String? email,
    String? phone,
    String? emergencyContactName,
    String? emergencyContactPhone,
    String? emergencyContactRelationship,
  }) async {
    isUpdatingProfile = true;
    profileUpdateError = null;
    notifyListeners();
    try {
      final updated = await _api.updatePatientProfile(
        patientId: patientId,
        email: email,
        phone: phone,
        emergencyContactName: emergencyContactName,
        emergencyContactPhone: emergencyContactPhone,
        emergencyContactRelationship: emergencyContactRelationship,
      );
      final existing = patient;
      patient = existing == null
          ? updated
          : existing.copyWith(
              phone: updated.phone,
              email: updated.email,
              emergencyContactName: updated.emergencyContactName,
              emergencyContactPhone: updated.emergencyContactPhone,
              emergencyContactRelationship: updated.emergencyContactRelationship,
            );
      return true;
    } on ApiException catch (e) {
      profileUpdateError = e.message;
      return false;
    } catch (e) {
      profileUpdateError = 'Unexpected error: $e';
      return false;
    } finally {
      isUpdatingProfile = false;
      notifyListeners();
    }
  }

  Future<bool> issueEmergencyCard({
    required String patientId,
    required List<String> scope,
  }) async {
    isIssuingCard = true;
    emergencyError = null;
    notifyListeners();
    try {
      emergencyCard = await _api.issueEmergencyCard(patientId: patientId, scope: scope);
      return true;
    } on ApiException catch (e) {
      emergencyError = e.message;
      return false;
    } catch (e) {
      emergencyError = 'Unexpected error: $e';
      return false;
    } finally {
      isIssuingCard = false;
      notifyListeners();
    }
  }

  Future<bool> revokeCurrentCard() async {
    final card = emergencyCard;
    if (card == null) return false;
    try {
      await _api.revokeEmergencyCard(card.cardReference);
      card.revoked = true;
      notifyListeners();
      return true;
    } on ApiException catch (e) {
      emergencyError = e.message;
      notifyListeners();
      return false;
    }
  }

  void clearEmergencyCard() {
    emergencyCard = null;
    emergencyError = null;
    notifyListeners();
  }

  /// FIX for "no synergy between phone-issued and web-issued QR cards":
  /// `emergencyCard` used to only ever get set as a side effect of *this*
  /// screen calling [issueEmergencyCard] — so a card issued from the web
  /// console (or a different install of this app) never appeared here at
  /// all, and a revoke/reissue done elsewhere was invisible too. This
  /// polls the read-only `GET /emergency/current/{patient_id}` (no side
  /// effects — doesn't issue anything, doesn't log an access) and
  /// reconciles [emergencyCard] against whatever the backend says is
  /// actually live right now, the same way the web console's
  /// `CARD_STATUS_POLL_MS` polling reconciles its own display.
  ///
  /// Skips the reconciliation while an issue/revoke request from *this*
  /// device is already in flight, so a poll tick can't race with it and
  /// clobber optimistic local state mid-request.
  Future<void> refreshCurrentCard(String patientId) async {
    if (isIssuingCard) return;
    isLoadingCurrentCard = true;
    try {
      final current = await _api.getCurrentEmergencyCard(patientId);
      final local = emergencyCard;

      if (current == null) {
        // No live card server-side. If we're still showing one as active,
        // it must have been revoked (here or elsewhere) — reflect that.
        if (local != null && !local.revoked) {
          local.revoked = true;
          notifyListeners();
        }
        return;
      }

      if (local == null || local.cardReference != current.cardReference) {
        // Either we've never seen a card this session (fresh launch, or
        // one was issued entirely elsewhere), or the live card has been
        // replaced by a newer one issued elsewhere. Either way, adopt the
        // server's current card so it actually renders here.
        emergencyCard = current;
        notifyListeners();
      } else if (local.revoked) {
        // Same reference, but our local copy thinks it's revoked while
        // the server says it's active again — shouldn't normally happen
        // (revocation isn't reversible), but resync defensively rather
        // than leave a contradictory state on screen.
        local.revoked = false;
        notifyListeners();
      }
    } catch (_) {
      // Transient poll failure — the timer will just try again next tick.
    } finally {
      isLoadingCurrentCard = false;
    }
  }

  /// Starts polling [refreshCurrentCard] every few seconds while a screen
  /// that displays the emergency card is open (call from `initState` of
  /// EmergencyScreen / SeniorEmergencyScreen) — this is what makes a card
  /// issued/revoked on another device "just show up" without the user
  /// having to force-quit and reopen the app. Safe to call repeatedly
  /// (e.g. from multiple screens) — restarts the timer against the given
  /// patient rather than stacking timers.
  void startCardPolling(String patientId, {Duration interval = const Duration(seconds: 5)}) {
    stopCardPolling();
    refreshCurrentCard(patientId); // immediate, don't wait for the first tick
    _cardPollTimer = Timer.periodic(interval, (_) => refreshCurrentCard(patientId));
  }

  void stopCardPolling() {
    _cardPollTimer?.cancel();
    _cardPollTimer = null;
  }

  Future<void> loadAuditLog(String patientId) async {
    isLoadingAuditLog = true;
    notifyListeners();
    try {
      auditLog = await _api.getAuditLog(patientId);
    } catch (_) {
      auditLog = [];
    } finally {
      isLoadingAuditLog = false;
      notifyListeners();
    }
  }

  void clear() {
    stopCardPolling();
    patient = null;
    handoverBrief = null;
    recordError = null;
    emergencyCard = null;
    emergencyError = null;
    auditLog = [];
    nfcCards = [];
    notifyListeners();
  }

  @override
  void dispose() {
    stopCardPolling();
    super.dispose();
  }
}
