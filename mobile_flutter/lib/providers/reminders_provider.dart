import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/appointment_reminder.dart';
import '../models/patient.dart';
import '../services/notification_service.dart';

/// Drives the Reminders screen: which active medications currently have a
/// local reminder scheduled, plus a small list of user-added appointment
/// reminders. Everything here is device-local (SharedPreferences +
/// flutter_local_notifications) — there is no backend endpoint for
/// reminders in this MVP.
class RemindersProvider extends ChangeNotifier {
  static const _mutedMedsKey = 'mb_muted_medication_reminders';
  static const _appointmentsKey = 'mb_appointment_reminders';
  static const _permissionAskedKey = 'mb_notif_permission_asked';

  Set<String> _mutedMedications = {};
  List<AppointmentReminder> _appointments = [];
  bool _notificationsGranted = false;
  bool _notificationsPermanentlyDenied = false;
  bool _loaded = false;

  Set<String> get mutedMedications => _mutedMedications;
  List<AppointmentReminder> get appointments => List.unmodifiable(_appointments);
  bool get notificationsGranted => _notificationsGranted;
  /// True once Android has permanently denied the notification-permission
  /// prompt (i.e. the user said no before, possibly by accident, or during
  /// earlier testing) — at that point Android will **not show the system
  /// dialog again** no matter how many times the app asks; the only way
  /// forward is the app's own Settings screen. See [openNotificationSettings].
  bool get notificationsPermanentlyDenied => _notificationsPermanentlyDenied;
  bool get isLoaded => _loaded;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _mutedMedications = (prefs.getStringList(_mutedMedsKey) ?? []).toSet();
    final rawAppointments = prefs.getString(_appointmentsKey);
    if (rawAppointments != null) {
      final list = jsonDecode(rawAppointments) as List<dynamic>;
      _appointments = list
          .map((e) => AppointmentReminder.fromJson(e as Map<String, dynamic>))
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
      debugPrint('RemindersProvider: notification permission check/request failed ($e)');
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

  bool isMedicationReminderEnabled(String drugName) => !_mutedMedications.contains(drugName);

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
  Future<void> setMedicationReminderEnabled(String drugName, bool enabled) async {
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
        await NotificationService.instance.cancelMedicationReminder(drugName, 0);
        await NotificationService.instance.cancelMedicationReminder(drugName, 1);
      }
    } catch (e) {
      debugPrint('RemindersProvider: failed to (un)schedule reminder for $drugName ($e)');
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
        debugPrint('RemindersProvider: failed to sync reminder for $drugName ($e)');
      }
    }
  }

  Future<void> addAppointment(String title, DateTime when) async {
    final id = '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(99999)}';
    final appointment = AppointmentReminder(id: id, title: title, dateTime: when);
    _appointments = [..._appointments, appointment]..sort((a, b) => a.dateTime.compareTo(b.dateTime));
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
        debugPrint('RemindersProvider: failed to schedule appointment reminder ($e)');
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
      debugPrint('RemindersProvider: failed to cancel appointment reminder ($e)');
    }
  }

  /// Fires an immediate (not scheduled) notification so the feature is
  /// actually demonstrable on the spot — real medication reminders are
  /// fixed at 8am/8pm, which nobody can wait around for live. Returns
  /// `false` (without throwing) if it fails, so the UI can show a
  /// specific error rather than silently doing nothing.
  Future<bool> sendTestNotification({required String title, required String body}) async {
    try {
      await NotificationService.instance.showTestNotificationNow(title: title, body: body);
      return true;
    } catch (e) {
      debugPrint('RemindersProvider: test notification failed ($e)');
      return false;
    }
  }

  Future<void> _persistAppointments() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_appointmentsKey, jsonEncode(_appointments.map((a) => a.toJson()).toList()));
  }
}
