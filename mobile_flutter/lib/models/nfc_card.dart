import 'audit_log_entry.dart';

/// One row of `GET /emergency/nfc/{patient_id}`. Only the last 4 of the UID
/// ever reach the client.
class NfcCard {
  const NfcCard({
    required this.id,
    required this.last4,
    required this.scope,
    required this.grantValidUntil,
    required this.revoked,
    required this.createdAt,
    required this.tagType,
    required this.outdated,
    required this.status,
    this.validDaysLeft,
  });

  final String id;
  final String last4;
  final List<String> scope;
  final String grantValidUntil;
  final bool revoked;
  final String createdAt;
  final String tagType; // ntag21x | ntag424 | unknown
  final bool outdated;
  final String status; // active | expired | revoked
  final int? validDaysLeft;

  factory NfcCard.fromJson(Map<String, dynamic> j) {
    final revoked = j['revoked'] as bool? ?? false;
    return NfcCard(
      id: j['id']?.toString() ?? '',
      last4: j['nfc_uid_last4']?.toString() ?? '????',
      scope: (j['scope'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
      grantValidUntil: j['grant_valid_until'] as String? ?? '',
      revoked: revoked,
      createdAt: j['created_at'] as String? ?? '',
      tagType: j['tag_type'] as String? ?? 'unknown',
      outdated: j['outdated'] as bool? ?? false,
      status: j['status'] as String? ?? (revoked ? 'revoked' : 'active'),
      validDaysLeft: (j['valid_days_left'] as num?)?.toInt(),
    );
  }

  DateTime? get validUntil => parseServerTime(grantValidUntil);
  DateTime? get created => parseServerTime(createdAt);
}

/// Active cards first, then newest first.
List<NfcCard> sortNfcCards(List<NfcCard> cards) {
  final out = [...cards];
  out.sort((a, b) {
    final aa = a.status == 'active' ? 0 : 1;
    final bb = b.status == 'active' ? 0 : 1;
    if (aa != bb) return aa - bb;
    final ta = a.created ?? DateTime.fromMillisecondsSinceEpoch(0);
    final tb = b.created ?? DateTime.fromMillisecondsSinceEpoch(0);
    return tb.compareTo(ta);
  });
  return out;
}

/// One item of `GET /emergency/nfc/{patient_id}/{card_id}/history`.
class NfcCardEvent {
  const NfcCardEvent({required this.at, required this.event, this.byRole, this.byOrg, this.facility});

  final String at;
  final String event; // registered | renewed | revoked | scanned
  final String? byRole;
  final String? byOrg;
  final String? facility;

  factory NfcCardEvent.fromJson(Map<String, dynamic> j) => NfcCardEvent(
        at: j['at'] as String? ?? '',
        event: j['event'] as String? ?? '',
        byRole: j['by_role'] as String?,
        byOrg: j['by_org'] as String?,
        facility: j['facility'] as String?,
      );

  DateTime? get time => parseServerTime(at);
}
