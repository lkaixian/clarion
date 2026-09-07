import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/server_appointment.dart';
import '../providers/patient_provider.dart';
import '../providers/reminders_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/mysejahtera_launcher.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

/// Derives medication reminders directly from the patient's structured
/// record (active medications become dose reminders), and schedules **real
/// local notifications** for them via [RemindersProvider] /
/// flutter_local_notifications — not just a static list. Also supports
/// user-added appointment reminders (purely local — there's still no way to
/// create/edit one from this app) and a best-effort deep link out to
/// MySejahtera to actually book one. Separately, now also displays
/// clinic-published appointments synced from the backend (see
/// [RemindersProvider.syncServerAppointments] /
/// [RemindersProvider.serverAppointments]) — read-only, staff-owned data,
/// rendered in its own visually distinct section above the self-added list.
class RemindersScreen extends StatefulWidget {
  const RemindersScreen({super.key});

  @override
  State<RemindersScreen> createState() => _RemindersScreenState();
}

class _RemindersScreenState extends State<RemindersScreen>
    with WidgetsBindingObserver {
  // Cached rather than looked up via `context.read` inside dispose() —
  // Provider explicitly disallows using `context` at that point (same
  // pattern as PatientProvider's card-polling screens).
  RemindersProvider? _remindersProvider;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _remindersProvider = context.read<RemindersProvider>();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      final reminders = context.read<RemindersProvider>();
      await reminders.load();
      await reminders.ensurePermissionRequested();
      if (!mounted) return;
      final patient = context.read<PatientProvider>().patient;
      if (patient != null) {
        await reminders.syncWithActiveMedications(patient.activeMedications);
        if (!mounted) return;
        // FIX for "web-published appointments never show up / update in
        // the app": a single sync on screen-open isn't enough — start
        // polling so an appointment published/edited/cancelled from the
        // web console while this screen stays open actually appears
        // without the user having to leave and come back.
        reminders.startAppointmentPolling(
          patient.id,
          context.read<ApiClient>(),
        );
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _remindersProvider?.stopAppointmentPolling();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Re-checks permission status when the user comes back from the
    // system Settings screen (see "Open Settings" flow below) — otherwise
    // the banner would keep showing stale "denied" state even after the
    // user actually granted it there. Also gives appointments an
    // immediate refresh on resume rather than waiting for the next poll
    // tick, consistent with this same resumed-refresh pattern.
    if (state == AppLifecycleState.resumed && mounted) {
      final reminders = context.read<RemindersProvider>();
      reminders.ensurePermissionRequested();
      final patient = context.read<PatientProvider>().patient;
      if (patient != null) {
        reminders.syncServerAppointments(patient.id, context.read<ApiClient>());
      }
    }
  }

  Future<void> _sendTestNotification() async {
    final l10n = AppLocalizations.of(context);
    final ok = await context.read<RemindersProvider>().sendTestNotification(
      title: l10n.testNotificationTitle,
      body: l10n.testNotificationBody,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          ok
              ? l10n.testNotificationSentSnack
              : l10n.testNotificationFailedSnack,
        ),
      ),
    );
  }

  Future<void> _addAppointment() async {
    final l10n = AppLocalizations.of(context);
    final titleController = TextEditingController();
    DateTime? picked;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: Text(l10n.addAppointmentTitle),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: titleController,
                decoration: InputDecoration(
                  labelText: l10n.appointmentLabelField,
                ),
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                icon: const Icon(Icons.calendar_month),
                label: Text(
                  picked == null
                      ? l10n.pickDateTime
                      : DateFormat('d MMM yyyy, h:mm a').format(picked!),
                ),
                onPressed: () async {
                  final now = DateTime.now();
                  final date = await showDatePicker(
                    context: dialogContext,
                    initialDate: now,
                    firstDate: now,
                    lastDate: now.add(const Duration(days: 730)),
                  );
                  if (date == null) return;
                  if (!dialogContext.mounted) return;
                  final time = await showTimePicker(
                    context: dialogContext,
                    initialTime: TimeOfDay.fromDateTime(now),
                  );
                  if (time == null) return;
                  setDialogState(() {
                    picked = DateTime(
                      date.year,
                      date.month,
                      date.day,
                      time.hour,
                      time.minute,
                    );
                  });
                },
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: Text(
                MaterialLocalizations.of(dialogContext).cancelButtonLabel,
              ),
            ),
            FilledButton(
              onPressed: titleController.text.trim().isEmpty || picked == null
                  ? null
                  : () => Navigator.of(dialogContext).pop(true),
              child: Text(l10n.save),
            ),
          ],
        ),
      ),
    );

    if (!mounted) return;
    if (confirmed == true &&
        picked != null &&
        titleController.text.trim().isNotEmpty) {
      await context.read<RemindersProvider>().addAppointment(
        titleController.text.trim(),
        picked!,
      );
    }
  }

  Future<void> _openMySejahtera() async {
    final l10n = AppLocalizations.of(context);
    final ok = await MySejahteraLauncher.open();
    if (!mounted) return;
    if (!ok) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l10n.mySejahteraLaunchFailed)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final remindersState = context.watch<RemindersProvider>();
    final patient = patientState.patient;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.remindersTitle)),
      body: patientState.isLoadingRecord && patient == null
          ? const LoadingView()
          : RefreshIndicator(
              // Manual pull-to-refresh on top of the periodic background
              // poll started in initState — same "give the user an
              // explicit way to force a refresh, not just wait" pattern as
              // HomeScreen's RefreshIndicator.
              onRefresh: () async {
                if (patient != null) {
                  await context
                      .read<RemindersProvider>()
                      .syncServerAppointments(
                        patient.id,
                        context.read<ApiClient>(),
                      );
                }
              },
              child: ListView(
                padding: const EdgeInsets.all(20),
                children: [
                  if (remindersState.isLoaded &&
                      !remindersState.notificationsGranted)
                    Container(
                      margin: const EdgeInsets.only(bottom: 16),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: context.palette.emergencyBg,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Row(
                        children: [
                          Icon(
                            Icons.notifications_off_outlined,
                            color: context.palette.emergency,
                            size: 20,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Text(
                              remindersState.notificationsPermanentlyDenied
                                  ? l10n.notificationsPermanentlyDeniedNote
                                  : l10n.notificationsDisabledNote,
                              style: TextStyle(
                                fontSize: 12,
                                color: context.palette.emergency,
                              ),
                            ),
                          ),
                          TextButton(
                            onPressed:
                                remindersState.notificationsPermanentlyDenied
                                ? () => context
                                      .read<RemindersProvider>()
                                      .openNotificationSettings()
                                : () => context
                                      .read<RemindersProvider>()
                                      .ensurePermissionRequested(),
                            child: Text(
                              remindersState.notificationsPermanentlyDenied
                                  ? l10n.openAppSettings
                                  : l10n.enableAction,
                            ),
                          ),
                        ],
                      ),
                    ),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _sendTestNotification,
                      icon: const Icon(
                        Icons.notifications_active_outlined,
                        size: 18,
                      ),
                      label: Text(l10n.sendTestNotification),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: context.palette.primary,
                        padding: const EdgeInsets.all(12),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    l10n.medicationsSection,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: context.palette.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  if (patient == null || patient.activeMedications.isEmpty)
                    Text(
                      l10n.noActiveMedsRecord,
                      style: TextStyle(
                        fontSize: 13,
                        color: context.palette.textFaint,
                      ),
                    )
                  else
                    ...patient.activeMedications.map((m) {
                      final enabled = remindersState
                          .isMedicationReminderEnabled(m.drugName);
                      final doseFreq = [m.dosage, m.frequency]
                          .where((p) => p != null && p.trim().isNotEmpty)
                          .join(', ');
                      return Container(
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: context.palette.surface,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: context.palette.border),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '💊 ${m.drugName}',
                                    style: TextStyle(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 15,
                                      color: context.palette.textPrimary,
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    l10n.prescribedBy(
                                      m.prescribedByFacility ??
                                          l10n.unknownFacility,
                                    ),
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: context.palette.textMuted,
                                    ),
                                  ),
                                  Text(
                                    doseFreq.isNotEmpty
                                        ? doseFreq
                                        : l10n.suggestedReminder,
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: context.palette.textMuted,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Switch(
                              value: enabled,
                              onChanged: (value) => context
                                  .read<RemindersProvider>()
                                  .setMedicationReminderEnabled(
                                    m.drugName,
                                    value,
                                  ),
                            ),
                          ],
                        ),
                      );
                    }),
                  const SizedBox(height: 20),
                  // Clinic-published appointments (server-owned, read-only for
                  // the patient) — deliberately rendered ABOVE and visually
                  // distinct from the patient's own self-added appointments
                  // below: no delete/edit affordance at all, since staff (not
                  // the patient) own this data. Only ever shows `scheduled`
                  // ones — a cancelled server appointment is omitted entirely
                  // here rather than shown de-emphasized like the web
                  // console's staff-facing history view, since this screen is
                  // action-oriented, not a historical record.
                  Text(
                    l10n.clinicAppointmentsSection,
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: context.palette.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Builder(
                    builder: (context) {
                      final upcoming = remindersState.serverAppointments
                          .where((a) => a.status == 'scheduled')
                          .toList();
                      if (upcoming.isEmpty) {
                        return Text(
                          l10n.noClinicAppointments,
                          style: TextStyle(
                            fontSize: 13,
                            color: context.palette.textFaint,
                          ),
                        );
                      }
                      return Column(
                        children: upcoming
                            .map(
                              (a) => _ClinicAppointmentCard(
                                appointment: a,
                                l10n: l10n,
                                onRescheduleRequested: () {
                                  if (patient != null) {
                                    context.read<RemindersProvider>().syncServerAppointments(
                                          patient.id,
                                          context.read<ApiClient>(),
                                        );
                                  }
                                },
                              ),
                            )
                            .toList(),
                      );
                    },
                  ),
                  const SizedBox(height: 20),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        l10n.upcomingAppointments,
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: context.palette.textPrimary,
                        ),
                      ),
                      TextButton.icon(
                        onPressed: _addAppointment,
                        icon: const Icon(Icons.add, size: 18),
                        label: Text(l10n.addAppointmentAction),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  if (remindersState.appointments.isEmpty)
                    Text(
                      l10n.noAppointments,
                      style: TextStyle(
                        fontSize: 13,
                        color: context.palette.textFaint,
                      ),
                    )
                  else
                    ...remindersState.appointments.map(
                      (a) => Container(
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: context.palette.surface,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: context.palette.border),
                        ),
                        child: Row(
                          children: [
                            Icon(
                              Icons.event_outlined,
                              color: context.palette.primary,
                              size: 20,
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    a.title,
                                    style: TextStyle(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 14,
                                      color: context.palette.textPrimary,
                                    ),
                                  ),
                                  Text(
                                    DateFormat(
                                      'd MMM yyyy, h:mm a',
                                    ).format(a.dateTime),
                                    style: TextStyle(
                                      fontSize: 12,
                                      color: context.palette.textMuted,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            IconButton(
                              icon: Icon(
                                Icons.delete_outline,
                                size: 20,
                                color: context.palette.textFaint,
                              ),
                              onPressed: () => context
                                  .read<RemindersProvider>()
                                  .removeAppointment(a.id),
                            ),
                          ],
                        ),
                      ),
                    ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _openMySejahtera,
                      icon: const Text('📅'),
                      label: Text(l10n.bookViaMySejahtera),
                      style: OutlinedButton.styleFrom(
                        backgroundColor: context.palette.chipBg,
                        foregroundColor: context.palette.primary,
                        padding: const EdgeInsets.all(14),
                        side: BorderSide.none,
                      ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    l10n.mySejahteraNote,
                    style: TextStyle(
                      fontSize: 11,
                      color: context.palette.textFaint,
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}

/// One clinic-published appointment card. Deliberately styled to read as
/// "official" rather than "just another list item" — a filled, tinted
/// background (vs. the plain white cards used for the patient's own
/// self-added appointments below it) and a small "set by your clinic" tag
/// instead of a delete icon, since there is no affordance to edit/remove
/// this data from the app at all (it's staff-owned).
class _ClinicAppointmentCard extends StatelessWidget {
  const _ClinicAppointmentCard({
    required this.appointment,
    required this.l10n,
    required this.onRescheduleRequested,
  });

  final ServerAppointment appointment;
  final AppLocalizations l10n;

  /// Called after a reschedule request is successfully submitted, so the
  /// caller can re-sync [RemindersProvider.serverAppointments] and this
  /// card picks up the new pending state.
  final VoidCallback onRescheduleRequested;

  @override
  Widget build(BuildContext context) {
    final venue = appointment.venue;
    final reason = appointment.reason;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: context.palette.chipBg.withValues(alpha: 0.35),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: context.palette.primaryLight),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.local_hospital_outlined,
                color: context.palette.primary,
                size: 20,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      venue != null && venue.trim().isNotEmpty
                          ? '${appointment.facilityName} — $venue'
                          : appointment.facilityName,
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 14,
                        color: context.palette.textPrimary,
                      ),
                    ),
                    Text(
                      DateFormat(
                        'd MMM yyyy, h:mm a',
                      ).format(appointment.scheduledAt),
                      style: TextStyle(
                        fontSize: 12,
                        color: context.palette.textMuted,
                      ),
                    ),
                    if (reason != null && reason.trim().isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        l10n.appointmentReasonLabel(reason),
                        style: TextStyle(
                          fontSize: 12,
                          color: context.palette.textMuted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: context.palette.chipBg,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  l10n.clinicAppointmentBadge,
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                    color: context.palette.primary,
                  ),
                ),
              ),
            ],
          ),
          // Fasting-precaution callout — reuses this app's established
          // "critical warning" visual convention (emergencyBg fill,
          // emergency-red icon/text, see the notifications-disabled banner
          // above and EmergencyScannerScreen's allergy card) rather than
          // inventing a new warning style just for this.
          if (appointment.fastingRequired) ...[
            const SizedBox(height: 10),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: context.palette.emergencyBg,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.warning_amber_rounded,
                    color: context.palette.emergency,
                    size: 16,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      appointment.fastingHours != null
                          ? l10n.fastingRequiredNote(appointment.fastingHours!)
                          : l10n.fastingRequiredNoteUnspecified,
                      style: TextStyle(
                        fontSize: 12,
                        color: context.palette.emergency,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
          // Patient-initiated reschedule request UI. Only ever shown for a
          // still-`scheduled` appointment (the parent list already filters
          // to that), reflecting whichever of four states applies:
          // no request yet, a pending one awaiting the clinic, or a
          // resolved (accepted/rejected) one -- and a resolved outcome
          // doesn't block filing a fresh request afterwards.
          _RescheduleSection(appointment: appointment, l10n: l10n, onRescheduleRequested: onRescheduleRequested),
        ],
      ),
    );
  }
}

