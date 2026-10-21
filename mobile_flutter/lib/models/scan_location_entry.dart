import 'audit_log_entry.dart' show parseServerTime;

/// One row of `GET /emergency/locations/{patient_id}`: a position reported by
/// the phone of whoever scanned this patient's card.
class ScanLocationEntry {
  const ScanLocationEntry({
    required this.lat,
    required this.lng,
    this.accuracyM,
    this.tier,
    this.actorRole,
    this.actorFacility,
    this.createdAt,
  });

  final double lat;
  final double lng;
  final int? accuracyM;
  final String? tier; // public | responder | paramedic | clinical
  final String? actorRole;
  final String? actorFacility;
  final DateTime? createdAt;

  factory ScanLocationEntry.fromJson(Map<String, dynamic> j) => ScanLocationEntry(
        lat: (j['lat'] as num).toDouble(),
        lng: (j['lng'] as num).toDouble(),
        accuracyM: (j['accuracy_m'] as num?)?.round(),
        tier: j['tier'] as String?,
        actorRole: j['actor_role'] as String?,
        actorFacility: j['actor_facility'] as String?,
        createdAt: parseServerTime(j['created_at'] as String? ?? ''),
      );
}
