import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/patient_provider.dart';
import '../providers/reminders_provider.dart';
import '../services/mysejahtera_launcher.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

/// Derives medication reminders directly from the patient's structured
/// record (active medications become dose reminders), and schedules **real
/// local notifications** for them via [RemindersProvider] /
/// flutter_local_notifications — not just a static list. Also supports
/// user-added appointment reminders (purely local; the backend has no
/// appointments concept in this MVP) and a best-effort deep link out to
/// MySejahtera to actually book one.
class RemindersScreen extends StatefulWidget {
  const RemindersScreen({super.key});

  @override
  State<RemindersScreen> createState() => _RemindersScreenState();
}

class _RemindersScreenState extends State<RemindersScreen> with WidgetsBindingObserver {
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
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Re-checks permission status when the user comes back from the
    // system Settings screen (see "Open Settings" flow below) — otherwise
    // the banner would keep showing stale "denied" state even after the
    // user actually granted it there.
    if (state == AppLifecycleState.resumed && mounted) {
      context.read<RemindersProvider>().ensurePermissionRequested();
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
      SnackBar(content: Text(ok ? l10n.testNotificationSentSnack : l10n.testNotificationFailedSnack)),
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
                decoration: InputDecoration(labelText: l10n.appointmentLabelField),
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
                    picked = DateTime(date.year, date.month, date.day, time.hour, time.minute);
                  });
                },
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: Text(MaterialLocalizations.of(dialogContext).cancelButtonLabel),
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
    if (confirmed == true && picked != null && titleController.text.trim().isNotEmpty) {
      await context.read<RemindersProvider>().addAppointment(titleController.text.trim(), picked!);
    }
  }

  Future<void> _openMySejahtera() async {
    final l10n = AppLocalizations.of(context);
    final ok = await MySejahteraLauncher.open();
    if (!mounted) return;
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l10n.mySejahteraLaunchFailed)));
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
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                if (remindersState.isLoaded && !remindersState.notificationsGranted)
                  Container(
                    margin: const EdgeInsets.only(bottom: 16),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppColors.emergencyBg,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.notifications_off_outlined, color: AppColors.emergency, size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            remindersState.notificationsPermanentlyDenied
                                ? l10n.notificationsPermanentlyDeniedNote
                                : l10n.notificationsDisabledNote,
                            style: const TextStyle(fontSize: 12, color: AppColors.emergency),
                          ),
                        ),
                        TextButton(
                          onPressed: remindersState.notificationsPermanentlyDenied
                              ? () => context.read<RemindersProvider>().openNotificationSettings()
                              : () => context.read<RemindersProvider>().ensurePermissionRequested(),
                          child: Text(
                            remindersState.notificationsPermanentlyDenied ? l10n.openAppSettings : l10n.enableAction,
                          ),
                        ),
                      ],
                    ),
                  ),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _sendTestNotification,
                    icon: const Icon(Icons.notifications_active_outlined, size: 18),
                    label: Text(l10n.sendTestNotification),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.primary,
                      padding: const EdgeInsets.all(12),
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Text(l10n.medicationsSection,
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
                const SizedBox(height: 8),
                if (patient == null || patient.activeMedications.isEmpty)
                  Text(l10n.noActiveMedsRecord, style: const TextStyle(fontSize: 13, color: AppColors.textFaint))
                else
                  ...patient.activeMedications.map((m) {
                    final enabled = remindersState.isMedicationReminderEnabled(m.drugName);
                    final doseFreq = [m.dosage, m.frequency]
                        .where((p) => p != null && p.trim().isNotEmpty)
                        .join(', ');
                    return Container(
                      margin: const EdgeInsets.only(bottom: 10),
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppColors.border),
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('💊 ${m.drugName}',
                                    style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15, color: AppColors.textPrimary)),
                                const SizedBox(height: 2),
                                Text(l10n.prescribedBy(m.prescribedByFacility ?? l10n.unknownFacility),
                                    style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                                Text(doseFreq.isNotEmpty ? doseFreq : l10n.suggestedReminder,
                                    style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                              ],
                            ),
                          ),
                          Switch(
                            value: enabled,
                            onChanged: (value) =>
                                context.read<RemindersProvider>().setMedicationReminderEnabled(m.drugName, value),
                          ),
                        ],
                      ),
                    );
                  }),
                const SizedBox(height: 20),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(l10n.upcomingAppointments,
                        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
                    TextButton.icon(
                      onPressed: _addAppointment,
                      icon: const Icon(Icons.add, size: 18),
                      label: Text(l10n.addAppointmentAction),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                if (remindersState.appointments.isEmpty)
                  Text(l10n.noAppointments, style: const TextStyle(fontSize: 13, color: AppColors.textFaint))
                else
                  ...remindersState.appointments.map((a) => Container(
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: AppColors.border),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.event_outlined, color: AppColors.primary, size: 20),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(a.title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14, color: AppColors.textPrimary)),
                                  Text(DateFormat('d MMM yyyy, h:mm a').format(a.dateTime),
                                      style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                                ],
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, size: 20, color: AppColors.textFaint),
                              onPressed: () => context.read<RemindersProvider>().removeAppointment(a.id),
                            ),
                          ],
                        ),
                      )),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _openMySejahtera,
                    icon: const Text('📅'),
                    label: Text(l10n.bookViaMySejahtera),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: AppColors.chipBg,
                      foregroundColor: AppColors.primary,
                      padding: const EdgeInsets.all(14),
                      side: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 6),
                Text(l10n.mySejahteraNote, style: const TextStyle(fontSize: 11, color: AppColors.textFaint)),
              ],
            ),
    );
  }
}
