/// P3.10: patient self-service appointment booking + P3.10
///: clinic-published announcements. Mirrors
/// `GET /patients/appointment-slots`, `GET /patients/booking-options` and
/// `GET /patients/announcements` — see backend/app/schemas.py's
/// AppointmentSlotOut / BookingOptionsOut / AnnouncementOut for the exact
/// server-side shapes these are parsed from.
library;

/// One bookable slot returned by `GET /patients/appointment-slots`.
class AppointmentSlot {
  final DateTime scheduledAt;
  final String? clinicianId;
  final String? clinicianName;

  const AppointmentSlot({
    required this.scheduledAt,
    this.clinicianId,
    this.clinicianName,
  });

  factory AppointmentSlot.fromJson(Map<String, dynamic> json) => AppointmentSlot(
        scheduledAt: DateTime.parse(json['scheduled_at'] as String),
        clinicianId: json['clinician_id'] as String?,
        clinicianName: json['clinician_name'] as String?,
      );
}

/// One clinician a patient can pick from when self-booking.
class BookingClinician {
  final String id;
  final String fullName;
  final String? department;

  const BookingClinician({
    required this.id,
    required this.fullName,
    this.department,
  });

  factory BookingClinician.fromJson(Map<String, dynamic> json) => BookingClinician(
        id: json['id'] as String? ?? '',
        fullName: json['full_name'] as String? ?? '',
        department: json['department'] as String?,
      );
}

/// The department + clinician pickers for one facility, from
/// `GET /patients/booking-options`.
class BookingOptions {
  final List<String> departments;
  final List<BookingClinician> clinicians;

  const BookingOptions({
    required this.departments,
    required this.clinicians,
  });

  factory BookingOptions.fromJson(Map<String, dynamic> json) => BookingOptions(
        departments: (json['departments'] as List<dynamic>? ?? []).map((e) => e as String).toList(),
        clinicians: (json['clinicians'] as List<dynamic>? ?? [])
            .map((e) => BookingClinician.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// A clinic-published notice (health campaign, service change), from
/// `GET /patients/announcements` — already filtered server-side to
/// currently-live ones (started, not yet expired), so this app never needs
/// to re-check `expiresAt` before displaying one.
class Announcement {
  final String id;
  final String? facilityName;
  final String title;
  final String body;
  final DateTime startsAt;
  final DateTime? expiresAt;
  final DateTime createdAt;

  const Announcement({
    required this.id,
    this.facilityName,
    required this.title,
    required this.body,
    required this.startsAt,
    this.expiresAt,
    required this.createdAt,
  });

  factory Announcement.fromJson(Map<String, dynamic> json) => Announcement(
        id: json['id'] as String? ?? '',
        facilityName: json['facility_name'] as String?,
        title: json['title'] as String? ?? '',
        body: json['body'] as String? ?? '',
        startsAt: DateTime.parse(json['starts_at'] as String),
        expiresAt: json['expires_at'] != null ? DateTime.parse(json['expires_at'] as String) : null,
        createdAt: DateTime.parse(json['created_at'] as String),
      );
}
