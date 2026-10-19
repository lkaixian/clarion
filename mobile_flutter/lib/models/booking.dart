/// Online booking v2 (category -> hospital -> date/time -> person -> confirm)
/// plus clinic-published announcements. Mirrors the `/booking/*` endpoints
/// and `GET /patients/announcements`; every parser tolerates missing fields.
library;

/// Wall-clock time of an ISO-8601 string with an offset, exactly as the
/// hospital's own clock shows it (offset dropped, not converted). Slots are
/// serialised in the facility's timezone, so this shows "9:30 AM" at the
/// hospital even when the phone is set to another timezone.
DateTime wallClock(String iso) {
  final s = iso.length >= 19 ? iso.substring(0, 19) : iso;
  return DateTime.parse(s);
}

/// "2.4" for 2.43 km, "12" for 12.04 km; null when unknown.
String? distanceKmLabel(double? km) {
  if (km == null || km.isNaN || km < 0) return null;
  final s = km < 10 ? km.toStringAsFixed(1) : km.toStringAsFixed(0);
  return s;
}

/// Request body for `POST /booking/appointments`. `scheduledAt` is the
/// slot's own `start` string, passed through untouched (the server only
/// accepts a currently offered slot start).
Map<String, dynamic> buildBookingBody({
  required String facilityName,
  required String category,
  required String scheduledAt,
  String? profileId,
  String? reason,
}) {
  final trimmed = reason?.trim() ?? '';
  return {
    'facility_name': facilityName,
    'category': category,
    'scheduled_at': scheduledAt,
    'profile_id': profileId,
    if (trimmed.isNotEmpty) 'reason': trimmed,
  };
}

/// First date with at least one open slot, or null when none.
AvailabilityDay? firstOpenDay(List<AvailabilityDay> days) {
  for (final d in days) {
    if (d.openSlots > 0) return d;
  }
  return null;
}

const bookingRelationships = ['child', 'parent', 'spouse', 'sibling', 'relative', 'other'];

class BookingCategory {
  final String code;
  final String label;
  const BookingCategory({required this.code, required this.label});

  factory BookingCategory.fromJson(Map<String, dynamic> json) => BookingCategory(
        code: json['code'] as String? ?? '',
        label: json['label'] as String? ?? '',
      );
}

class BookingFacility {
  final String facilityName;
  final String displayName;
  final String? address;
  final String? contactPhone;
  final double? distanceKm;

  /// ISO-8601 with offset, or null when nothing is open soon.
  final String? nextAvailableAt;

  const BookingFacility({
    required this.facilityName,
    required this.displayName,
    this.address,
    this.contactPhone,
    this.distanceKm,
    this.nextAvailableAt,
  });

  factory BookingFacility.fromJson(Map<String, dynamic> json) {
    final name = json['facility_name'] as String? ?? '';
    final display = json['display_name'] as String?;
    return BookingFacility(
      facilityName: name,
      displayName: display != null && display.trim().isNotEmpty ? display : name,
      address: json['address'] as String?,
      contactPhone: json['contact_phone'] as String?,
      distanceKm: (json['distance_km'] as num?)?.toDouble(),
      nextAvailableAt: json['next_available_at'] as String?,
    );
  }
}

class AvailabilityDay {
  final String date; // YYYY-MM-DD
  final int openSlots;
  const AvailabilityDay({required this.date, required this.openSlots});

  DateTime get day => DateTime.parse(date);

  factory AvailabilityDay.fromJson(Map<String, dynamic> json) => AvailabilityDay(
        date: json['date'] as String? ?? '',
        openSlots: (json['open_slots'] as num?)?.toInt() ?? 0,
      );
}

class FacilityAvailability {
  final int slotMinutes;
  final int capacity;
  final List<AvailabilityDay> days;
  const FacilityAvailability({required this.slotMinutes, required this.capacity, required this.days});

  factory FacilityAvailability.fromJson(Map<String, dynamic> json) => FacilityAvailability(
        slotMinutes: (json['slot_minutes'] as num?)?.toInt() ?? 0,
        capacity: (json['capacity'] as num?)?.toInt() ?? 1,
        days: (json['days'] as List<dynamic>? ?? [])
            .map((e) => AvailabilityDay.fromJson(e as Map<String, dynamic>))
            .where((d) => d.date.isNotEmpty)
            .toList(),
      );
}

class BookingSlot {
  /// Verbatim ISO string from the server; this is what gets booked.
  final String start;
  final String end;
  final int remaining;
  const BookingSlot({required this.start, required this.end, required this.remaining});

  bool get isFull => remaining <= 0;
  DateTime get startWall => wallClock(start);

  factory BookingSlot.fromJson(Map<String, dynamic> json) => BookingSlot(
        start: json['start'] as String? ?? '',
        end: json['end'] as String? ?? '',
        remaining: (json['remaining'] as num?)?.toInt() ?? 0,
      );
}

/// A saved person (child, parent...) the account holder can book for.
class BookingProfile {
  final String id;
  final String fullName;
  final String relationship;
  final String? dateOfBirth; // YYYY-MM-DD
  final String? nationalId;

  const BookingProfile({
    required this.id,
    required this.fullName,
    required this.relationship,
    this.dateOfBirth,
    this.nationalId,
  });

  factory BookingProfile.fromJson(Map<String, dynamic> json) => BookingProfile(
        id: json['id'] as String? ?? '',
        fullName: json['full_name'] as String? ?? '',
        relationship: json['relationship'] as String? ?? 'other',
        dateOfBirth: json['date_of_birth'] as String?,
        nationalId: json['national_id'] as String?,
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
