import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/appointment_reminder.dart';
import '../models/patient.dart';
import '../models/server_appointment.dart';
import '../services/api_client.dart';
import '../services/notification_service.dart';

/// Drives the Reminders screen: which active medications currently have a
/// local reminder scheduled, a small list of user-added appointment
/// reminders, and (since the backend grew a real appointments concept) a
/// separate, read-only list of clinic-published appointments synced from
/// the server. The medication/self-added-appointment halves of this class
/// are entirely device-local (SharedPreferences + flutter_local_notifications)
/// — only [_serverAppointments] talks to the backend, and even then only to
/// read; there is still no way for the patient to create/edit/delete a
/// server appointment from this app.
class RemindersProvider extends ChangeNotifier {
  static const _mutedMedsKey = 'mb_muted_medication_reminders';
  static const _appointmentsKey = 'mb_appointment_reminders';
  static const _permissionAskedKey = 'mb_notif_permission_asked';
  // Tracks which (server appointment id, reminder index) pairs currently
  // have a local notification scheduled for them, so the next sync can
  // diff against this set and cancel anything that's no longer current
  // (appointment cancelled server-side, or a reminder window's `fires_at`
  // passed and the backend stopped sending it) instead of only ever adding.
  // See syncServerAppointments.
  static const _serverReminderKeysKey = 'mb_server_appointment_reminder_keys';

  Set<String> _mutedMedications = {};
  List<AppointmentReminder> _appointments = [];
  List<ServerAppointment> _serverAppointments = [];
  bool _notificationsGranted = false;
  bool _notificationsPermanentlyDenied = false;
  bool _loaded = false;

  Set<String> get mutedMedications => _mutedMedications;
  List<AppointmentReminder> get appointments =>
      List.unmodifiable(_appointments);

  /// Clinic-published appointments as last fetched from
  /// `GET /patients/{id}/appointments` (see [syncServerAppointments]) —
  /// includes all statuses; screens that want only the actionable ones
  /// should filter on `status == 'scheduled'` themselves (mirrors how
  /// [Patient.activeMedications] filters at the call site rather than here).
  List<ServerAppointment> get serverAppointments =>
      List.unmodifiable(_serverAppointments);
  bool get notificationsGranted => _notificationsGranted;

  /// True once Android has permanently denied the notification-permission
  /// prompt (i.e. the user said no before, possibly by accident, or during
  /// earlier testing) — at that point Android will **not show the system
  /// dialog again** no matter how many times the app asks; the only way
  /// forward is the app's own Settings screen. See [openNotificationSettings].
  bool get notificationsPermanentlyDenied => _notificationsPermanentlyDenied;
  bool get isLoaded => _loaded;

