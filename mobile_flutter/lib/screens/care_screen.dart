import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/expandable_item_list.dart';
import '../widgets/loading_view.dart';
import '../widgets/record_widgets.dart';
import '../widgets/section_card.dart';
import 'book_appointment_screen.dart';
import 'home_screen.dart' show refreshPatientData;
import 'my_bills_screen.dart';
import 'reminders_screen.dart';

/// Care tab: reminders, booking, bills, and the clinical record lists
/// (medications, visits, documents, NFC cards).
class CareScreen extends StatelessWidget {
  const CareScreen({super.key});

  /// Fetches the visit-summary PDF (Bearer-authed, so not a plain URL) and
  /// hands it to the OS share sheet.
  // ponytail: the temp PDF is never deleted; the OS may still be reading it
  // after shareXFiles returns. Clear `clarion_pdf*` temp dirs on next start
  // if this becomes a real storage problem.
  Future<void> _shareVisitSummary(BuildContext context, String patientId, String encounterId) async {
    final l10n = AppLocalizations.of(context);
    final api = context.read<ApiClient>();
    try {
      final bytes = await api.getVisitSummaryPdfBytes(patientId: patientId, encounterId: encounterId);
      final dir = await Directory.systemTemp.createTemp('clarion_pdf');
      final file = File('${dir.path}/visit_summary.pdf');
      await file.writeAsBytes(bytes);
      await Share.shareXFiles([XFile(file.path)]);
    } catch (e) {
      // A 404 just means this visit has no signed summary; show the server
      // message when there is one.
      if (!context.mounted) return;
      context.snack(e is ApiException ? e.message : l10n.visitSummaryUnavailable);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientId = context.watch<AuthProvider>().user?.patientId;
    final state = context.watch<PatientProvider>();
    final patient = state.patient;

    Widget body;
    if (patientId == null) {
      body = const NoRecordNotice();
    } else if (state.isLoadingRecord && patient == null) {
      body = const LoadingView();
    } else if (state.recordError != null && patient == null) {
      body = ErrorRetryView(
        message: state.recordError!,
        onRetry: () => refreshPatientData(context),
        showLogout: true,
      );
    } else if (patient == null) {
      body = const NoRecordNotice();
    } else {
      final meds = patient.activeMedications;
      body = RefreshIndicator(
        onRefresh: () => refreshPatientData(context),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _ActionButton(
              icon: Icons.alarm_outlined,
              label: l10n.remindersButton,
              onPressed: () => context.pushScreen(const RemindersScreen()),
            ),
            const SizedBox(height: 10),
            _ActionButton(
              icon: Icons.event_available_outlined,
              label: l10n.bookAppointmentButton,
              onPressed: () => context.pushScreen(const BookAppointmentScreen()),
            ),
            const SizedBox(height: 10),
            _ActionButton(
              icon: Icons.receipt_long_outlined,
              label: l10n.myBills,
              onPressed: () => context.pushScreen(const MyBillsScreen()),
            ),
            const SizedBox(height: 20),
            SectionHeader(l10n.healthRecordSectionTitle),
            const SizedBox(height: 10),
            SectionCard(
              title: l10n.currentMedicationsTitle,
              child: meds.isEmpty
                  ? EmptyText(l10n.noActiveMedications)
                  : ExpandableItemList(
                      items: meds.map((m) {
                        final doseFreq = joinNonEmpty([m.dosage, m.frequency], ', ');
                        return BulletLine(
                          doseFreq.isEmpty ? m.drugName : '${m.drugName} · $doseFreq',
                          subtitle: l10n.prescribedBy(m.prescribedByFacility ?? l10n.unknownFacility),
                        );
                      }).toList(),
                    ),
            ),
            SectionCard(
              title: l10n.recentEncountersTitle,
              child: patient.encounters.isEmpty
                  ? EmptyText(l10n.noEncounters)
                  : ExpandableItemList(
                      items: patient.encounters.map((e) {
                        final lines = <String>[];
                        final note = e.consultationNote;
                        void add(String? v, String Function(String) fmt) {
                          if (v != null && v.trim().isNotEmpty) lines.add(fmt(v));
                        }

                        add(e.reason, l10n.encounterReasonLabel);
                        add(e.department, l10n.encounterDepartmentLabel);
                        add(e.notes, l10n.encounterNotesLabel);
                        add(note?.assessment, (v) => v);
                        if (note != null && note.hasVitals) {
                          lines.add(l10n.encounterVitalsLabel(note.vitalsLine));
                        }
                        return BulletLine(
                          '${e.encounterType} @ ${e.facilityName} · ${e.startedAt}',
                          subtitle: lines.isEmpty ? null : lines.join('\n'),
                          maxLines: lines.length.clamp(2, 5),
                          trailing: IconButton(
                            tooltip: l10n.downloadVisitSummary,
                            icon: Icon(Icons.picture_as_pdf_outlined, size: 20, color: context.palette.primary),
                            onPressed: () => _shareVisitSummary(context, patient.id, e.id),
                          ),
                        );
                      }).toList(),
                    ),
            ),
            SectionCard(
              title: l10n.documentsTitle,
              child: patient.documents.isEmpty
                  ? EmptyText(l10n.noDocuments)
                  : ExpandableItemList(
                      items: patient.documents.map((d) {
                        return BulletLine(
                          '${docTypeLabel(l10n, d.docType)} · ${d.originalFilename}',
                          subtitle: l10n.documentUploadedLine(d.uploadedByFacility ?? l10n.unknownFacility, d.uploadedAt),
                        );
                      }).toList(),
                    ),
            ),
            if (state.nfcCards.isNotEmpty)
              SectionCard(
                title: l10n.nfcCardSectionTitle,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: state.nfcCards.map((n) {
                    // Only the last 4 of the UID ever reach the client.
                    final label = 'card ••${n.last4}';
                    return BulletLine(
                      n.revoked ? l10n.nfcCardRevokedLine(label) : l10n.nfcCardActiveLine(label),
                    );
                  }).toList(),
                ),
              ),
          ],
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: Text(l10n.navCare)),
      body: body,
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.icon, required this.label, required this.onPressed});
  final IconData icon;
  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: OutlinedButton.icon(
        onPressed: onPressed,
        icon: Icon(icon),
        label: Text(label),
        style: OutlinedButton.styleFrom(
          backgroundColor: context.palette.chipBg,
          foregroundColor: context.palette.primary,
          padding: const EdgeInsets.all(16),
          side: BorderSide.none,
        ),
      ),
    );
  }
}