class _RescheduleSection extends StatelessWidget {
  const _RescheduleSection({
    required this.appointment,
    required this.l10n,
    required this.onRescheduleRequested,
  });

  final ServerAppointment appointment;
  final AppLocalizations l10n;
  final VoidCallback onRescheduleRequested;

  Future<void> _openDialog(BuildContext context) async {
    final submitted = await showDialog<bool>(
      context: context,
      builder: (_) => _RescheduleRequestDialog(appointment: appointment),
    );
    if (submitted == true) onRescheduleRequested();
  }

  @override
  Widget build(BuildContext context) {
    final previous = appointment.previousScheduledAt;
    final latest = appointment.latestRescheduleRequest;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (previous != null) ...[
          const SizedBox(height: 8),
          Text(
            l10n.previouslyScheduledLabel(DateFormat('d MMM yyyy, h:mm a').format(previous)),
            style: TextStyle(fontSize: 11, color: context.palette.textFaint, fontStyle: FontStyle.italic),
          ),
        ],
        const SizedBox(height: 8),
        if (latest != null && latest.status == 'pending')
          Row(
            children: [
              Icon(Icons.hourglass_top, size: 14, color: context.palette.attention),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  l10n.reschedulePendingNote,
                  style: TextStyle(fontSize: 12, color: context.palette.attention, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          )
        else ...[
          if (latest != null && latest.status == 'accepted')
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                children: [
                  Icon(Icons.check_circle_outline, size: 14, color: context.palette.success),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      l10n.rescheduleAcceptedNote,
                      style: TextStyle(fontSize: 12, color: context.palette.success, fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
            ),
          if (latest != null && latest.status == 'rejected')
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.cancel_outlined, size: 14, color: context.palette.emergency),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          l10n.rescheduleRejectedNote,
                          style: TextStyle(fontSize: 12, color: context.palette.emergency, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                  if (latest.clinicianNote != null && latest.clinicianNote!.trim().isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(left: 20, top: 2),
                      child: Text(
                        l10n.rescheduleClinicianNoteLabel(latest.clinicianNote!),
                        style: TextStyle(fontSize: 12, color: context.palette.textMuted),
                      ),
                    ),
                ],
              ),
            ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              style: TextButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size(0, 32)),
              onPressed: () => _openDialog(context),
              icon: const Icon(Icons.event_repeat, size: 16),
              label: Text(l10n.requestRescheduleButton, style: const TextStyle(fontSize: 12)),
            ),
          ),
        ],
      ],
    );
  }
}

