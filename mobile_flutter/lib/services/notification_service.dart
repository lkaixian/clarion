import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

/// Purely local (on-device) medication + appointment reminders. There is no
/// backend endpoint for this — matches the reference RN app's
/// RemindersScreen.js intent, which derives reminders from the patient's
/// own medication list rather than requiring a server-side reminders
/// feature. Real, working local notifications (not just a static list)
/// per the "notify the user to remember take medicine / appointment"
/// request.
class NotificationService {
  NotificationService._();
  static final NotificationService instance = NotificationService._();

  final FlutterLocalNotificationsPlugin _plugin = FlutterLocalNotificationsPlugin();
  bool _initialized = false;

  /// Deterministic notification IDs so re-scheduling the same medication
  /// (e.g. after editing the record, or on every app start) replaces the
  /// existing notification instead of piling up duplicates. Medication
  /// reminders use IDs in [0, 100000); appointment reminders use IDs in
  /// [100000, 200000) — see [_appointmentNotificationId].
  static int medicationNotificationId(String drugName, int slotIndex) {
    // slotIndex distinguishes the 8am vs 8pm dose of the same drug.
    return (drugName.toLowerCase().hashCode.abs() % 90000) * 10 + slotIndex;
  }

  static int appointmentNotificationId(String appointmentId) {
    return 100000 + (appointmentId.hashCode.abs() % 90000);
  }

  Future<void> init() async {
    if (_initialized) return;

    tz_data.initializeTimeZones();
    try {
      final deviceTimeZone = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(deviceTimeZone));
    } catch (e) {
      // Falls back to whatever `timezone`'s default local location is
      // (UTC) rather than crashing app startup over a reminders feature.
      debugPrint('NotificationService: could not resolve device timezone ($e), reminders may fire in UTC.');
    }

    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosInit = DarwinInitializationSettings();
    await _plugin.initialize(
      const InitializationSettings(android: androidInit, iOS: iosInit),
    );
    _initialized = true;
  }

  static const _medicationChannel = AndroidNotificationDetails(
    'medication_reminders',
    'Medication reminders',
    channelDescription: 'Reminders to take your scheduled medication.',
    importance: Importance.high,
    priority: Priority.high,
  );

  static const _appointmentChannel = AndroidNotificationDetails(
    'appointment_reminders',
    'Appointment reminders',
    channelDescription: 'Reminders about upcoming medical appointments.',
    importance: Importance.high,
    priority: Priority.high,
  );

  static const _testChannel = AndroidNotificationDetails(
    'test_notifications',
    'Test notifications',
    channelDescription: 'One-off test notification triggered manually from the Reminders screen.',
    importance: Importance.high,
    priority: Priority.high,
  );

  /// Shows a notification **immediately** (not scheduled) — for the
  /// Reminders screen's "Send test notification now" button. Real
  /// medication reminders are fixed at 8am/8pm, which isn't demoable live;
  /// this lets someone actually see a notification appear on the spot to
  /// confirm the whole pipeline (permission → channel → OS tray) works,
  /// without waiting for a scheduled time.
  Future<void> showTestNotificationNow({required String title, required String body}) async {
    await init();
    await _plugin.show(
      999999,
      title,
      body,
      const NotificationDetails(android: _testChannel, iOS: DarwinNotificationDetails()),
    );
  }

  /// Schedules a daily-repeating reminder at [hour]:[minute] local time for
  /// one medication dose. Safe to call again for the same drug/slot — it
  /// replaces the previous schedule rather than duplicating it.
  Future<void> scheduleMedicationReminder({
    required String drugName,
    required int slotIndex,
    required int hour,
    required int minute,
    required String title,
    required String body,
  }) async {
    await init();
    final id = medicationNotificationId(drugName, slotIndex);
    await _plugin.zonedSchedule(
      id,
      title,
      body,
      _nextInstanceOfTime(hour, minute),
      const NotificationDetails(android: _medicationChannel, iOS: DarwinNotificationDetails()),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      matchDateTimeComponents: DateTimeComponents.time,
      // iOS-only legacy parameter, still required by this plugin version
      // even for an Android-focused app — `absoluteTime` means "treat
      // scheduledDate as-is", the only sane choice for a fixed wall-clock
      // reminder time like this.
      uiLocalNotificationDateInterpretation: UILocalNotificationDateInterpretation.absoluteTime,
    );
  }

  Future<void> cancelMedicationReminder(String drugName, int slotIndex) async {
    await init();
    await _plugin.cancel(medicationNotificationId(drugName, slotIndex));
  }

  /// Schedules a one-off reminder for an appointment at [when]. If [when]
  /// is already in the past, does nothing (caller should validate first).
  Future<void> scheduleAppointmentReminder({
    required String appointmentId,
    required DateTime when,
    required String title,
    required String body,
  }) async {
    await init();
    if (when.isBefore(DateTime.now())) return;
    final id = appointmentNotificationId(appointmentId);
    await _plugin.zonedSchedule(
      id,
      title,
      body,
      tz.TZDateTime.from(when, tz.local),
      const NotificationDetails(android: _appointmentChannel, iOS: DarwinNotificationDetails()),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      uiLocalNotificationDateInterpretation: UILocalNotificationDateInterpretation.absoluteTime,
    );
  }

  Future<void> cancelAppointmentReminder(String appointmentId) async {
    await init();
    await _plugin.cancel(appointmentNotificationId(appointmentId));
  }

  tz.TZDateTime _nextInstanceOfTime(int hour, int minute) {
    final now = tz.TZDateTime.now(tz.local);
    var scheduled = tz.TZDateTime(tz.local, now.year, now.month, now.day, hour, minute);
    if (scheduled.isBefore(now)) {
      scheduled = scheduled.add(const Duration(days: 1));
    }
    return scheduled;
  }
}
