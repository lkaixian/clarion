import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/generated/app_localizations.dart';
import '../../providers/auth_provider.dart';
import '../../providers/patient_provider.dart';
import '../../theme/app_theme.dart';

/// Large-print, single-column medication list — no nested navigation, no
/// secondary actions. Just what to take.
class SeniorMedicationsScreen extends StatelessWidget {
  const SeniorMedicationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final isDark = context.watch<AuthProvider>().seniorIsDark;
    final background = isDark ? SeniorColors.background : SeniorColorsLight.background;
    final surface = isDark ? SeniorColors.surface : SeniorColorsLight.surface;
    final text = isDark ? SeniorColors.text : SeniorColorsLight.text;
    final accent = isDark ? SeniorColors.accent : SeniorColorsLight.accent;
    final meds = patientState.patient?.activeMedications ?? [];

    return Scaffold(
      backgroundColor: background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: Icon(Icons.arrow_back, color: text, size: 32),
                  ),
                  Expanded(
                    child: Text(
                      l10n.seniorMedsTitle,
                      textAlign: TextAlign.center,
                      style: TextStyle(color: text, fontSize: 26, fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(width: 48),
                ],
              ),
              const SizedBox(height: 20),
              Expanded(
                child: meds.isEmpty
                    ? Center(
                        child: Text(l10n.noMedsRecord, style: TextStyle(color: text.withValues(alpha: 0.7), fontSize: 20)),
                      )
                    : ListView.separated(
                        itemCount: meds.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 16),
                        itemBuilder: (context, i) {
                          final m = meds[i];
                          final doseFreq = [m.dosage, m.frequency]
                              .where((p) => p != null && p.trim().isNotEmpty)
                              .join(', ');
                          return Container(
                            padding: const EdgeInsets.all(20),
                            decoration: BoxDecoration(
                              color: surface,
                              borderRadius: BorderRadius.circular(20),
                              border: Border.all(color: accent, width: 1.5),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  m.drugName,
                                  style: TextStyle(color: text, fontSize: 26, fontWeight: FontWeight.bold),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  doseFreq.isNotEmpty ? doseFreq : l10n.takeTwiceDaily,
                                  style: TextStyle(color: accent, fontSize: 18),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  l10n.fromFacility(m.prescribedByFacility ?? l10n.yourClinic),
                                  style: TextStyle(color: text.withValues(alpha: 0.6), fontSize: 15),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
