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

/// Mirrors `schemas.RescheduleRequestOut` — returned both as the direct
/// response of `POST /patients/{patient_id}/appointments/{appointment_id}
/// /reschedule-requests` and nested as `latest_reschedule_request` inside
/// each entry of `GET /patients/{patient_id}/appointments` (the most recent
/// request for that appointment, regardless of status, so the UI can show a
/// resolved outcome too — not just a pending one). `status` is one of
/// `pending` | `accepted` | `rejected`.
class RescheduleRequestInfo {
  final String id;
  final String appointmentId;
  final String patientId;
  final String requestedBy;
  final String reasonCode;
  final String? reasonOther;
  final String status;
  final String? clinicianNote;
  final DateTime createdAt;
  final DateTime? resolvedAt;
  final String? resolvedBy;

  const RescheduleRequestInfo({
    required this.id,
    required this.appointmentId,
    required this.patientId,
    required this.requestedBy,
    required this.reasonCode,
    this.reasonOther,
    required this.status,
    this.clinicianNote,
    required this.createdAt,
    this.resolvedAt,
    this.resolvedBy,
  });

  factory RescheduleRequestInfo.fromJson(Map<String, dynamic> json) => RescheduleRequestInfo(
        id: json['id'] as String? ?? '',
        appointmentId: json['appointment_id'] as String? ?? '',
        patientId: json['patient_id'] as String? ?? '',
        requestedBy: json['requested_by'] as String? ?? '',
        reasonCode: json['reason_code'] as String? ?? '',
        reasonOther: json['reason_other'] as String?,
        status: json['status'] as String? ?? 'pending',
        clinicianNote: json['clinician_note'] as String?,
        createdAt: DateTime.parse(json['created_at'] as String),
        resolvedAt: json['resolved_at'] != null ? DateTime.parse(json['resolved_at'] as String) : null,
        resolvedBy: json['resolved_by'] as String?,
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

  /// When this appointment was previously rescheduled (i.e. a reschedule
  /// request against it was accepted), the `scheduled_at` it held before
  /// that change — `null` for an appointment that's never been rescheduled.
  final DateTime? previousScheduledAt;

  /// The reason code/free-text recorded for the most recent *accepted*
  /// reschedule that produced the current [scheduledAt] — distinct from
  /// [latestRescheduleRequest], which reflects the latest request
  /// regardless of status (including a still-pending or rejected one).
  final String? rescheduleReasonCode;
  final String? rescheduleReasonOther;

  /// The most recent reschedule request filed against this appointment,
  /// regardless of status — `null` if none has ever been filed. See
  /// [RescheduleRequestInfo].
  final RescheduleRequestInfo? latestRescheduleRequest;

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
    this.previousScheduledAt,
    this.rescheduleReasonCode,
    this.rescheduleReasonOther,
    this.latestRescheduleRequest,
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
        previousScheduledAt:
            json['previous_scheduled_at'] != null ? DateTime.parse(json['previous_scheduled_at'] as String) : null,
        rescheduleReasonCode: json['reschedule_reason_code'] as String?,
        rescheduleReasonOther: json['reschedule_reason_other'] as String?,
        latestRescheduleRequest: json['latest_reschedule_request'] != null
            ? RescheduleRequestInfo.fromJson(json['latest_reschedule_request'] as Map<String, dynamic>)
            : null,
      );
}
