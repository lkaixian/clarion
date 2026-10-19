import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/bill.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

String _newKey() {
  final r = Random.secure();
  return List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}

/// The patient's own finalized bills, online payment (simulated gateway on a
/// demo node) and receipts. Every figure comes from the server; nothing is
/// computed here beyond display formatting.
class MyBillsScreen extends StatefulWidget {
  const MyBillsScreen({super.key});

  @override
  State<MyBillsScreen> createState() => _MyBillsScreenState();
}

class _MyBillsScreenState extends State<MyBillsScreen> {
  List<PatientBill>? _bills;
  List<PaymentHistoryEntry> _history = const [];
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    setState(() => _error = null);
    try {
      final bills = await api.getMyBills();
      final history = await api.getMyPaymentHistory();
      if (!mounted) return;
      setState(() {
        _bills = bills;
        _history = history;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _showReceipt(String paymentId) async {
    try {
      final r = await context.read<ApiClient>().getReceipt(paymentId);
      if (!mounted) return;
      await showDialog<void>(context: context, builder: (_) => _ReceiptDialog(receipt: r));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _pay(PatientBill bill) async {
    final receipt = await showModalBottomSheet<PaymentReceipt>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _CheckoutSheet(bill: bill),
    );
    await _load();
    if (receipt != null && mounted) {
      await showDialog<void>(context: context, builder: (_) => _ReceiptDialog(receipt: receipt));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final bills = _bills;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.myBills)),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(_error!, textAlign: TextAlign.center),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _load, child: Text(l10n.retry)),
                ]),
              ),
            )
          : bills == null
              ? const LoadingView()
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      if (bills.isEmpty) Padding(padding: const EdgeInsets.all(24), child: Center(child: Text(l10n.billsEmpty))),
                      for (final b in bills) _BillCard(bill: b, onPay: () => _pay(b)),
                      if (_history.isNotEmpty) ...[
                        const SizedBox(height: 16),
                        Text(l10n.paymentHistory, style: Theme.of(context).textTheme.titleSmall),
                        for (final h in _history)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text('${formatRm(h.amountCents)} · ${h.method}'),
                            subtitle: Text(h.facilityName),
                            trailing: Text(h.receiptNo, style: TextStyle(color: context.palette.textMuted)),
                            onTap: () => _showReceipt(h.paymentId),
                          ),
                      ],
                    ],
                  ),
                ),
    );
  }
}

class _BillCard extends StatelessWidget {
  const _BillCard({required this.bill, required this.onPay});
  final PatientBill bill;
  final VoidCallback onPay;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final status = bill.payable
        ? l10n.billToPay(formatRm(bill.patientDueCents))
        : bill.amountDueCents > 0
            ? l10n.billInsurerPending
            : l10n.billPaidInFull;
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(bill.facilityName, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(status, key: const Key('bill-status'), style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 8),
          Text('${formatRm(bill.totalCents)} total · ${formatRm(bill.paidCents)} paid',
              style: TextStyle(color: context.palette.textMuted)),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text(l10n.billItems),
            children: [
              for (final i in bill.items)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(i.quantity > 1 ? '${i.description} x${i.quantity}' : i.description),
                  trailing: Text(formatRm(i.amountCents)),
                ),
            ],
          ),
          if (bill.payable)
            SizedBox(
              width: double.infinity,
              child: FilledButton(onPressed: onPay, child: Text(l10n.payNow)),
            ),
        ]),
      ),
    );
  }
}

/// Amount -> gateway -> result, in one bottom sheet. Pops the receipt on success.
class _CheckoutSheet extends StatefulWidget {
  const _CheckoutSheet({required this.bill});
  final PatientBill bill;

  @override
  State<_CheckoutSheet> createState() => _CheckoutSheetState();
}

