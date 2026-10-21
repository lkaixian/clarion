import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/queue_ticket.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';

/// Owns the logged-in patient's own reception queue status
/// (`GET /reception/queue/status/{patient_id}`). A small, standalone
/// `ChangeNotifier` — this app deliberately has several small providers
/// rather than one big store (see mobile_flutter/README.md's Architecture
/// section) — mirroring PatientProvider's `startCardPolling`/
/// `stopCardPolling` pattern exactly, including guarding a poll tick
/// against racing an in-flight user action (there is no user-initiated
/// mutation on this screen today — a patient can only ever view their own
/// queue status, never call/complete/cancel a ticket themselves — but the
/// same `isRefreshing` guard is kept for consistency with PatientProvider
/// and so a future action added here doesn't have to relearn/re-add it).
class QueueProvider extends ChangeNotifier {
  QueueProvider({required this._api});

  final ApiClient _api;

  QueueStatus status = QueueStatus.inactive();
  bool isLoading = false;
  String? error;

  Timer? _pollTimer;

  Future<void> refresh(String patientId) async {
    if (isLoading) return;
    isLoading = true;
    // Update + notify BEFORE the await below, not after — same
    // "immediate notifyListeners()" fix documented for
    // RemindersProvider.setMedicationReminderEnabled in
    // mobile_flutter/README.md, so a spinner/disabled state (if a caller
    // ever adds one) reflects `isLoading` right away rather than only after
    // the network call resolves.
    notifyListeners();
    try {
      final result = await _api.getQueueStatus(patientId);
      status = result;
      error = null;
    } on ApiException catch (e) {
      error = e.message;
    } catch (e) {
      error = 'Unexpected error: $e';
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  /// Starts polling [refresh] every few seconds while the Queue Status
  /// screen is open — same 5-second cadence and "immediate first refresh,
  /// don't wait for the first tick" pattern as
  /// PatientProvider.startCardPolling.
  void startPolling(String patientId, {Duration interval = const Duration(seconds: 5)}) {
    stopPolling();
    refresh(patientId);
    _pollTimer = Timer.periodic(interval, (_) => refresh(patientId));
  }

  /// Forget the previous profile's ticket (profile switch).
  void clear() {
    stopPolling();
    status = QueueStatus.inactive();
    error = null;
    notifyListeners();
  }

  void stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  @override
  void dispose() {
    stopPolling();
    super.dispose();
  }
}