const _kRescheduleReasonCodes = [
  'schedule_conflict',
  'unwell_or_cannot_travel',
  'transport_issue',
  'other',
];

String _rescheduleReasonLabel(AppLocalizations l10n, String code) {
  switch (code) {
    case 'schedule_conflict':
      return l10n.rescheduleReasonScheduleConflict;
    case 'unwell_or_cannot_travel':
      return l10n.rescheduleReasonUnwell;
    case 'transport_issue':
      return l10n.rescheduleReasonTransport;
    case 'other':
      return l10n.rescheduleReasonOther;
    default:
      return code;
  }
}

/// The "Request Reschedule" dialog: a radio list of the four patient reason
/// codes, plus a conditional required text field for `other`. Pops `true`
/// on a successful submit (so the caller knows to re-sync
/// [RemindersProvider.serverAppointments]) or `null`/`false` if dismissed.
class _RescheduleRequestDialog extends StatefulWidget {
  const _RescheduleRequestDialog({required this.appointment});

  final ServerAppointment appointment;

  @override
  State<_RescheduleRequestDialog> createState() => _RescheduleRequestDialogState();
}

class _RescheduleRequestDialogState extends State<_RescheduleRequestDialog> {
  String _reasonCode = _kRescheduleReasonCodes.first;
  final _otherController = TextEditingController();
  bool _submitting = false;
  String? _error;
  bool _otherTouched = false;

