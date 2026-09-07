import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../theme/app_theme.dart';

/// Scope keys accepted by the backend's `POST /emergency/issue` endpoint
/// (see backend/app/schemas.py::EmergencyProfileRequest). Labels are
/// resolved per-locale via [scopeLabel] rather than baked into this list.
const kScopeKeys = ['allergies', 'medications', 'conditions', 'blood_type'];

String scopeLabel(AppLocalizations l10n, String key) {
  switch (key) {
    case 'allergies':
      return l10n.scopeAllergies;
    case 'medications':
      return l10n.scopeMedications;
    case 'conditions':
      return l10n.scopeConditions;
    case 'blood_type':
      return l10n.scopeBloodType;
    default:
      return key;
  }
}

class EmergencyScreen extends StatefulWidget {
  const EmergencyScreen({super.key});

  @override
  State<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends State<EmergencyScreen> {
  final Set<String> _selected = {...kScopeKeys};

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
    // FIX for "no synergy between phone-issued and web-issued QR cards":
    // fetch (and keep polling) the backend's read-only view of whichever
    // card is *actually* currently live for this patient — not just
    // whatever this screen itself issued — so a card generated from the
    // web console (or another device) shows up here too, and a
    // revoke/reissue done elsewhere is reflected without a manual
    // force-quit/reopen. See PatientProvider.refreshCurrentCard.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final patientId = context.read<AuthProvider>().user?.patientId;
      if (patientId != null) {
        context.read<PatientProvider>().startCardPolling(patientId);
      }
    });
  }

  @override
  void dispose() {
    _patientProvider?.stopCardPolling();
    super.dispose();
  }

  void _toggle(String key) {
    setState(() {
      if (_selected.contains(key)) {
        _selected.remove(key);
      } else {
        _selected.add(key);
      }
    });
  }

  Future<void> _issue() async {
    final l10n = AppLocalizations.of(context);
    final patientState = context.read<PatientProvider>();

    // If there's already a live card on screen, warn before replacing it —
    // this is the fix for "I kept hitting Generate and it didn't tell me
    // what happened to the old card": the backend now auto-revokes any
    // previous QR card when a new one is issued (a patient should only
    // ever have one live QR card at a time), but the user should be told
    // that's about to happen rather than have it happen silently.
    final existingCard = patientState.emergencyCard;
    if (existingCard != null && !existingCard.revoked) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: Text(l10n.regenerateConfirmTitle),
          content: Text(l10n.regenerateConfirmBody(existingCard.cardReference)),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: Text(MaterialLocalizations.of(dialogContext).cancelButtonLabel),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: Text(l10n.regenerateConfirmAction),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    if (!mounted) return;

    final auth = context.read<AuthProvider>();
    final patientId = auth.user?.patientId;
    if (patientId == null) return;
    final ok = await patientState.issueEmergencyCard(
      patientId: patientId,
      scope: _selected.toList(),
    );
    if (!mounted) return;
    if (ok) {
      final revokedCount = patientState.emergencyCard?.previousCardsRevoked ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            revokedCount > 0 ? l10n.cardIssuedWithRevokeSnack(revokedCount) : l10n.cardIssuedSnack,
          ),
        ),
      );
    } else {
      final err = patientState.emergencyError;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err ?? l10n.cardIssueFailedSnack)));
    }
  }

  Future<void> _revoke() async {
    final l10n = AppLocalizations.of(context);
    final ok = await context.read<PatientProvider>().revokeCurrentCard();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(ok ? l10n.cardRevokedSnack : l10n.cardRevokeFailedSnack)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final card = patientState.emergencyCard;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.emergencyCardTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.emergencyAccessCardTitle,
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: context.palette.emergency)),
            const SizedBox(height: 8),
            Text(
              l10n.emergencyDesc,
              style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
            ),
            const SizedBox(height: 20),
            Text(l10n.fieldsToShare,
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.textPrimary)),
            const SizedBox(height: 8),
            ...kScopeKeys.map((key) {
              final checked = _selected.contains(key);
              return InkWell(
                onTap: () => _toggle(key),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Container(
                        width: 22,
                        height: 22,
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: checked ? context.palette.primary : context.palette.border, width: 2),
                          color: checked ? context.palette.primary : Colors.transparent,
                        ),
                        child: checked ? const Icon(Icons.check, size: 16, color: Colors.white) : null,
                      ),
                      const SizedBox(width: 10),
                      Text(scopeLabel(l10n, key), style: TextStyle(fontSize: 14, color: context.palette.textBody)),
                    ],
                  ),
                ),
              );
            }),
            const SizedBox(height: 4),
            Text(
              l10n.onlyOneLiveCardNote,
              style: TextStyle(fontSize: 11, color: context.palette.textFaint),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: context.palette.emergency, padding: const EdgeInsets.all(16)),
                onPressed: patientState.isIssuingCard || _selected.isEmpty ? null : _issue,
                child: Text(
                  patientState.isIssuingCard ? l10n.issuing : l10n.generateButton,
                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
                ),
              ),
            ),
            if (patientState.isIssuingCard)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Center(child: CircularProgressIndicator(color: context.palette.primary)),
              ),
            if (card != null) _EmergencyCardResult(onRevoke: _revoke),
            const SizedBox(height: 20),
            Center(
              child: TextButton(
                onPressed: () => Navigator.of(context).pop(),
                child: Text('← ${l10n.back}', style: TextStyle(color: context.palette.textMuted)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmergencyCardResult extends StatelessWidget {
  const _EmergencyCardResult({required this.onRevoke});

  final VoidCallback onRevoke;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final card = patientState.emergencyCard!;
    final imageBytes = card.qrImageBytes;

    final expiry = card.expiryAsDateTime;
    final expiryText = expiry != null
        ? DateFormat('d MMM yyyy, h:mm a', Localizations.localeOf(context).toString()).format(expiry)
        : card.grantValidUntil;

    // Deliberately NOT theme-aware: this is a fixed white "printable card"
    // surface (see printNote below — the patient is meant to print/screenshot
    // it) with a QR that needs a light quiet-zone to scan. Its contents stay
    // on the light [AppColors] palette in both app themes for that reason.
    return Container(
      margin: const EdgeInsets.only(top: 24),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        children: [
          if (card.revoked)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              margin: const EdgeInsets.only(bottom: 12),
              decoration: BoxDecoration(color: AppColors.emergencyBg, borderRadius: BorderRadius.circular(8)),
              child: Text(l10n.revokedBadge,
                  style: const TextStyle(color: AppColors.emergency, fontWeight: FontWeight.bold, fontSize: 12)),
            ),
          if (imageBytes != null)
            Opacity(
              opacity: card.revoked ? 0.35 : 1,
              child: Image.memory(imageBytes, width: 180, height: 180),
            )
          else
            SizedBox(
              width: 180,
              height: 180,
              child: Center(child: Text(l10n.couldNotRenderQr)),
            ),
          const SizedBox(height: 12),
          SelectableText(l10n.referenceLabel(card.cardReference),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13, color: AppColors.textBody)),
          const SizedBox(height: 4),
          Text(l10n.validUntilLabel(expiryText), style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
          const SizedBox(height: 8),
          Text(
            l10n.printNote,
            style: const TextStyle(fontSize: 12, color: AppColors.textFaint),
            textAlign: TextAlign.center,
          ),
          if (!card.revoked) ...[
            const SizedBox(height: 12),
            TextButton.icon(
              onPressed: onRevoke,
              icon: const Icon(Icons.block, size: 18, color: AppColors.emergency),
              label: Text(l10n.revokeCard, style: const TextStyle(color: AppColors.emergency)),
            ),
          ],
        ],
      ),
    );
  }
}