class _CheckoutSheetState extends State<_CheckoutSheet> {
  late final TextEditingController _amount =
      TextEditingController(text: (widget.bill.patientDueCents / 100).toStringAsFixed(2));
  PaymentIntent? _intent;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _intent = widget.bill.pendingIntent;
  }

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final l10n = AppLocalizations.of(context);
    final cents = parseRmToCents(_amount.text);
    if (cents == null) return setState(() => _error = l10n.payInvalidAmount);
    if (cents > widget.bill.patientDueCents) {
      return setState(() => _error = l10n.payTooMuch(formatRm(widget.bill.patientDueCents)));
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final i = await context.read<ApiClient>().createPaymentIntent(widget.bill.id, cents, _newKey());
      if (mounted) setState(() => _intent = i);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finish(String outcome) async {
    final l10n = AppLocalizations.of(context);
    final api = context.read<ApiClient>();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final done = await api.simulatePayment(_intent!.id, outcome);
      if (done.status == 'succeeded' && done.paymentId != null) {
        final receipt = await api.getReceipt(done.paymentId!);
        if (mounted) Navigator.of(context).pop(receipt);
      } else if (mounted) {
        setState(() {
          _intent = null;
          _error = l10n.payDeclined(done.failureReason ?? '');
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _cancel() async {
    final api = context.read<ApiClient>();
    final nav = Navigator.of(context);
    final i = _intent;
    if (i != null) {
      try {
        await api.cancelPaymentIntent(i.id);
      } on ApiException {
        // already closed server-side: nothing to undo
      }
    }
    nav.pop();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final intent = _intent;
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(widget.bill.facilityName, style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 12),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(_error!, key: const Key('pay-error'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ),
        if (intent == null) ...[
          TextField(
            key: const Key('pay-amount'),
            controller: _amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(labelText: l10n.payAmountLabel),
          ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: FilledButton(onPressed: _busy ? null : _start, child: Text(l10n.payContinue))),
            const SizedBox(width: 8),
            TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: Text(l10n.cancel)),
          ]),
        ] else ...[
          Text(formatRm(intent.amountCents), style: Theme.of(context).textTheme.headlineSmall),
          if (intent.simulated) ...[
            const SizedBox(height: 8),
            Text(l10n.paySimulatedNotice, key: const Key('sim-notice')),
          ],
          const SizedBox(height: 12),
          if (intent.simulated) ...[
            FilledButton(onPressed: _busy ? null : () => _finish('succeeded'), child: Text(l10n.payApprove)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _busy ? null : () => _finish('failed'), child: Text(l10n.payDecline)),
            const SizedBox(height: 8),
          ],
          TextButton(onPressed: _busy ? null : _cancel, child: Text(l10n.payCancel)),
        ],
      ]),
    );
  }
}

class _ReceiptDialog extends StatefulWidget {
  const _ReceiptDialog({required this.receipt});
  final PaymentReceipt receipt;

  @override
  State<_ReceiptDialog> createState() => _ReceiptDialogState();
}

class _ReceiptDialogState extends State<_ReceiptDialog> {
  bool _busy = false;
  String? _note;
  bool _noteIsError = false;

  Future<void> _run(Future<String?> Function(ApiClient api) job) async {
    final api = context.read<ApiClient>();
    setState(() {
      _busy = true;
      _note = null;
    });
    try {
      final done = await job(api);
      if (mounted) setState(() => _note = done);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _note = e.message;
          _noteIsError = true;
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _email() {
    final l10n = AppLocalizations.of(context);
    return _run((api) async {
      _noteIsError = false;
      return l10n.receiptEmailSent(await api.emailReceipt(widget.receipt.paymentId));
    });
  }

  Future<void> _sharePdf() => _run((api) async {
        _noteIsError = false;
        final bytes = await api.getReceiptPdfBytes(widget.receipt.paymentId);
        final dir = await Directory.systemTemp.createTemp('clarion_pdf');
        final file = File('${dir.path}/receipt-${widget.receipt.receiptNo}.pdf');
        await file.writeAsBytes(bytes);
        await Share.shareXFiles([XFile(file.path)]);
        return null;
      });

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final receipt = widget.receipt;
    return AlertDialog(
      title: Text(l10n.receiptTitle(receipt.receiptNo)),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(receipt.facilityName),
          const SizedBox(height: 8),
          Text('${formatRm(receipt.amountCents)} · ${receipt.method}',
              style: Theme.of(context).textTheme.titleMedium),
          if (receipt.referenceNo != null) Text(receipt.referenceNo!),
          if (receipt.refundedCents > 0) Text('Refunded ${formatRm(receipt.refundedCents)}'),
          if (receipt.voided) Text(l10n.receiptVoided),
          const Divider(),
          for (final i in receipt.items)
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Flexible(child: Text(i.quantity > 1 ? '${i.description} x${i.quantity}' : i.description)),
              Text(formatRm(i.amountCents)),
            ]),
          const Divider(),
          Text('${formatRm(receipt.billTotalCents)} total · balance ${formatRm(receipt.billBalanceAfterCents)}'),
          if (_note != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_note!,
                  key: const Key('receipt-note'),
                  style: _noteIsError ? TextStyle(color: Theme.of(context).colorScheme.error) : null),
            ),
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : _sharePdf, child: Text(l10n.receiptSharePdf)),
        TextButton(onPressed: _busy ? null : _email, child: Text(l10n.receiptEmail)),
        TextButton(onPressed: () => Navigator.of(context).pop(), child: Text(l10n.close)),
      ],
    );
  }
}
