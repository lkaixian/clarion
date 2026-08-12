import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/generated/app_localizations.dart';
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
    final meds = patientState.patient?.activeMedications ?? [];

    return Scaffold(
      backgroundColor: SeniorColors.background,
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
                    icon: const Icon(Icons.arrow_back, color: Colors.white, size: 32),
                  ),
                  Expanded(
                    child: Text(
                      l10n.seniorMedsTitle,
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(width: 48),
                ],
              ),
              const SizedBox(height: 20),
              Expanded(
                child: meds.isEmpty
                    ? Center(
                        child: Text(l10n.noMedsRecord, style: const TextStyle(color: Colors.white70, fontSize: 20)),
                      )
                    : ListView.separated(
                        itemCount: meds.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 16),
                        itemBuilder: (context, i) {
                          final m = meds[i];
                          return Container(
                            padding: const EdgeInsets.all(20),
                            decoration: BoxDecoration(
                              color: SeniorColors.surface,
                              borderRadius: BorderRadius.circular(20),
                              border: Border.all(color: SeniorColors.accent, width: 1.5),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  m.drugName,
                                  style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.bold),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  l10n.takeTwiceDaily,
                                  style: const TextStyle(color: SeniorColors.accent, fontSize: 18),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  l10n.fromFacility(m.prescribedByFacility ?? l10n.yourClinic),
                                  style: const TextStyle(color: Colors.white60, fontSize: 15),
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
