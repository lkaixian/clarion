import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../providers/reminders_provider.dart';
import '../services/api_client.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/expandable_item_list.dart';
import '../widgets/loading_view.dart';
import '../widgets/missing_profile_banner.dart';
import '../widgets/record_widgets.dart';
import '../widgets/profile_switcher.dart';
import '../widgets/section_card.dart';
import 'edit_profile_screen.dart';
import 'emergency_screen.dart';

/// Reloads the signed-in account's record and clinic appointments. No-op for
/// an account with no linked patient record.
Future<void> refreshPatientData(BuildContext context) async {
  final patientId = context.read<AuthProvider>().user?.patientId;
  if (patientId == null) return;
  final reminders = context.read<RemindersProvider>();
  final api = context.read<ApiClient>();
  context.read<PatientProvider>().loadRecord(patientId);
  await reminders.syncServerAppointments(patientId, api);
}

/// Home tab: the emergency action first, then a glance at the record
/// (summary, upcoming appointments, allergies, conditions). Medications,
/// visits, documents and bills live on the Care tab.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  bool _profileBannerDismissed = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();
    final patientState = context.watch<PatientProvider>();
    final remindersState = context.watch<RemindersProvider>();
    final patientId = auth.user?.patientId;
    final patient = patientState.patient;

    Widget content;
    if (patientId == null) {
      content = const NoRecordNotice();
    } else if (patientState.isLoadingRecord && patient == null) {
      content = const LoadingView();
    } else if (patientState.recordError != null && patient == null) {
      content = ErrorRetryView(
        message: patientState.recordError!,
        onRetry: () => refreshPatientData(context),
        showLogout: true,
      );
    } else if (patient == null) {
      content = const NoRecordNotice();
    } else {
      final upcoming = remindersState.serverAppointments.where((a) => a.status == 'scheduled').toList();
      final brief = patientState.handoverBrief;
      content = RefreshIndicator(
        onRefresh: () => refreshPatientData(context),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          children: [
            Text(
              patient.fullName,
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: context.palette.textPrimary),
            ),
            Text(
              l10n.bloodTypeLabel(patient.bloodType ?? '—'),
              style: TextStyle(fontSize: 13, color: context.palette.textMuted),
            ),
            if (!_profileBannerDismissed && auth.missingProfileFields.isNotEmpty) ...[
              const SizedBox(height: 12),
              MissingProfileBanner(
                onTap: () => context.pushScreen(const EditProfileScreen()),
                onDismiss: () => setState(() => _profileBannerDismissed = true),
              ),
            ],
            const SizedBox(height: 16),
            if (brief != null && brief.trim().isNotEmpty)
              SectionCard(
                title: l10n.healthSummaryTitle,
                child: Text(
                  brief,
                  style: TextStyle(fontSize: 14, color: context.palette.textBody, height: 1.4),
                ),
              ),
            SectionCard(
              title: l10n.clinicAppointmentsSection,
              child: upcoming.isEmpty
                  ? EmptyText(l10n.noClinicAppointments)
                  : ExpandableItemList(
                      items: upcoming.map((a) {
                        final venue = a.venue;
                        final title = (venue != null && venue.trim().isNotEmpty)
                            ? '${a.facilityName} · $venue'
                            : a.facilityName;
                        return BulletLine(title, subtitle: DateFormat('d MMM yyyy, h:mm a').format(a.scheduledAt));
                      }).toList(),
                    ),
            ),
            SectionCard(
              title: l10n.allergiesTitle,
              child: patient.allergies.isEmpty
                  ? EmptyText(l10n.noAllergies)
                  : ExpandableItemList(
                      items: patient.allergies.map((a) {
                        final reaction = a.reaction;
                        final title = (reaction != null && reaction.trim().isNotEmpty)
                            ? '${a.substance} (${a.severity}) · $reaction'
                            : '${a.substance} (${a.severity})';
                        return BulletLine(title);
                      }).toList(),
                    ),
            ),
            SectionCard(
              title: l10n.activeConditionsTitle,
              child: patient.conditions.isEmpty
                  ? EmptyText(l10n.noConditions)
                  : ExpandableItemList(
                      items: patient.conditions.map((c) {
                        final diagnosedAt = c.diagnosedAt;
                        return BulletLine(
                          '${c.name}${c.isChronic ? ' ${l10n.chronicSuffix}' : ''}',
                          subtitle: (diagnosedAt != null && diagnosedAt.trim().isNotEmpty)
                              ? l10n.diagnosedOnLabel(diagnosedAt)
                              : null,
                        );
                      }).toList(),
                    ),
            ),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(l10n.homeTitle), actions: const [ProfileSwitcherAction()]),
      body: Column(
        children: [
          const ActingBanner(),
          // Always first and never scrolls away: emergency-first product.
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton.icon(
                style: ElevatedButton.styleFrom(
                  backgroundColor: context.palette.emergency,
                  foregroundColor: context.onFill,
                  padding: const EdgeInsets.all(18),
                ),
                onPressed: () => context.pushScreen(const EmergencyScreen()),
                icon: const Icon(Icons.emergency_outlined),
                label: Text(l10n.emergencyButton),
              ),
            ),
          ),
          Expanded(child: content),
        ],
      ),
    );
  }
}
