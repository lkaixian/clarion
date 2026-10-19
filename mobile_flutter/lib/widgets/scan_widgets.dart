import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:nfc_manager/nfc_manager.dart' show NfcAvailability;
import 'package:permission_handler/permission_handler.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/nfc_service.dart';
import '../services/tag_crypto.dart';
import '../theme/app_theme.dart';
import 'loading_view.dart';

/// Shown in place of the viewfinder when the camera can't start.
class CameraErrorView extends StatelessWidget {
  const CameraErrorView(this.error, {super.key});
  final MobileScannerException error;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final isPermission = error.errorCode == MobileScannerErrorCode.permissionDenied;
    return ColoredBox(
      color: Colors.black,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.no_photography_outlined, color: Colors.white70, size: 40),
              const SizedBox(height: 12),
              Text(
                isPermission ? l10n.cameraPermissionDenied : error.errorDetails?.message ?? error.errorCode.message,
                style: const TextStyle(color: Colors.white70),
                textAlign: TextAlign.center,
              ),
              if (isPermission) ...[
                const SizedBox(height: 12),
                ElevatedButton(onPressed: openAppSettings, child: Text(l10n.openAppSettings)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// NFC unsupported / disabled / waiting-for-tap states, shared by the
/// responder scanner and the scan hub.
class NfcStatusPanel extends StatelessWidget {
  const NfcStatusPanel({super.key, required this.availability, required this.sessionActive});
  final NfcAvailability? availability;
  final bool sessionActive;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    if (!NfcService.isSupportedPlatform) {
      return Text(l10n.nfcUnsupportedPlatform, style: TextStyle(color: p.textMuted));
    }
    switch (availability) {
      case null:
        return const LoadingView();
      case NfcAvailability.unsupported:
        return Text(l10n.nfcUnsupportedDevice, style: TextStyle(color: p.textMuted));
      case NfcAvailability.disabled:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.nfcDisabled, style: TextStyle(color: p.textMuted)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: openAppSettings, child: Text(l10n.openAppSettings)),
          ],
        );
      case NfcAvailability.enabled:
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(color: p.chipBg, borderRadius: BorderRadius.circular(16)),
          child: Column(
            children: [
              Icon(Icons.nfc, size: 48, color: sessionActive ? p.primary : p.textFaint),
              const SizedBox(height: 12),
              Text(
                sessionActive ? l10n.nfcReadyToTap : l10n.nfcStarting,
                style: TextStyle(color: p.primary, fontWeight: FontWeight.w600),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        );
    }
  }
}

/// True when a tapped card has no sealed (v2) on-tag record: a legacy
/// plaintext record, or no record at all.
bool tagIsLegacy(String? ndefText) => ndefText == null || !TagCrypto.looksSealed(ndefText);

/// Persistent amber warning for an older NFC card. Icon + text, never colour
/// alone. The lookup result is still shown beneath it.
class LegacyTagBanner extends StatelessWidget {
  const LegacyTagBanner({super.key, this.title, this.body});

  /// Override the scanner wording (e.g. the patient's own card view).
  final String? title;
  final String? body;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.attentionBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.attention, width: 1.5),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.warning_amber_rounded, size: 22, color: p.attention),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title ?? l10n.legacyTagWarningTitle,
                  style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary),
                ),
                const SizedBox(height: 2),
                Text(body ?? l10n.legacyTagWarningBody, style: TextStyle(fontSize: 13, color: p.textBody, height: 1.35)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
