/// A single computed reminder for a [ServerAppointment], as returned nested
/// inside the `reminders` array of `GET /patients/{patient_id}/appointments`.
///
/// Critically, the backend computes this list **at read time relative to
/// now** and only includes entries whose `fires_at` is still in the future
/// (see backend/app/routers/patients.py) — so this app deliberately does
/// NOT reimplement the "1 day before / start fasting / 3 hours before"
/// offset algorithm in Dart. Consuming the server's already-filtered list
/// directly means a notification is never scheduled for a time that has
/// already passed, and the two implementations of the same rule can never
/// drift apart.
class AppointmentReminderInfo {
  final String label;
  final int hoursBefore;
  final DateTime firesAt;

  const AppointmentReminderInfo({
    required this.label,
    required this.hoursBefore,
    required this.firesAt,
  });

  factory AppointmentReminderInfo.fromJson(Map<String, dynamic> json) => AppointmentReminderInfo(
        label: json['label'] as String? ?? '',
        hoursBefore: (json['hours_before'] as num?)?.toInt() ?? 0,
        firesAt: DateTime.parse(json['fires_at'] as String),
      );
}

/// A clinic-published appointment, mirroring `AppointmentOut` from
/// `GET /patients/{patient_id}/appointments`. Unlike [AppointmentReminder]
/// (models/appointment_reminder.dart), which is purely device-local and
/// patient-added, this is server-owned data set by staff — the patient can
/// view it but never edit or remove it from this app (see ReminderScreen's
/// separate, non-editable section for these).
class ServerAppointment {
  final String id;
  final String patientId;
  final String facilityName;
  final String? venue;
  final DateTime scheduledAt;
  final String? reason;
  final bool fastingRequired;
  final int? fastingHours;
  final String? precautionNotes;

  /// One of `scheduled` | `cancelled` | `completed` — see the backend's
  /// `AppointmentOut.status`. Callers filtering for "upcoming" should check
  /// this rather than just comparing [scheduledAt] to now, since a
  /// cancelled future-dated appointment should not be treated as upcoming.
  final String status;

  /// Server-computed, future-only reminder offsets for this appointment —
  /// see [AppointmentReminderInfo]. May be empty (e.g. all of this
  /// appointment's reminder windows have already passed even though the
  /// appointment itself is still in the future, or it's already very
  /// close).
  final List<AppointmentReminderInfo> reminders;

  const ServerAppointment({
    required this.id,
    required this.patientId,
    required this.facilityName,
    this.venue,
    required this.scheduledAt,
    this.reason,
    required this.fastingRequired,
    this.fastingHours,
    this.precautionNotes,
    required this.status,
    required this.reminders,
  });

  factory ServerAppointment.fromJson(Map<String, dynamic> json) => ServerAppointment(
        id: json['id'] as String? ?? '',
        patientId: json['patient_id'] as String? ?? '',
        facilityName: json['facility_name'] as String? ?? '',
        venue: json['venue'] as String?,
        scheduledAt: DateTime.parse(json['scheduled_at'] as String),
        reason: json['reason'] as String?,
        fastingRequired: json['fasting_required'] as bool? ?? false,
        fastingHours: (json['fasting_hours'] as num?)?.toInt(),
        precautionNotes: json['precaution_notes'] as String?,
        status: json['status'] as String? ?? 'scheduled',
        reminders: (json['reminders'] as List<dynamic>? ?? [])
            .map((e) => AppointmentReminderInfo.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}
