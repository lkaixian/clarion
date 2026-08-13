import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/generated/app_localizations.dart';
import '../../providers/auth_provider.dart';
import '../../providers/patient_provider.dart';
import '../../theme/app_theme.dart';
import '../emergency_scanner_screen.dart';
import 'senior_emergency_screen.dart';
import 'senior_language_screen.dart';
import 'senior_medications_screen.dart';

/// The Senior Citizen Mode hub — MediBridge's differentiation feature.
///
/// Deliberately NOT "Home with bigger fonts": different color system (near
/// -black background, high-contrast white/yellow text instead of the pale
/// blue standard theme), a single column of two or three giant buttons,
/// no scrolling required, and the two things a senior citizen or their
/// caregiver need most (emergency card, medications) are always exactly
/// one tap away. No checkboxes, no scope pickers, no secondary reading —
/// every decision the standard app asks of the user has been removed or
/// defaulted here.
///
/// Deliberately does NOT show the "complete your profile"
/// missing-profile-fields banner/nudge that HomeScreen shows (see
/// MissingProfileBanner) — it's purely informational, and adding a third
/// thing to read/dismiss here would work against this screen's whole
/// "no secondary reading" design goal for a senior citizen / caregiver
/// under stress. Editing contact details is also not exposed from this
/// hub at all (no Settings-equivalent screen here) for the same reason.
class SeniorHomeScreen extends StatefulWidget {
  const SeniorHomeScreen({super.key});

  @override
  State<SeniorHomeScreen> createState() => _SeniorHomeScreenState();
}

class _SeniorHomeScreenState extends State<SeniorHomeScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final patientId = context.read<AuthProvider>().user?.patientId;
      final patientState = context.read<PatientProvider>();
      if (patientId != null && patientState.patient == null) {
        patientState.loadRecord(patientId);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();
    final patientState = context.watch<PatientProvider>();
    final patient = patientState.patient;

    final topAllergy = patient != null && patient.allergies.isNotEmpty ? patient.allergies.first.substance : null;

    return Scaffold(
      backgroundColor: SeniorColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  // Reachable without signing out — e.g. a senior who is
                  // also acting as a bystander/responder for someone else.
                  // Kept as a small corner icon, well below the two giant
                  // tiles below, matching this screen's "no secondary
                  // reading" design philosophy.
                  IconButton(
                    tooltip: l10n.scanSomeoneElsesCardTooltip,
                    icon: const Icon(Icons.qr_code_scanner, color: SeniorColors.text, size: 30),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const EmergencyScannerScreen()),
                    ),
                  ),
                  IconButton(
                    tooltip: l10n.seniorLanguageTitle,
                    icon: const Icon(Icons.language, color: SeniorColors.text, size: 30),
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const SeniorLanguageScreen()),
                    ),
                  ),
                ],
              ),
              Text(
                patient?.fullName ?? l10n.appTitle,
                textAlign: TextAlign.center,
                style: const TextStyle(color: SeniorColors.text, fontSize: 34, fontWeight: FontWeight.w800, height: 1.15),
              ),
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                decoration: BoxDecoration(
                  color: SeniorColors.surface,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: SeniorColors.accent, width: 2),
                ),
                child: Text(
                  l10n.seniorBloodType(patient?.bloodType ?? '—'),
                  style: const TextStyle(color: SeniorColors.accent, fontSize: 24, fontWeight: FontWeight.bold),
                ),
              ),
              if (topAllergy != null) ...[
                const SizedBox(height: 8),
                Text(
                  l10n.seniorAllergicTo(topAllergy.toUpperCase()),
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: SeniorColors.emergency, fontSize: 18, fontWeight: FontWeight.bold),
                ),
              ],
              const Spacer(),
              _BigTile(
                label: l10n.seniorEmergencyTile,
                color: SeniorColors.emergency,
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const SeniorEmergencyScreen()),
                ),
              ),
              const SizedBox(height: 20),
              _BigTile(
                label: l10n.seniorMedsTile,
                color: SeniorColors.safe,
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const SeniorMedicationsScreen()),
                ),
              ),
              const Spacer(),
              TextButton(
                onPressed: () async {
                  await auth.setPrefersSeniorMode(false);
                },
                child: Text(
                  l10n.switchToStandard,
                  style: const TextStyle(color: SeniorColors.accent, fontSize: 18, decoration: TextDecoration.underline),
                ),
              ),
              const SizedBox(height: 4),
              TextButton(
                onPressed: () => auth.logout(),
                child: Text(l10n.signOutSenior, style: const TextStyle(color: Colors.white70, fontSize: 16)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _BigTile extends StatelessWidget {
  const _BigTile({required this.label, required this.color, required this.onTap});

  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 140,
      child: Material(
        color: color,
        borderRadius: BorderRadius.circular(24),
        child: InkWell(
          borderRadius: BorderRadius.circular(24),
          onTap: onTap,
          child: Center(
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w800, height: 1.2),
            ),
          ),
        ),
      ),
    );
  }
}
