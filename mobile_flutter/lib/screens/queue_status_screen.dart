import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/queue_ticket.dart';
import '../providers/auth_provider.dart';
import '../providers/queue_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';
import '../widgets/section_card.dart';
import '../widgets/record_widgets.dart';

// No "serving" status -- only waiting|called|done|cancelled are ever set
// server-side (see backend schemas.VALID_QUEUE_TICKET_STATUSES); a ticket
// goes straight from "called" to "done" with no intermediate state.
String _statusLabel(AppLocalizations l10n, String status) {
  switch (status) {
    case 'waiting':
      return l10n.queueStatusWaiting;
    case 'called':
      return l10n.queueStatusCalled;
    case 'done':
      return l10n.queueStatusDone;
    case 'cancelled':
      return l10n.queueStatusCancelled;
    default:
      return status;
  }
}

class QueueStatusScreen extends StatefulWidget {
  const QueueStatusScreen({super.key, this.active = true, this.onScan});

  /// False while another shell tab is showing: polling pauses.
  final bool active;

  /// Opens the scan hub from the "no ticket" state; hidden when null.
  final VoidCallback? onScan;

  @override
  State<QueueStatusScreen> createState() => _QueueStatusScreenState();
}

class _QueueStatusScreenState extends State<QueueStatusScreen> {
  // Cached rather than looked up via `context.read` inside dispose() —
  // Provider explicitly disallows using `context` at that point (same
  // reasoning/pattern as EmergencyScreen's `_patientProvider` field).
  QueueProvider? _queueProvider;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _queueProvider = context.read<QueueProvider>();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _syncPolling());
  }

  @override
  void didUpdateWidget(QueueStatusScreen old) {
    super.didUpdateWidget(old);
    if (old.active != widget.active) _syncPolling();
  }

  void _syncPolling() {
    if (!mounted) return;
    if (!widget.active) {
      _queueProvider?.stopPolling();
      return;
    }
    final patientId = context.read<AuthProvider>().user?.patientId;
    if (patientId != null) context.read<QueueProvider>().startPolling(patientId);
  }

  @override
  void dispose() {
    _queueProvider?.stopPolling();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final queueState = context.watch<QueueProvider>();
    final patientId = context.watch<AuthProvider>().user?.patientId;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.queueStatusTitle)),
      body: Builder(
        builder: (context) {
          if (patientId == null) {
            return const NoRecordNotice();
          }
          if (queueState.isLoading && !queueState.status.active && queueState.error == null) {
            return const LoadingView();
          }
          if (queueState.error != null && !queueState.status.active) {
            return Padding(
              padding: const EdgeInsets.all(24),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.error_outline, color: context.palette.emergency, size: 40),
                    const SizedBox(height: 12),
                    Text(
                      queueState.error!,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: context.palette.textBody),
                    ),
                    const SizedBox(height: 16),
                    ElevatedButton(
                      onPressed: () => context.read<QueueProvider>().refresh(patientId),
                      child: Text(l10n.retry),
                    ),
                  ],
                ),
              ),
            );
          }

          if (!queueState.status.active) {
            return _EmptyQueueState(l10n: l10n, onScan: widget.onScan);
          }

          final QueueTicket ticket = queueState.status.ticket!;
          final nowServing = queueState.status.nowServing;
          final peopleAhead = queueState.status.peopleAhead ?? 0;

          return RefreshIndicator(
            onRefresh: () => context.read<QueueProvider>().refresh(patientId),
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: context.palette.primary,
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Column(
                    children: [
                      Text(
                        l10n.yourNumberLabel(ticket.queueNumber.toString()),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                        ),
                      ),
                      Text(
                        '${ticket.queueNumber}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 48,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        nowServing != null
                            ? l10n.nowServingLabel(nowServing.toString())
                            : l10n.nowServingNoneYet,
                        style: const TextStyle(color: Colors.white, fontSize: 15),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        l10n.peopleAheadLabel(peopleAhead.toString()),
                        style: const TextStyle(color: Colors.white70, fontSize: 13),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: l10n.queueTicketDetailsTitle,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _DetailLine(
                        label: l10n.queueStatusLabel,
                        value: _statusLabel(l10n, ticket.status),
                      ),
                      _DetailLine(
                        label: l10n.queueFacilityLabel,
                        value: ticket.facilityName,
                      ),
                      if (ticket.department != null && ticket.department!.trim().isNotEmpty)
                        _DetailLine(
                          label: l10n.queueDepartmentLabel,
                          value: ticket.department!,
                        ),
                      if (ticket.reason != null && ticket.reason!.trim().isNotEmpty)
                        _DetailLine(
                          label: l10n.queueReasonLabel,
                          value: ticket.reason!,
                        ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _DetailLine extends StatelessWidget {
  const _DetailLine({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 110,
            child: Text(
              label,
              style: TextStyle(fontSize: 13, color: context.palette.textMuted),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(fontSize: 13, color: context.palette.textBody),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyQueueState extends StatelessWidget {
  const _EmptyQueueState({required this.l10n, this.onScan});
  final AppLocalizations l10n;
  final VoidCallback? onScan;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.confirmation_number_outlined, color: context.palette.textFaint, size: 48),
            const SizedBox(height: 12),
            Text(
              l10n.noActiveQueueTicketTitle,
              textAlign: TextAlign.center,
              style: TextStyle(fontWeight: FontWeight.bold, color: context.palette.textPrimary, fontSize: 16),
            ),
            const SizedBox(height: 8),
            Text(
              l10n.noActiveQueueTicketDesc,
              textAlign: TextAlign.center,
              style: TextStyle(color: context.palette.textMuted, fontSize: 13),
            ),
            if (onScan != null) ...[
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: onScan,
                  icon: const Icon(Icons.qr_code_scanner),
                  label: Text(l10n.scanCheckinButton),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
