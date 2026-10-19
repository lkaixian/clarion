// Patient-facing billing models (GET /payments/my-bills, /payments/receipts/...).
// All amounts are integer cents, exactly as the server sends them.

String formatRm(int cents) => 'RM ${(cents / 100).toStringAsFixed(2)}';

/// "25", "25.5", "25.50" -> cents. Anything else (empty, zero, more than 2
/// decimals, negative, text) -> null. Never uses floating point.
int? parseRmToCents(String text) {
  final m = RegExp(r'^(\d+)(?:\.(\d{1,2}))?$').firstMatch(text.trim());
  if (m == null) return null;
  final cents = int.parse(m.group(1)!) * 100 + int.parse((m.group(2) ?? '').padRight(2, '0'));
  return cents > 0 ? cents : null;
}

class BillLine {
  const BillLine({required this.description, required this.quantity, required this.amountCents});
  final String description;
  final int quantity;
  final int amountCents;

  factory BillLine.fromJson(Map<String, dynamic> j) => BillLine(
        description: j['description'] as String? ?? '',
        quantity: (j['quantity'] as num?)?.toInt() ?? 1,
        amountCents: (j['amount_cents'] as num?)?.toInt() ?? 0,
      );
}

class PaymentIntent {
  const PaymentIntent({
    required this.id,
    required this.amountCents,
    required this.status,
    required this.simulated,
    this.paymentId,
    this.failureReason,
    this.checkoutUrl,
  });
  final String id;
  final int amountCents;
  final String status; // pending | succeeded | failed | cancelled | expired
  final bool simulated;
  final String? paymentId;
  final String? failureReason;
  final String? checkoutUrl; // hosted payment page (real gateway); null for the simulated one

  factory PaymentIntent.fromJson(Map<String, dynamic> j) => PaymentIntent(
        id: j['id'] as String,
        amountCents: (j['amount_cents'] as num).toInt(),
        status: j['status'] as String,
        simulated: j['simulated'] as bool? ?? false,
        paymentId: j['payment_id'] as String?,
        failureReason: j['failure_reason'] as String?,
        checkoutUrl: j['checkout_url'] as String?,
      );
}

class PatientBill {
  const PatientBill({
    required this.id,
    required this.facilityName,
    required this.totalCents,
    required this.paidCents,
    required this.claimedPendingCents,
    required this.amountDueCents,
    required this.patientDueCents,
    required this.items,
    this.finalizedAt,
    this.pendingIntent,
  });
  final String id;
  final String facilityName;
  final DateTime? finalizedAt;
  final int totalCents;
  final int paidCents;
  final int claimedPendingCents;
  final int amountDueCents;
  final int patientDueCents;
  final List<BillLine> items;
  final PaymentIntent? pendingIntent;

  bool get payable => patientDueCents > 0;

  factory PatientBill.fromJson(Map<String, dynamic> j) => PatientBill(
        id: j['id'] as String,
        facilityName: j['facility_name'] as String? ?? '',
        finalizedAt: DateTime.tryParse(j['finalized_at'] as String? ?? '')?.toLocal(),
        totalCents: (j['total_cents'] as num?)?.toInt() ?? 0,
        paidCents: (j['paid_cents'] as num?)?.toInt() ?? 0,
        claimedPendingCents: (j['claimed_pending_cents'] as num?)?.toInt() ?? 0,
        amountDueCents: (j['amount_due_cents'] as num?)?.toInt() ?? 0,
        patientDueCents: (j['patient_due_cents'] as num?)?.toInt() ?? 0,
        items: ((j['items'] as List<dynamic>?) ?? const [])
            .map((e) => BillLine.fromJson(e as Map<String, dynamic>))
            .toList(),
        pendingIntent: j['pending_intent'] == null
            ? null
            : PaymentIntent.fromJson(j['pending_intent'] as Map<String, dynamic>),
      );
}

class PaymentReceipt {
  const PaymentReceipt({
    required this.paymentId,
    required this.receiptNo,
    required this.facilityName,
    required this.amountCents,
    required this.method,
    required this.billBalanceAfterCents,
    required this.billTotalCents,
    required this.items,
    this.referenceNo,
    this.receivedAt,
    this.refundedCents = 0,
    this.voided = false,
  });
  final String paymentId;
  final String receiptNo;
  final String facilityName;
  final int amountCents;
  final String method;
  final String? referenceNo;
  final DateTime? receivedAt;
  final int refundedCents;
  final bool voided;
  final int billBalanceAfterCents;
  final int billTotalCents;
  final List<BillLine> items;

  factory PaymentReceipt.fromJson(Map<String, dynamic> j) => PaymentReceipt(
        paymentId: j['payment_id'] as String? ?? '',
        receiptNo: j['receipt_no'] as String? ?? '',
        facilityName: j['facility_name'] as String? ?? '',
        amountCents: (j['amount_cents'] as num?)?.toInt() ?? 0,
        method: j['method'] as String? ?? '',
        referenceNo: j['reference_no'] as String?,
        receivedAt: DateTime.tryParse(j['received_at'] as String? ?? '')?.toLocal(),
        refundedCents: (j['refunded_cents'] as num?)?.toInt() ?? 0,
        voided: j['voided'] as bool? ?? false,
        billBalanceAfterCents: (j['bill_balance_after_cents'] as num?)?.toInt() ?? 0,
        billTotalCents: (j['bill_total_cents'] as num?)?.toInt() ?? 0,
        items: ((j['items'] as List<dynamic>?) ?? const [])
            .map((e) => BillLine.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

class PaymentHistoryEntry {
  const PaymentHistoryEntry({
    required this.paymentId,
    required this.amountCents,
    required this.method,
    required this.facilityName,
    required this.receiptNo,
    this.receivedAt,
  });
  final String paymentId;
  final int amountCents;
  final String method;
  final String facilityName;
  final String receiptNo;
  final DateTime? receivedAt;

  factory PaymentHistoryEntry.fromJson(Map<String, dynamic> j) => PaymentHistoryEntry(
        paymentId: j['payment_id'] as String,
        amountCents: (j['amount_cents'] as num).toInt(),
        method: j['method'] as String? ?? '',
        facilityName: j['facility_name'] as String? ?? '',
        receiptNo: j['receipt_no'] as String? ?? '',
        receivedAt: DateTime.tryParse(j['received_at'] as String? ?? '')?.toLocal(),
      );
}
