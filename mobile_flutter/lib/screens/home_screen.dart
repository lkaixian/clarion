import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';
import '../widgets/missing_profile_banner.dart';
import '../widgets/section_card.dart';
import 'audit_log_screen.dart';
import 'edit_profile_screen.dart';
import 'emergency_scanner_screen.dart';
import 'emergency_screen.dart';
import 'reminders_screen.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  // Session-only dismiss (no persistence needed per spec) — resets if the
  // user navigates away and back, which is fine for a purely informational
  // nudge.
  bool _profileBannerDismissed = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  void _load() {
    final auth = context.read<AuthProvider>();
    final patientId = auth.user?.patientId;
    if (patientId != null) {
      context.read<PatientProvider>().loadRecord(patientId);
    }
  }

  Future<void> _signOut() async {
    await context.read<AuthProvider>().logout();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();
    final patientState = context.watch<PatientProvider>();
    final patientId = auth.user?.patientId;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.homeTitle),
        actions: [
          // Reachable while already signed in — e.g. a clinician, or a
          // patient who's also acting as a bystander/responder — without
          // having to sign out first. Deliberately a small app-bar icon
          // (not a prominent button) so it stays clearly secondary to
          // "View / Issue Emergency QR Card" below, which is about *this
          // patient's own* card, not scanning someone else's.
          IconButton(
            tooltip: l10n.scanSomeoneElsesCardTooltip,
            icon: const Icon(Icons.qr_code_scanner),
            onPressed: () =>
                Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EmergencyScannerScreen())),
          ),
          // Only meaningful for patient-role accounts — staff/clinician
          // accounts don't have a Patient record of their own to edit here.
          if (auth.user?.role == 'patient')
            IconButton(
              tooltip: l10n.editProfileTitle,
              icon: const Icon(Icons.person_outline),
              onPressed: () =>
                  Navigator.of(context).push(MaterialPageRoute(builder: (_) => const EditProfileScreen())),
            ),
          IconButton(
            tooltip: l10n.apiSettingsTooltip,
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      body: Builder(builder: (context) {
        if (patientId == null) {
          return Padding(
            padding: const EdgeInsets.all(24),
            child: Center(child: Text(l10n.noPatientRecord)),
          );
        }
        if (patientState.isLoadingRecord && patientState.patient == null) {
          return const LoadingView();
        }
        if (patientState.recordError != null && patientState.patient == null) {
          return ErrorRetryView(message: patientState.recordError!, onRetry: _load);
        }
        final patient = patientState.patient;
        if (patient == null) {
          return Padding(
            padding: const EdgeInsets.all(24),
            child: Center(child: Text(l10n.noPatientRecord)),
          );
        }

        final activeMeds = patient.activeMedications;
        final recentEncounters = patient.encounters.take(5).toList();

        return RefreshIndicator(
          onRefresh: () async => context.read<PatientProvider>().loadRecord(patientId),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(patient.fullName,
                            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: AppColors.textPrimary)),
                        Text(l10n.bloodTypeLabel(patient.bloodType ?? '—'),
                            style: const TextStyle(fontSize: 13, color: AppColors.textMuted)),
                      ],
                    ),
                  ),
                  TextButton(
                    onPressed: _signOut,
                    child: Text(l10n.signOut, style: const TextStyle(color: AppColors.textFaint, fontSize: 13)),
                  ),
                ],
              ),
              if (!_profileBannerDismissed && auth.missingProfileFields.isNotEmpty) ...[
                const SizedBox(height: 12),
                MissingProfileBanner(
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const EditProfileScreen()),
                  ),
                  onDismiss: () => setState(() => _profileBannerDismissed = true),
                ),
              ],
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.emergency,
                    padding: const EdgeInsets.all(16),
                  ),
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const EmergencyScreen()),
                  ),
                  child: Text(l10n.emergencyButton, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                ),
              ),
              const SizedBox(height: 16),
              if (patientState.handoverBrief != null && patientState.handoverBrief!.trim().isNotEmpty)
                SectionCard(
                  title: l10n.healthSummaryTitle,
                  child: Text(patientState.handoverBrief!,
                      style: const TextStyle(fontSize: 14, color: AppColors.textBody, height: 1.4)),
                ),
              SectionCard(
                title: l10n.activeConditionsTitle,
                child: patient.conditions.isEmpty
                    ? _EmptyLine(l10n.noConditions)
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: patient.conditions.map((c) {
                          final diagnosedAt = c.diagnosedAt;
                          return _BulletLine(
                            '${c.name}${c.isChronic ? ' ${l10n.chronicSuffix}' : ''}',
                            subtitle: (diagnosedAt != null && diagnosedAt.trim().isNotEmpty)
                                ? l10n.diagnosedOnLabel(diagnosedAt)
                                : null,
                          );
                        }).toList(),
                      ),
              ),
              SectionCard(
                title: l10n.currentMedicationsTitle,
                child: activeMeds.isEmpty
                    ? _EmptyLine(l10n.noActiveMedications)
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: activeMeds.map((m) {
                          final doseFreq = _joinNonEmpty([m.dosage, m.frequency], ', ');
                          final title = doseFreq.isEmpty ? m.drugName : '${m.drugName} — $doseFreq';
                          return _BulletLine(
                            title,
                            subtitle: l10n.prescribedBy(m.prescribedByFacility ?? l10n.unknownFacility),
                          );
                        }).toList(),
                      ),
              ),
              SectionCard(
                title: l10n.allergiesTitle,
                child: patient.allergies.isEmpty
                    ? _EmptyLine(l10n.noAllergies)
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: patient.allergies.map((a) {
                          final reaction = a.reaction;
                          final title = (reaction != null && reaction.trim().isNotEmpty)
                              ? '${a.substance} (${a.severity}) — $reaction'
                              : '${a.substance} (${a.severity})';
                          return _BulletLine(title);
                        }).toList(),
                      ),
              ),
              SectionCard(
                title: l10n.recentEncountersTitle,
                child: recentEncounters.isEmpty
                    ? _EmptyLine(l10n.noEncounters)
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: recentEncounters.map((e) {
                          final subtitleLines = <String>[];
                          final reason = e.reason;
                          final notes = e.notes;
                          if (reason != null && reason.trim().isNotEmpty) {
                            subtitleLines.add(l10n.encounterReasonLabel(reason));
                          }
                          if (notes != null && notes.trim().isNotEmpty) {
                            subtitleLines.add(l10n.encounterNotesLabel(notes));
                          }
                          return _BulletLine(
                            '${e.encounterType} @ ${e.facilityName} — ${e.startedAt}',
                            subtitle: subtitleLines.isEmpty ? null : subtitleLines.join('\n'),
                          );
                        }).toList(),
                      ),
              ),
              SectionCard(
                title: l10n.documentsTitle,
                child: patient.documents.isEmpty
                    ? _EmptyLine(l10n.noDocuments)
                    : Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: patient.documents.map((d) {
                          return _BulletLine(
                            '${_docTypeLabel(l10n, d.docType)} — ${d.originalFilename}',
                            subtitle: l10n.documentUploadedLine(
                              d.uploadedByFacility ?? l10n.unknownFacility,
                              d.uploadedAt,
                            ),
                          );
                        }).toList(),
                      ),
              ),
              if (patientState.nfcCards.isNotEmpty)
                SectionCard(
                  title: l10n.nfcCardSectionTitle,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: patientState.nfcCards.map((n) {
                      final revoked = n['revoked'] == true;
                      return _BulletLine(
                        revoked
                            ? l10n.nfcCardRevokedLine(n['nfc_uid'].toString())
                            : l10n.nfcCardActiveLine(n['nfc_uid'].toString()),
                      );
                    }).toList(),
                  ),
                ),
              const SizedBox(height: 4),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const RemindersScreen()),
                  ),
                  icon: const Text('💊'),
                  label: Text(l10n.remindersButton),
                  style: OutlinedButton.styleFrom(
                    backgroundColor: AppColors.chipBg,
                    foregroundColor: AppColors.primary,
                    padding: const EdgeInsets.all(16),
                    side: BorderSide.none,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: TextButton.icon(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                  ),
                  icon: const Icon(Icons.visibility_outlined, size: 18, color: AppColors.textMuted),
                  label: Text(l10n.whoViewedRecord, style: const TextStyle(color: AppColors.textMuted)),
                ),
              ),
            ],
          ),
        );
      }),
    );
  }
}

