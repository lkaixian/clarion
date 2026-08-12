import 'dart:convert';
import 'dart:typed_data';

/// Mirrors the response of `POST /emergency/issue` **and**
/// `GET /emergency/current/{patient_id}` (when `active: true`) — both
/// endpoints return the same shape for a live card, which is what lets a
/// card issued on one device/session show up correctly when fetched from
/// another (see PatientProvider.refreshCurrentCard).
class EmergencyCard {
  final String cardReference;
  // Nullable defensively: `/emergency/current` is a newer addition to the
  // backend contract than `/emergency/issue`, and `qr_code_base64` was
  // added to it slightly after the endpoint itself existed. Treat a
  // missing/null value as "card is active, but this server build can't
  // render its QR image" rather than crashing — see EmergencyScreen /
  // SeniorEmergencyScreen for how the UI degrades when this is null.
  final String? qrCodeBase64; // full "data:image/png;base64,..." string, or null
  final List<String> scope;
  final String grantValidUntil; // ISO timestamp
  final String note;
  final int previousCardsRevoked;
  bool revoked;

  EmergencyCard({
    required this.cardReference,
    required this.qrCodeBase64,
    required this.scope,
    required this.grantValidUntil,
    required this.note,
    this.previousCardsRevoked = 0,
    this.revoked = false,
  });

  factory EmergencyCard.fromJson(Map<String, dynamic> json) => EmergencyCard(
        cardReference: json['card_reference'] as String,
        qrCodeBase64: json['qr_code_base64'] as String?,
        scope: (json['scope'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
        grantValidUntil: json['grant_valid_until'] as String? ?? '',
        note: json['note'] as String? ?? '',
        previousCardsRevoked: json['previous_cards_revoked'] as int? ?? 0,
      );

  DateTime? get expiryAsDateTime {
    try {
      return DateTime.parse(grantValidUntil).toLocal();
    } catch (_) {
      return null;
    }
  }

  /// Decoded PNG bytes for [qrCodeBase64], or null if there's no image to
  /// decode (missing from the server response, or malformed).
  Uint8List? get qrImageBytes {
    final raw = qrCodeBase64;
    if (raw == null) return null;
    try {
      return base64Decode(raw.split(',').last);
    } catch (_) {
      return null;
    }
  }
}
