import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../l10n/generated/app_localizations.dart';
import '../../models/emergency_card.dart';
import '../../providers/auth_provider.dart';
import '../../providers/patient_provider.dart';
import '../../theme/app_theme.dart';
import '../emergency_screen.dart' show kScopeKeys;

/// Zero-decision emergency card: no scope checkboxes, no settings — it
/// issues a card with the recommended full scope the instant this screen
/// opens (unless one is already live — see [_issueIfNeeded]), so a senior
/// citizen (or someone helping them) is at most one tap away from a
/// scannable emergency QR code from the home hub.
class SeniorEmergencyScreen extends StatefulWidget {
  const SeniorEmergencyScreen({super.key});

  @override
  State<SeniorEmergencyScreen> createState() => _SeniorEmergencyScreenState();
}

class _SeniorEmergencyScreenState extends State<SeniorEmergencyScreen> {
  // Cached rather than looked up via `context.read` inside dispose() —
  // Provider explicitly disallows using `context` at that point.
  PatientProvider? _patientProvider;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _patientProvider = context.read<PatientProvider>();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _init());
  }

  @override
  void dispose() {
    _patientProvider?.stopCardPolling();
    super.dispose();
  }

  Future<void> _init() async {
    final patientId = context.read<AuthProvider>().user?.patientId;
    if (patientId == null) return;
    final patientState = context.read<PatientProvider>();

    // FIX for "no synergy between phone-issued and web-issued QR cards":
    // check what's *actually* live server-side first (a card could
    // already have been issued from the web console, another device, or
    // the standard Emergency screen) before auto-issuing a redundant new
    // one. Then keep polling so a revoke/reissue done elsewhere while this
    // screen stays open is reflected too — see
    // PatientProvider.refreshCurrentCard.
    await patientState.refreshCurrentCard(patientId);
    if (!mounted) return;
    await _issueIfNeeded();
    if (!mounted) return;
    context.read<PatientProvider>().startCardPolling(patientId);
  }

  Future<void> _issueIfNeeded() async {
    final patientState = context.read<PatientProvider>();
    if (patientState.emergencyCard != null && !patientState.emergencyCard!.revoked) return;
    final patientId = context.read<AuthProvider>().user?.patientId;
    if (patientId == null) return;
    await patientState.issueEmergencyCard(patientId: patientId, scope: kScopeKeys);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final card = patientState.emergencyCard;
    final imageBytes = card?.qrImageBytes;

    return Scaffold(
      backgroundColor: SeniorColors.background,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            children: [
              Row(
                children: [
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.arrow_back, color: Colors.white, size: 32),
                  ),
                  Expanded(
                    child: Text(
                      l10n.seniorEmergencyTitle,
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.w800),
                    ),
                  ),
                  const SizedBox(width: 48),
                ],
              ),
              const SizedBox(height: 24),
              Expanded(
                child: Center(
                  child: patientState.isIssuingCard
                      ? const CircularProgressIndicator(color: SeniorColors.accent)
                      : patientState.emergencyError != null
                          ? _ErrorState(message: patientState.emergencyError!, onRetry: _issueIfNeeded)
                          : imageBytes != null
                              ? _CardView(imageBytes: imageBytes, card: card!)
                              : Text(l10n.preparingCard, style: const TextStyle(color: Colors.white70, fontSize: 18)),
                ),
              ),
              if (card != null && imageBytes != null) ...[
                SizedBox(
                  width: double.infinity,
                  height: 72,
                  child: ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: SeniorColors.accent,
                      foregroundColor: Colors.black,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                      textStyle: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
                    ),
                    onPressed: () async {
                      await patientState.revokeCurrentCard();
                      patientState.clearEmergencyCard();
                      await _issueIfNeeded();
                    },
                    child: Text(l10n.getNewCard),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _CardView extends StatelessWidget {
  const _CardView({required this.imageBytes, required this.card});

  final Uint8List imageBytes;
  final EmergencyCard card;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(24)),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Image.memory(imageBytes, width: 220, height: 220),
          const SizedBox(height: 16),
          Text(
            l10n.showToResponder,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.black, fontSize: 20, fontWeight: FontWeight.bold, height: 1.3),
          ),
          const SizedBox(height: 8),
          Text(l10n.refLabel(card.cardReference), style: const TextStyle(color: Colors.black54, fontSize: 14)),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.error_outline, color: SeniorColors.emergency, size: 48),
        const SizedBox(height: 12),
        Text(message, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontSize: 18)),
        const SizedBox(height: 16),
        ElevatedButton(
          style: ElevatedButton.styleFrom(backgroundColor: SeniorColors.accent, foregroundColor: Colors.black),
          onPressed: onRetry,
          child: Text(l10n.tryAgain, style: const TextStyle(fontSize: 18)),
        ),
      ],
    );
  }
}
