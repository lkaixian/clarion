import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/generated/app_localizations.dart';
import '../../providers/auth_provider.dart';
import '../../providers/patient_provider.dart';
import '../../theme/app_theme.dart';
import '../../widgets/profile_switcher.dart';
import '../emergency_scanner_screen.dart';
import '../family_screen.dart';
import 'senior_emergency_screen.dart';
import 'senior_language_screen.dart';
import 'senior_medications_screen.dart';
import '../../widgets/common.dart';

/// The Senior Citizen Mode hub — CLARION's differentiation feature.
///
/// Deliberately NOT "Home with bigger fonts": different color system (near
/// -black background, high-contrast white/yellow text instead of the pale
/// blue standard theme, or a light high-contrast alternative — see
/// [AuthProvider.seniorIsDark]), a single column of two or three giant
/// buttons, no scrolling required, and the two things a senior citizen or
/// their caregiver need most (emergency card, medications) are always
/// exactly one tap away. No checkboxes, no scope pickers, no secondary
/// reading — every decision the standard app asks of the user has been
/// removed or defaulted here.
///
/// Deliberately does NOT show the "complete your profile"
/// missing-profile-fields banner/nudge that HomeScreen shows (see
/// MissingProfileBanner) — it's purely informational, and adding a third
/// thing to read/dismiss here would work against this screen's whole
/// "no secondary reading" design goal for a senior citizen / caregiver
/// under stress. Editing contact details is also not exposed from this
/// hub at all (no Settings-equivalent screen here) for the same reason.
///
/// "Switch to Standard View" and "Sign Out" used to be two plain
/// `TextButton`s stacked at the bottom of this column, firing immediately
/// on tap with zero confirmation — an easy accidental-tap trap for a senior
/// user (this was reported as a mispress problem). FIX: both actions now
/// live behind a single top-left menu icon opening a bottom sheet with two
/// large, well-separated buttons, and EACH of those still requires its own
/// explicit confirm/cancel dialog before anything actually happens — moving
/// them off the main column only fixed "easy to brush against by accident";
/// the confirmation step is what actually fixes "one tap = irreversible".
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

  void _openMenu(BuildContext context, bool isDark) {
    final l10n = AppLocalizations.of(context);
    final surface = isDark ? SeniorColors.surface : SeniorColorsLight.surface;
    final text = isDark ? SeniorColors.text : SeniorColorsLight.text;
    final accent = isDark ? SeniorColors.accent : SeniorColorsLight.accent;
    final emergency = isDark ? SeniorColors.emergency : SeniorColorsLight.emergency;

    showModalBottomSheet<void>(
      context: context,
      backgroundColor: surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 20, 24, 32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                l10n.seniorMenuTitle,
                style: TextStyle(color: text, fontSize: 22, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 88,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: accent,
                    foregroundColor: isDark ? Colors.black : Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                    textStyle: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                  ),
                  onPressed: () {
                    Navigator.of(sheetContext).pop();
                    _confirmSwitchToStandard(context, isDark);
                  },
                  child: Text(l10n.switchToStandard, textAlign: TextAlign.center),
                ),
              ),
              // Deliberately generous spacing (well beyond the app's usual
              // 10-12px gaps) between the two options -- these are the two
              // most consequential actions on this whole screen, so they
              // must never read as "one grouped control" a thumb could
              // clip both of on a single hurried tap.
              const SizedBox(height: 32),
              SizedBox(
                width: double.infinity,
                height: 88,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: emergency,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
                    textStyle: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                  ),
                  onPressed: () {
                    Navigator.of(sheetContext).pop();
                    _confirmSignOut(context, isDark);
                  },
                  child: Text(l10n.signOutSenior, textAlign: TextAlign.center),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _confirmSwitchToStandard(BuildContext context, bool isDark) async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await _showBigConfirmDialog(
      context: context,
      isDark: isDark,
      title: l10n.confirmSwitchToStandardTitle,
      body: l10n.confirmSwitchToStandardBody,
      confirmLabel: l10n.confirmSwitchToStandardAction,
    );
    if (confirmed == true && context.mounted) {
      await context.read<AuthProvider>().setPrefersSeniorMode(false);
    }
  }

  Future<void> _confirmSignOut(BuildContext context, bool isDark) async {
    final l10n = AppLocalizations.of(context);
    final confirmed = await _showBigConfirmDialog(
      context: context,
      isDark: isDark,
      title: l10n.confirmSignOutTitle,
      body: l10n.confirmSignOutBody,
      confirmLabel: l10n.confirmSignOutAction,
    );
    if (confirmed == true && context.mounted) {
      await context.read<AuthProvider>().logout();
    }
  }

  Future<bool?> _showBigConfirmDialog({
    required BuildContext context,
    required bool isDark,
    required String title,
    required String body,
    required String confirmLabel,
  }) {
    final surface = isDark ? SeniorColors.surface : SeniorColorsLight.surface;
    final text = isDark ? SeniorColors.text : SeniorColorsLight.text;
    final accent = isDark ? SeniorColors.accent : SeniorColorsLight.accent;
    return showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: Text(title, style: TextStyle(color: text, fontSize: 22, fontWeight: FontWeight.w800)),
        content: Text(body, style: TextStyle(color: text, fontSize: 18, height: 1.35)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: Text(
              MaterialLocalizations.of(dialogContext).cancelButtonLabel,
              style: TextStyle(color: text, fontSize: 18),
            ),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: accent, foregroundColor: isDark ? Colors.black : Colors.white),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(confirmLabel, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();
    final patientState = context.watch<PatientProvider>();
    final patient = patientState.patient;
    final isDark = auth.seniorIsDark;

    final background = isDark ? SeniorColors.background : SeniorColorsLight.background;
    final surface = isDark ? SeniorColors.surface : SeniorColorsLight.surface;
    final text = isDark ? SeniorColors.text : SeniorColorsLight.text;
    final accent = isDark ? SeniorColors.accent : SeniorColorsLight.accent;
    final emergency = isDark ? SeniorColors.emergency : SeniorColorsLight.emergency;
    final safe = isDark ? SeniorColors.safe : SeniorColorsLight.safe;

    final topAllergy = patient != null && patient.allergies.isNotEmpty ? patient.allergies.first.substance : null;

    return Scaffold(
      backgroundColor: background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              const ActingBanner(),
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      // FIX for the "Switch to Standard View" / "Sign Out"
                      // mispress problem: both actions moved here, behind a
                      // menu + a confirmation step each (see _openMenu).
                      IconButton(
                        tooltip: l10n.seniorMenuTooltip,
                        icon: Icon(Icons.menu, color: text, size: 30),
                        onPressed: () => _openMenu(context, isDark),
                      ),
                      IconButton(
                        tooltip: l10n.seniorThemeToggleTooltip,
                        icon: Icon(isDark ? Icons.light_mode : Icons.dark_mode, color: text, size: 28),
                        onPressed: () => auth.setSeniorIsDark(!isDark),
                      ),
                    ],
                  ),
                  Row(
                    children: [
                      // Reachable without signing out — e.g. a senior who is
                      // also acting as a bystander/responder for someone
                      // else. Kept as a small corner icon, well below the
                      // two giant tiles below, matching this screen's
                      // "no secondary reading" design philosophy.
                      IconButton(
                        tooltip: l10n.scanSomeoneElsesCardTooltip,
                        icon: Icon(Icons.qr_code_scanner, color: text, size: 30),
                        onPressed: () => context.pushScreen(const EmergencyScannerScreen()),
                      ),
                      IconButton(
                        tooltip: l10n.seniorLanguageTitle,
                        icon: Icon(Icons.language, color: text, size: 30),
                        onPressed: () => context.pushScreen(const SeniorLanguageScreen()),
                      ),
                    ],
                  ),
                ],
              ),
              Text(
                patient?.fullName ?? l10n.appTitle,
                textAlign: TextAlign.center,
                style: TextStyle(color: text, fontSize: 34, fontWeight: FontWeight.w800, height: 1.15),
              ),
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                decoration: BoxDecoration(
                  color: surface,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: accent, width: 2),
                ),
                child: Text(
                  l10n.seniorBloodType(patient?.bloodType ?? '—'),
                  style: TextStyle(color: accent, fontSize: 24, fontWeight: FontWeight.bold),
                ),
              ),
              if (topAllergy != null) ...[
                const SizedBox(height: 8),
                Text(
                  l10n.seniorAllergicTo(topAllergy.toUpperCase()),
                  textAlign: TextAlign.center,
                  style: TextStyle(color: emergency, fontSize: 18, fontWeight: FontWeight.bold),
                ),
              ],
              const Spacer(),
              _BigTile(
                label: l10n.seniorEmergencyTile,
                color: emergency,
                onTap: () => context.pushScreen(const SeniorEmergencyScreen()),
              ),
              const SizedBox(height: 20),
              _BigTile(
                label: l10n.seniorMedsTile,
                color: safe,
                onTap: () => context.pushScreen(const SeniorMedicationsScreen()),
              ),
              if (auth.user?.role == 'patient') ...[
              const SizedBox(height: 20),
              _BigTile(
                label: l10n.familyTitle,
                color: accent,
                height: 80,
                onTap: () => context.pushScreen(const FamilyScreen()),
              ),
              ],
              const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}

class _BigTile extends StatelessWidget {
  const _BigTile({required this.label, required this.color, required this.onTap, this.height = 140});

  final String label;
  final Color color;
  final VoidCallback onTap;
  final double height;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: height,
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