/// Joins the non-empty entries of [parts] with [separator] — used to fold
/// optional data fields (e.g. dosage + frequency) into a single display
/// string without stray separators when some fields are missing.
String _joinNonEmpty(List<String?> parts, String separator) {
  return parts.where((p) => p != null && p.trim().isNotEmpty).join(separator);
}

String _docTypeLabel(AppLocalizations l10n, String docType) {
  switch (docType) {
    case 'prescription':
      return l10n.docTypePrescription;
    case 'discharge_summary':
      return l10n.docTypeDischargeSummary;
    case 'lab_report':
      return l10n.docTypeLabReport;
    case 'imaging':
      return l10n.docTypeImaging;
    default:
      return l10n.docTypeOther;
  }
}

class _BulletLine extends StatelessWidget {
  const _BulletLine(this.text, {this.subtitle});
  final String text;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final subtitleText = subtitle;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('•  $text', style: const TextStyle(fontSize: 14, color: AppColors.textBody, height: 1.4)),
          if (subtitleText != null && subtitleText.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 18, top: 1),
              child: Text(
                subtitleText,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.3),
              ),
            ),
        ],
      ),
    );
  }
}

class _EmptyLine extends StatelessWidget {
  const _EmptyLine(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: const TextStyle(fontSize: 13, color: AppColors.textFaint));
  }
}