  Timer? _appointmentPollTimer;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _mutedMedications = (prefs.getStringList(_mutedMedsKey) ?? []).toSet();
    final rawAppointments = prefs.getString(_appointmentsKey);
    if (rawAppointments != null) {
      final list = jsonDecode(rawAppointments) as List<dynamic>;
      _appointments =
          list
              .map(
                (e) => AppointmentReminder.fromJson(e as Map<String, dynamic>),
              )
              .toList()
            ..sort((a, b) => a.dateTime.compareTo(b.dateTime));
    }
    _loaded = true;
    notifyListeners();
  }

  /// FIX ("notification button still broken" after the permission was
  /// denied once): uses `permission_handler` (rather than
  /// flutter_local_notifications' own request call, which can't tell the
  /// difference) so this can distinguish "not asked yet" / "denied, can
  /// ask again" from **`permanentlyDenied`** — once Android has that
  /// status for this permission, calling `request()` again is a silent
  /// no-op that shows no UI at all, which is exactly what made the
  /// "Enable" button look broken. When permanently denied, this stops
  /// trying to re-request and instead exposes
  /// [notificationsPermanentlyDenied] so the UI can offer
  /// [openNotificationSettings] instead — the only way to actually grant
  /// it after a denial.
  Future<void> ensurePermissionRequested() async {
    final prefs = await SharedPreferences.getInstance();
    try {
      var status = await Permission.notification.status;
      if (status.isGranted) {
        _notificationsGranted = true;
        _notificationsPermanentlyDenied = false;
      } else if (status.isPermanentlyDenied) {
        _notificationsGranted = false;
        _notificationsPermanentlyDenied = true;
      } else {
        status = await Permission.notification.request();
        _notificationsGranted = status.isGranted;
        _notificationsPermanentlyDenied = status.isPermanentlyDenied;
      }
    } catch (e) {
      debugPrint(
        'RemindersProvider: notification permission check/request failed ($e)',
      );
      _notificationsGranted = false;
    }
    await prefs.setBool(_permissionAskedKey, true);
    notifyListeners();
  }

  /// Opens this app's system Settings screen — the only way to grant the
  /// notification permission once Android has permanently denied it (see
  /// [ensurePermissionRequested]). Call [ensurePermissionRequested] again
  /// when the user returns to the app afterwards (e.g. on
  /// `AppLifecycleState.resumed`) to pick up whatever they changed.
  Future<void> openNotificationSettings() => openAppSettings();

  bool isMedicationReminderEnabled(String drugName) =>
      !_mutedMedications.contains(drugName);

  /// FIX (previously reported: "toggle doesn't update until I leave and
  /// come back to this screen"): this used to call `notifyListeners()`
  /// only once, at the very end, *after* awaiting the notification-plugin
  /// scheduling calls. If that await was slow (or threw — e.g. permission
  /// not actually granted, or the plugin not fully initialized yet), the
  /// UI never got told to rebuild, so the `Switch` visually stayed in its
  /// old position until some *other* action (like `load()` on screen
  /// re-entry) happened to call `notifyListeners()` afterwards. Now the
  /// preference is applied and broadcast to listeners **immediately** —
  /// the actual OS-level notification scheduling happens after, in the
  /// background, wrapped in try/catch so it can never block or silently
  /// swallow the UI update again.
  Future<void> setMedicationReminderEnabled(
    String drugName,
    bool enabled,
  ) async {
    if (enabled) {
      _mutedMedications.remove(drugName);
    } else {
      _mutedMedications.add(drugName);
    }
    notifyListeners();

    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_mutedMedsKey, _mutedMedications.toList());

    try {
      if (enabled) {
        await _scheduleBothDoses(drugName);
      } else {
        await NotificationService.instance.cancelMedicationReminder(
          drugName,
          0,
        );
        await NotificationService.instance.cancelMedicationReminder(
          drugName,
          1,
        );
      }
    } catch (e) {
      debugPrint(
        'RemindersProvider: failed to (un)schedule reminder for $drugName ($e)',
      );
      // The on/off preference itself is already saved and reflected in the
      // UI above regardless of whether OS-level scheduling succeeded.
    }
  }

  Future<void> _scheduleBothDoses(String drugName) async {
    await NotificationService.instance.scheduleMedicationReminder(
      drugName: drugName,
      slotIndex: 0,
      hour: 8,
      minute: 0,
      title: 'Time for your medication',
      body: 'Take $drugName (morning dose)',
    );
    await NotificationService.instance.scheduleMedicationReminder(
      drugName: drugName,
      slotIndex: 1,
      hour: 20,
      minute: 0,
      title: 'Time for your medication',
      body: 'Take $drugName (evening dose)',
    );
  }

  /// Re-syncs scheduled notifications against the patient's current active
  /// medication list — call whenever the record (re)loads. Medications
  /// that are no longer active get their reminders cancelled; newly active
  /// ones that aren't muted get scheduled. Each medication is scheduled
  /// independently (try/catch per drug) so one failure doesn't stop the
  /// rest of the list from syncing.
  Future<void> syncWithActiveMedications(List<Medication> activeMeds) async {
    if (!_notificationsGranted) return;
    final activeNames = activeMeds.map((m) => m.drugName).toSet();

    for (final drugName in activeNames) {
      if (_mutedMedications.contains(drugName)) continue;
      try {
        await _scheduleBothDoses(drugName);
      } catch (e) {
        debugPrint(
          'RemindersProvider: failed to sync reminder for $drugName ($e)',
        );
      }
    }
  }

  /// Re-syncs the clinic-published appointment list from the backend and
  /// reconciles local notifications against it — call whenever the record
  /// (re)loads (app open, pull-to-refresh), same trigger as
  /// [syncWithActiveMedications]. This is the entire "delivery mechanism"
  /// for server appointment reminders in this MVP: there is no push
  /// infrastructure, so instead this just polls-and-reconciles on every
  /// record load, using the server's own future-only `reminders` list (see
  /// [ServerAppointment]) as the source of truth each time.
  ///
  /// Safe to call repeatedly/idempotently: every call fully recomputes
  /// which (appointment, reminder) pairs *should* have a notification
  /// scheduled right now and diffs that against what was scheduled last
  /// time (persisted in [_serverReminderKeysKey]), so a re-sync replaces
  /// stale schedules rather than piling up duplicates — covering both "this
  /// appointment got cancelled server-side" and "this reminder's
  /// `fires_at` already passed, so the backend stopped including it".
  ///
  /// Wrapped defensively throughout (mirrors [syncWithActiveMedications]'s
  /// per-item try/catch, plus an outer guard around the network call
  /// itself) — a failure here must never crash the app or block anything
  /// else in this provider.
  Future<void> syncServerAppointments(String patientId, ApiClient api) async {
    List<ServerAppointment> fetched;
    try {
      fetched = await api.getAppointments(patientId);
    } catch (e) {
      debugPrint('RemindersProvider: failed to fetch server appointments ($e)');
      return; // Leave whatever was previously loaded/scheduled untouched.
    }

    try {
      _serverAppointments = fetched
        ..sort((a, b) => a.scheduledAt.compareTo(b.scheduledAt));
      notifyListeners();

      final prefs = await SharedPreferences.getInstance();
      final previousKeys = (prefs.getStringList(_serverReminderKeysKey) ?? [])
          .toSet();
      final newKeys = <String>{};

      if (_notificationsGranted) {
        for (final appt in fetched) {
          // Never schedule for a cancelled/completed appointment, and
          // nothing to schedule if every reminder window for this one has
          // already passed (empty list, per the backend's future-only
          // contract).
          if (appt.status != 'scheduled' || appt.reminders.isEmpty) continue;

          for (var i = 0; i < appt.reminders.length; i++) {
            final reminder = appt.reminders[i];
            final key = '${appt.id}#$i';
            newKeys.add(key);
            try {
              await NotificationService.instance
                  .scheduleServerAppointmentReminder(
                    serverAppointmentId: appt.id,
                    reminderIndex: i,
                    firesAt: reminder.firesAt,
                    title: reminder.label,
                    body: appt.venue != null && appt.venue!.trim().isNotEmpty
                        ? '${appt.facilityName} — ${appt.venue}'
                        : appt.facilityName,
                  );
            } catch (e) {
              debugPrint(
                'RemindersProvider: failed to schedule server appointment reminder ($e)',
              );
            }
          }
        }
      }

      // Anything that was scheduled last sync but isn't part of this fresh
      // fetch's key set no longer applies — cancel it explicitly, since
      // flutter_local_notifications won't do this on its own.
      final staleKeys = previousKeys.difference(newKeys);
      for (final key in staleKeys) {
        final parts = key.split('#');
        if (parts.length != 2) continue;
        final reminderIndex = int.tryParse(parts[1]);
        if (reminderIndex == null) continue;
        try {
          await NotificationService.instance.cancelServerAppointmentReminder(
            parts[0],
            reminderIndex,
          );
        } catch (e) {
          debugPrint(
            'RemindersProvider: failed to cancel stale server appointment reminder ($e)',
          );
        }
      }

      await prefs.setStringList(_serverReminderKeysKey, newKeys.toList());
    } catch (e) {
      debugPrint('RemindersProvider: failed to sync server appointments ($e)');
    }
  }

  /// FIX for "web-published appointments never show up / update in the
  /// app": [syncServerAppointments] used to only ever be called once, from
  /// RemindersScreen's `initState`, so an appointment published (or
  /// cancelled/edited) from the web console after the screen was opened
  /// simply never appeared without a manual force-quit-and-reopen. This
  /// mirrors the "make it dynamic" pattern already used elsewhere in this
  /// app for the exact same class of problem —
  /// `PatientProvider.startCardPolling`/`stopCardPolling` (polls
  /// `GET /emergency/current/{id}` every 5s while a relevant screen is
  /// open) and the web console's own `CARD_STATUS_POLL_MS` (4s) — except
  /// appointments change far less often than a live emergency card, so a
  /// longer interval is used by default. Safe to call repeatedly (restarts
  /// the timer rather than stacking one).
  void startAppointmentPolling(
    String patientId,
    ApiClient api, {
    Duration interval = const Duration(seconds: 20),
  }) {
    stopAppointmentPolling();
    syncServerAppointments(
      patientId,
      api,
    ); // immediate, don't wait for the first tick
    _appointmentPollTimer = Timer.periodic(
      interval,
      (_) => syncServerAppointments(patientId, api),
    );
  }

  void stopAppointmentPolling() {
    _appointmentPollTimer?.cancel();
    _appointmentPollTimer = null;
  }

  @override
  void dispose() {
    stopAppointmentPolling();
    super.dispose();
  }

  Future<void> addAppointment(String title, DateTime when) async {
    final id =
        '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(99999)}';
    final appointment = AppointmentReminder(
      id: id,
      title: title,
      dateTime: when,
    );
    _appointments = [..._appointments, appointment]
      ..sort((a, b) => a.dateTime.compareTo(b.dateTime));
    notifyListeners();

    await _persistAppointments();

    if (_notificationsGranted) {
      try {
        await NotificationService.instance.scheduleAppointmentReminder(
          appointmentId: id,
          when: when,
          title: 'Upcoming appointment',
          body: title,
        );
      } catch (e) {
        debugPrint(
          'RemindersProvider: failed to schedule appointment reminder ($e)',
        );
      }
    }
  }

  Future<void> removeAppointment(String id) async {
    _appointments = _appointments.where((a) => a.id != id).toList();
    notifyListeners();

    await _persistAppointments();
    try {
      await NotificationService.instance.cancelAppointmentReminder(id);
    } catch (e) {
      debugPrint(
        'RemindersProvider: failed to cancel appointment reminder ($e)',
      );
    }
  }

  /// Fires an immediate (not scheduled) notification so the feature is
  /// actually demonstrable on the spot — real medication reminders are
  /// fixed at 8am/8pm, which nobody can wait around for live. Returns
  /// `false` (without throwing) if it fails, so the UI can show a
  /// specific error rather than silently doing nothing.
  Future<bool> sendTestNotification({
    required String title,
    required String body,
  }) async {
    try {
      await NotificationService.instance.showTestNotificationNow(
        title: title,
        body: body,
      );
      return true;
    } catch (e) {
      debugPrint('RemindersProvider: test notification failed ($e)');
      return false;
    }
  }

  Future<void> _persistAppointments() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _appointmentsKey,
      jsonEncode(_appointments.map((a) => a.toJson()).toList()),
    );
  }
}
