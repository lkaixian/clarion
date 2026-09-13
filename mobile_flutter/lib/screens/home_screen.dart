import 'dart:io';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../providers/reminders_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import '../widgets/expandable_item_list.dart';
import '../widgets/loading_view.dart';
import '../widgets/missing_profile_banner.dart';
import '../widgets/section_card.dart';
import 'audit_log_screen.dart';
import 'book_appointment_screen.dart';
import 'edit_profile_screen.dart';
import 'emergency_scanner_screen.dart';
import 'emergency_screen.dart';
import 'queue_status_screen.dart';
import 'reminders_screen.dart';
import 'scan_checkin_screen.dart';
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
      // FIX for "web-published appointments never show up / update in the
      // app": this doesn't need to wait for the full record load — it's an
      // independent endpoint keyed only on patientId — so it's fired here
      // too (in addition to RemindersScreen's own polling) so a clinic
      // -published appointment is visible right on Home without the user
      // having to open Reminders at all. Errors are swallowed inside
      // syncServerAppointments itself (leaves whatever was last loaded
      // untouched), so this is safe to fire-and-forget.
      context.read<RemindersProvider>().syncServerAppointments(
        patientId,
        context.read<ApiClient>(),
      );
    }
  }

  Future<void> _signOut() async {
    await context.read<AuthProvider>().logout();
  }

  /// P3.10: fetch the visit-summary PDF and hand it to the
  /// OS share/open sheet. The endpoint is Bearer-authed like everything
  /// else here, so a plain url_launcher can't fetch it directly -- fetched
  /// via Dio into memory, written to a temp file, then share_plus wraps the
  /// Android FileProvider/iOS share-sheet plumbing a raw file:// URI hits
  /// StrictMode/FileUriExposedException on (see pubspec.yaml's comment on
  /// this dependency).
  Future<void> _shareVisitSummary(String patientId, String encounterId) async {
    final l10n = AppLocalizations.of(context);
    try {
      final bytes = await context.read<ApiClient>().getVisitSummaryPdfBytes(
        patientId: patientId,
        encounterId: encounterId,
      );
      final dir = await Directory.systemTemp.createTemp('clarion_pdf');
      final file = File('${dir.path}/visit_summary.pdf');
      await file.writeAsBytes(bytes);
      if (!mounted) return;
      await Share.shareXFiles([XFile(file.path)]);
    } catch (e) {
      if (!mounted) return;
      // A 404 (this particular visit was never signed off with structured
      // data) is a normal, expected outcome for some encounters, not a
      // scary error -- same ApiException.message-first pattern used
      // everywhere else in this app for a caught form/network failure.
      final message = e is ApiException ? e.message : l10n.visitSummaryUnavailable;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();
    final patientState = context.watch<PatientProvider>();
    final remindersState = context.watch<RemindersProvider>();
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
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const EmergencyScannerScreen()),
            ),
          ),
          // Only meaningful for patient-role accounts — staff/clinician
          // accounts don't have a Patient record of their own to edit here.
          if (auth.user?.role == 'patient')
            IconButton(
              tooltip: l10n.editProfileTitle,
              icon: const Icon(Icons.person_outline),
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const EditProfileScreen()),
              ),
            ),
          IconButton(
            tooltip: l10n.apiSettingsTooltip,
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.of(
              context,
            ).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      body: Builder(
        builder: (context) {
          if (patientId == null) {
            return Padding(
              padding: const EdgeInsets.all(24),
              child: Center(child: Text(l10n.noPatientRecord)),
            );
          }
          if (patientState.isLoadingRecord && patientState.patient == null) {
            return const LoadingView();
          }
          if (patientState.recordError != null &&
              patientState.patient == null) {
            return ErrorRetryView(
              message: patientState.recordError!,
              onRetry: _load,
              showLogout: true,
            );
          }
          final patient = patientState.patient;
          if (patient == null) {
            return Padding(
              padding: const EdgeInsets.all(24),
              child: Center(child: Text(l10n.noPatientRecord)),
            );
          }

          final activeMeds = patient.activeMedications;
          final upcomingAppointments = remindersState.serverAppointments
              .where((a) => a.status == 'scheduled')
              .toList();

          return RefreshIndicator(
            onRefresh: () async {
              context.read<PatientProvider>().loadRecord(patientId);
              await context.read<RemindersProvider>().syncServerAppointments(
                patientId,
                context.read<ApiClient>(),
              );
            },
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
                          Text(
                            patient.fullName,
                            style: TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.bold,
                              color: context.palette.textPrimary,
                            ),
                          ),
                          Text(
                            l10n.bloodTypeLabel(patient.bloodType ?? '—'),
                            style: TextStyle(
                              fontSize: 13,
                              color: context.palette.textMuted,
                            ),
                          ),
                        ],
                      ),
                    ),
                    TextButton(
                      onPressed: _signOut,
                      child: Text(
                        l10n.signOut,
                        style: TextStyle(
                          color: context.palette.textFaint,
                          fontSize: 13,
                        ),
                      ),
                    ),
                  ],
                ),
                if (!_profileBannerDismissed &&
                    auth.missingProfileFields.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  MissingProfileBanner(
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const EditProfileScreen(),
                      ),
                    ),
                    onDismiss: () =>
                        setState(() => _profileBannerDismissed = true),
                  ),
                ],
                const SizedBox(height: 16),
                // "Quick actions" groups the Emergency button together with
                // Reminders / Scan Check-in / Queue status — previously these
                // three lived *after* the whole run of medical-record
                // SectionCards below, which visually orphaned them from
                // Emergency (their nearest sibling in purpose) and made them
                // look like an afterthought rather than a deliberate group of
                // shortcuts.
                _SectionHeader(l10n.quickActionsSectionTitle),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: context.palette.emergency,
                      padding: const EdgeInsets.all(16),
                    ),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const EmergencyScreen(),
                      ),
                    ),
                    child: Text(
                      l10n.emergencyButton,
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        fontSize: 15,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const RemindersScreen(),
                      ),
                    ),
                    icon: const Text('💊'),
                    label: Text(l10n.remindersButton),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: context.palette.chipBg,
                      foregroundColor: context.palette.primary,
                      padding: const EdgeInsets.all(16),
                      side: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const ScanCheckinScreen(),
                      ),
                    ),
                    icon: Icon(Icons.qr_code_scanner, color: context.palette.primary),
                    label: Text(l10n.scanCheckinButton),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: context.palette.chipBg,
                      foregroundColor: context.palette.primary,
                      padding: const EdgeInsets.all(16),
                      side: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const QueueStatusScreen(),
                      ),
                    ),
                    icon: Icon(Icons.confirmation_number_outlined, color: context.palette.primary),
                    label: Text(l10n.queueStatusButton),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: context.palette.chipBg,
                      foregroundColor: context.palette.primary,
                      padding: const EdgeInsets.all(16),
                      side: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                // P3.10: patient self-service booking.
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const BookAppointmentScreen(),
                      ),
                    ),
                    icon: Icon(Icons.event_available_outlined, color: context.palette.primary),
                    label: Text(l10n.bookAppointmentButton),
                    style: OutlinedButton.styleFrom(
                      backgroundColor: context.palette.chipBg,
                      foregroundColor: context.palette.primary,
                      padding: const EdgeInsets.all(16),
                      side: BorderSide.none,
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                // "Health record" umbrella-groups every read-only medical
                // SectionCard below so it's visually obvious they're all
                // facets of the same thing — the patient's own record — as
                // opposed to the actionable shortcuts in Quick actions above.
                // The individual SectionCards keep their own internal
                // content/behavior unchanged; this only adds a group-level
                // heading above them.
                _SectionHeader(l10n.healthRecordSectionTitle),
                const SizedBox(height: 10),
                if (patientState.handoverBrief != null &&
                    patientState.handoverBrief!.trim().isNotEmpty)
                  SectionCard(
                    title: l10n.healthSummaryTitle,
                    child: Text(
                      patientState.handoverBrief!,
                      style: TextStyle(
                        fontSize: 14,
                        color: context.palette.textBody,
                        height: 1.4,
                      ),
                    ),
                  ),
                // Clinic-published appointments (see RemindersProvider /
                // RemindersScreen for the full, dynamically-polled section) —
                // surfaced here too, right under the emergency button, so a
                // newly-published appointment is visible the moment Home
                // loads without the patient having to know to open Reminders
                // at all. Read-only here, same as on the Reminders screen.
                SectionCard(
                  title: l10n.clinicAppointmentsSection,
                  child: upcomingAppointments.isEmpty
                      ? _EmptyLine(l10n.noClinicAppointments)
                      : ExpandableItemList(
                          items: upcomingAppointments.map((a) {
                            final venue = a.venue;
                            final title =
                                (venue != null && venue.trim().isNotEmpty)
                                ? '${a.facilityName} — $venue'
                                : a.facilityName;
                            return _BulletLine(
                              title,
                              subtitle: DateFormat(
                                'd MMM yyyy, h:mm a',
                              ).format(a.scheduledAt),
                            );
                          }).toList(),
                        ),
                ),
                SectionCard(
                  title: l10n.activeConditionsTitle,
                  child: patient.conditions.isEmpty
                      ? _EmptyLine(l10n.noConditions)
                      : ExpandableItemList(
                          items: patient.conditions.map((c) {
                            final diagnosedAt = c.diagnosedAt;
                            return _BulletLine(
                              '${c.name}${c.isChronic ? ' ${l10n.chronicSuffix}' : ''}',
                              subtitle:
                                  (diagnosedAt != null &&
                                      diagnosedAt.trim().isNotEmpty)
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
                      : ExpandableItemList(
                          items: activeMeds.map((m) {
                            final doseFreq = _joinNonEmpty([
                              m.dosage,
                              m.frequency,
                            ], ', ');
                            final title = doseFreq.isEmpty
                                ? m.drugName
                                : '${m.drugName} — $doseFreq';
                            return _BulletLine(
                              title,
                              subtitle: l10n.prescribedBy(
                                m.prescribedByFacility ?? l10n.unknownFacility,
                              ),
                            );
                          }).toList(),
                        ),
                ),
                SectionCard(
                  title: l10n.allergiesTitle,
                  child: patient.allergies.isEmpty
                      ? _EmptyLine(l10n.noAllergies)
                      : ExpandableItemList(
                          items: patient.allergies.map((a) {
                            final reaction = a.reaction;
                            final title =
                                (reaction != null && reaction.trim().isNotEmpty)
                                ? '${a.substance} (${a.severity}) — $reaction'
                                : '${a.substance} (${a.severity})';
                            return _BulletLine(title);
                          }).toList(),
                        ),
                ),
                SectionCard(
                  title: l10n.recentEncountersTitle,
                  child: patient.encounters.isEmpty
                      ? _EmptyLine(l10n.noEncounters)
                      : ExpandableItemList(
                          items: patient.encounters.map((e) {
                            final subtitleLines = <String>[];
                            final reason = e.reason;
                            final notes = e.notes;
                            final department = e.department;
                            final note = e.consultationNote;
                            if (reason != null && reason.trim().isNotEmpty) {
                              subtitleLines.add(
                                l10n.encounterReasonLabel(reason),
                              );
                            }
                            if (department != null && department.trim().isNotEmpty) {
                              subtitleLines.add(
                                l10n.encounterDepartmentLabel(department),
                              );
                            }
                            if (notes != null && notes.trim().isNotEmpty) {
                              subtitleLines.add(
                                l10n.encounterNotesLabel(notes),
                              );
                            }
                            // P3.10: diagnosis/treatment +
                            // vitals from the signed consultation, if any.
                            final assessment = note?.assessment;
                            if (assessment != null && assessment.trim().isNotEmpty) {
                              subtitleLines.add(assessment);
                            }
                            if (note != null && note.hasVitals) {
                              subtitleLines.add(
                                l10n.encounterVitalsLabel(note.vitalsLine),
                              );
                            }
                            return _BulletLine(
                              '${e.encounterType} @ ${e.facilityName} — ${e.startedAt}',
                              subtitle: subtitleLines.isEmpty
                                  ? null
                                  : subtitleLines.join('\n'),
                              maxLines: subtitleLines.length.clamp(2, 5),
                              trailing: IconButton(
                                tooltip: l10n.downloadVisitSummary,
                                icon: Icon(
                                  Icons.picture_as_pdf_outlined,
                                  size: 20,
                                  color: context.palette.primary,
                                ),
                                onPressed: () => _shareVisitSummary(patient.id, e.id),
                              ),
                            );
                          }).toList(),
                        ),
                ),
                SectionCard(
                  title: l10n.documentsTitle,
                  child: patient.documents.isEmpty
                      ? _EmptyLine(l10n.noDocuments)
                      : ExpandableItemList(
                          items: patient.documents.map((d) {
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
                        // The raw UID is stored hashed server-side (Security
                        // Audit M7) and never sent back; show the last-4 tail.
                        final label = 'card ••${n['nfc_uid_last4'] ?? '????'}';
                        return _BulletLine(
                          revoked
                              ? l10n.nfcCardRevokedLine(label)
                              : l10n.nfcCardActiveLine(label),
                        );
                      }).toList(),
                    ),
                  ),
                // Footer / secondary — kept last and visually de-emphasized
                // (plain TextButton, muted color), same as before.
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: TextButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const AuditLogScreen()),
                    ),
                    icon: Icon(
                      Icons.visibility_outlined,
                      size: 18,
                      color: context.palette.textMuted,
                    ),
                    label: Text(
                      l10n.whoViewedRecord,
                      style: TextStyle(color: context.palette.textMuted),
                    ),
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

/// Lightweight group-level heading used to visually separate Home's "Quick
/// actions" and "Health record" zones from each other. Deliberately *not*
/// a full [SectionCard] — these headings sit above a run of several cards
/// (or several buttons), not above a single piece of content, so a bordered
/// card container around the heading itself would read as an extra empty
/// card rather than as a section label. Style matches the small-caps
/// muted-label convention used elsewhere in the app (see e.g.
/// EmergencyScannerScreen's field-group labels).
class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);
  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Text(
        title.toUpperCase(),
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: context.palette.textMuted,
          letterSpacing: 0.5,
        ),
      ),
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
  // `trailing`/`maxLines` are additive (default null/2, matching every
  // existing call site's behaviour unchanged) -- added for P3.10's
  // per-encounter "download/share visit summary" button and its longer
  // (department + vitals) subtitle, without touching the plain-text-only
  // shape every other caller (documents/conditions/etc.) still relies on.
  const _BulletLine(this.text, {this.subtitle, this.trailing, this.maxLines = 2});
  final String text;
  final String? subtitle;
  final Widget? trailing;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    final subtitleText = subtitle;
    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '•  $text',
          style: TextStyle(
            fontSize: 14,
            color: context.palette.textBody,
            height: 1.4,
          ),
        ),
        if (subtitleText != null && subtitleText.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 18, top: 1),
            child: Text(
              subtitleText,
              maxLines: maxLines,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 12,
                color: context.palette.textMuted,
                height: 1.3,
              ),
            ),
          ),
      ],
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: trailing == null
          ? content
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [Expanded(child: content), trailing!],
            ),
    );
  }
}

class _EmptyLine extends StatelessWidget {
  const _EmptyLine(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text,
      style: TextStyle(fontSize: 13, color: context.palette.textFaint),
    );
  }
}