  @override
  void dispose() {
    _otherController.dispose();
    super.dispose();
  }

  bool get _otherRequired => _reasonCode == 'other';
  bool get _otherInvalid => _otherRequired && _otherController.text.trim().isEmpty;

  Future<void> _submit() async {
    setState(() => _otherTouched = true);
    if (_otherInvalid) return;

    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      await api.requestAppointmentReschedule(
        patientId: widget.appointment.patientId,
        appointmentId: widget.appointment.id,
        reasonCode: _reasonCode,
        reasonOther: _otherRequired ? _otherController.text.trim() : null,
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = AppLocalizations.of(context).unexpectedErrorGeneric);
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.rescheduleDialogTitle),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.rescheduleDialogDesc, style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
            const SizedBox(height: 12),
            RadioGroup<String>(
              groupValue: _reasonCode,
              // RadioGroup.onChanged is non-nullable (unlike the old
              // per-tile RadioListTile.onChanged this replaces) -- disabling
              // while submitting is a no-op guard inside the callback
              // rather than passing null.
              onChanged: (v) {
                if (_submitting || v == null) return;
                setState(() => _reasonCode = v);
              },
              child: Column(
                children: _kRescheduleReasonCodes
                    .map(
                      (code) => RadioListTile<String>(
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        value: code,
                        title: Text(_rescheduleReasonLabel(l10n, code)),
                      ),
                    )
                    .toList(),
              ),
            ),
            if (_otherRequired) ...[
              const SizedBox(height: 4),
              TextField(
                controller: _otherController,
                enabled: !_submitting,
                maxLines: 2,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  labelText: l10n.rescheduleOtherReasonLabel,
                  errorText: _otherTouched && _otherInvalid ? l10n.rescheduleOtherReasonRequired : null,
                ),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: context.palette.emergency, fontSize: 13)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(false),
          child: Text(MaterialLocalizations.of(context).cancelButtonLabel),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: Text(_submitting ? l10n.rescheduleSubmitting : l10n.rescheduleSubmitButton),
        ),
      ],
    );
  }
}
