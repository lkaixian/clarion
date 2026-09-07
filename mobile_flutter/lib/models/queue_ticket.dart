/// Mirrors `schemas.QueueTicketOut` on the backend (see
/// `backend/app/routers/reception.py`). One reception-desk check-in / queue
/// ticket. `department`/`reason` are nullable-safe the same way
/// [QueueStatus] and [EmergencyCard] treat their own optional fields.
class QueueTicket {
  final String id;
  final String patientId;
  final String facilityName;
  final int queueNumber;
  final String? department;
  final String? reason;
  final String source; // "qr" | "nfc" | "manual"
  final String status; // waiting | called | done | cancelled -- a ticket goes
  // straight from "called" to "done", there is no intermediate "serving" state
  final String checkedInAt; // ISO timestamp
  final String? calledAt;
  final String? completedAt;
  final String checkedInBy;

  QueueTicket({
    required this.id,
    required this.patientId,
    required this.facilityName,
    required this.queueNumber,
    required this.department,
    required this.reason,
    required this.source,
    required this.status,
    required this.checkedInAt,
    required this.calledAt,
    required this.completedAt,
    required this.checkedInBy,
  });

  factory QueueTicket.fromJson(Map<String, dynamic> json) => QueueTicket(
        id: json['id'] as String,
        patientId: json['patient_id'] as String,
        facilityName: json['facility_name'] as String,
        queueNumber: json['queue_number'] as int,
        department: json['department'] as String?,
        reason: json['reason'] as String?,
        source: json['source'] as String? ?? 'manual',
        status: json['status'] as String? ?? 'waiting',
        checkedInAt: json['checked_in_at'] as String? ?? '',
        calledAt: json['called_at'] as String?,
        completedAt: json['completed_at'] as String?,
        checkedInBy: json['checked_in_by'] as String? ?? '',
      );

  DateTime? get checkedInAtAsDateTime {
    try {
      return DateTime.parse(checkedInAt).toLocal();
    } catch (_) {
      return null;
    }
  }
}

/// Mirrors `schemas.QueueStatusOut` — the response of
/// `GET /reception/queue/status/{patient_id}`. `active: false` (with every
/// other field null) is the explicit "nothing to show" shape, matching
/// `GET /emergency/current/{patient_id}`'s `{"active": false}` convention
/// (see [EmergencyCard] / PatientProvider for the equivalent pattern on the
/// emergency-card side of this app).
class QueueStatus {
  final bool active;
  final QueueTicket? ticket;
  final int? nowServing;
  final int? peopleAhead;

  QueueStatus({
    required this.active,
    required this.ticket,
    required this.nowServing,
    required this.peopleAhead,
  });

  factory QueueStatus.fromJson(Map<String, dynamic> json) => QueueStatus(
        active: json['active'] as bool? ?? false,
        ticket: json['ticket'] != null
            ? QueueTicket.fromJson(json['ticket'] as Map<String, dynamic>)
            : null,
        nowServing: json['now_serving'] as int?,
        peopleAhead: json['people_ahead'] as int?,
      );

  factory QueueStatus.inactive() => QueueStatus(
        active: false,
        ticket: null,
        nowServing: null,
        peopleAhead: null,
      );
}
