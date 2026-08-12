import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:nfc_manager/nfc_manager.dart' show NfcAvailability;
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/nfc_service.dart';
import '../theme/app_theme.dart';

enum _ScanMode { qr, nfc, manual }

/// The responder-facing "scan an emergency card" screen — reachable from
/// the Login screen **without** authenticating (matches the backend's
/// design: /emergency/scan and /emergency/nfc/scan need no auth). Offers
/// three ways to look a card up, switchable via a segmented control:
///
/// - **Scan QR**: live camera preview (`mobile_scanner`), decodes the
///   `MEDIBRIDGE-EMERGENCY:<ref>` payload encoded in the QR.
/// - **Tap NFC**: reads a physical NFC card's UID (`nfc_manager`), for
///   patients using a physical card instead of the QR flow.
/// - **Type Manually**: text entry fallback for either a QR card
///   reference or an NFC UID, if the camera/NFC hardware isn't usable.
class EmergencyScannerScreen extends StatefulWidget {
  const EmergencyScannerScreen({super.key});

  @override
  State<EmergencyScannerScreen> createState() => _EmergencyScannerScreenState();
}

class _EmergencyScannerScreenState extends State<EmergencyScannerScreen> {
  _ScanMode _mode = _ScanMode.qr;

  final _refController = TextEditingController();
  final _nameController = TextEditingController();
  final _orgController = TextEditingController();
  bool _manualIsNfc = false;

  MobileScannerController? _qrController;
  bool _qrHandledOnce = false;

  NfcAvailability? _nfcAvailability;
  bool _nfcSessionActive = false;

  bool _loading = false;
  String? _error;
  Map<String, dynamic>? _result;

  @override
  void initState() {
    super.initState();
    _startModeResources();
  }

  @override
  void dispose() {
    _refController.dispose();
    _nameController.dispose();
    _orgController.dispose();
    _qrController?.dispose();
    NfcService.cancelSession();
    super.dispose();
  }

  void _startModeResources() {
    if (_mode == _ScanMode.qr) {
      _qrHandledOnce = false;
      _qrController ??= MobileScannerController(formats: [BarcodeFormat.qrCode]);
      _qrController!.start();
    } else {
      _qrController?.stop();
    }
    if (_mode == _ScanMode.nfc) {
      _checkNfcAndStartSession();
    } else {
      NfcService.cancelSession();
      _nfcSessionActive = false;
    }
  }

  Future<void> _checkNfcAndStartSession() async {
    final availability = await NfcService.checkAvailability();
    if (!mounted) return;
    setState(() => _nfcAvailability = availability);
    if (availability == NfcAvailability.enabled) {
      _beginNfcSession();
    }
  }

  Future<void> _beginNfcSession() async {
    setState(() => _nfcSessionActive = true);
    final uid = await NfcService.readTagUidOnce();
    if (!mounted) return;
    setState(() => _nfcSessionActive = false);
    if (uid != null) {
      await _lookup(nfcUid: uid);
    }
  }

  void _switchMode(_ScanMode mode) {
    if (mode == _mode) return;
    setState(() {
      _mode = mode;
      _result = null;
      _error = null;
    });
    _startModeResources();
  }

  void _onQrDetect(BarcodeCapture capture) {
    if (_qrHandledOnce || _loading) return;
    for (final barcode in capture.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null) continue;
      // QR payload format encoded by the backend: see
      // backend/app/routers/emergency.py::issue_emergency_card ->
      // `f"MEDIBRIDGE-EMERGENCY:{card_reference}"`.
      const prefix = 'MEDIBRIDGE-EMERGENCY:';
      final ref = raw.startsWith(prefix) ? raw.substring(prefix.length) : raw;
      if (ref.isEmpty) continue;
      _qrHandledOnce = true;
      _qrController?.stop();
      _lookup(cardReference: ref);
      return;
    }
  }

  Future<void> _lookup({String? cardReference, String? nfcUid}) async {
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
    });
    try {
      final api = context.read<ApiClient>();
      final result = cardReference != null
          ? await api.scanEmergencyCard(
              cardReference: cardReference,
              responderName: _nameController.text.trim(),
              responderOrg: _orgController.text.trim(),
            )
          : await api.scanNfcCard(
              nfcUid: nfcUid!,
              responderName: _nameController.text.trim(),
              responderOrg: _orgController.text.trim(),
            );
      if (!mounted) return;
      setState(() => _result = result);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _error = e.message);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.responderScanTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l10n.responderScanDesc,
              style: const TextStyle(fontSize: 13, color: AppColors.textMuted, height: 1.4),
            ),
            const SizedBox(height: 16),
            SegmentedButton<_ScanMode>(
              segments: [
                ButtonSegment(value: _ScanMode.qr, label: Text(l10n.scanModeQr), icon: const Icon(Icons.qr_code_scanner)),
                ButtonSegment(value: _ScanMode.nfc, label: Text(l10n.scanModeNfc), icon: const Icon(Icons.nfc)),
                ButtonSegment(value: _ScanMode.manual, label: Text(l10n.scanModeManual), icon: const Icon(Icons.keyboard)),
              ],
              selected: {_mode},
              onSelectionChanged: (s) => _switchMode(s.first),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _nameController,
              decoration: InputDecoration(labelText: l10n.responderNameLabel),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _orgController,
              decoration: InputDecoration(labelText: l10n.responderOrgLabel),
            ),
            const SizedBox(height: 16),
            if (_mode == _ScanMode.qr) _buildQrMode(l10n),
            if (_mode == _ScanMode.nfc) _buildNfcMode(l10n),
            if (_mode == _ScanMode.manual) _buildManualMode(l10n),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(_error!, style: const TextStyle(color: AppColors.emergency)),
              ),
            if (_loading)
              const Padding(
                padding: EdgeInsets.only(top: 16),
                child: Center(child: CircularProgressIndicator(color: AppColors.primary)),
              ),
            if (_result != null) ...[
              const SizedBox(height: 20),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: AppColors.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: _result!.entries
                      .map((e) => Padding(
                            padding: const EdgeInsets.only(bottom: 6),
                            child: Text('${e.key}: ${e.value}',
                                style: const TextStyle(fontSize: 13, color: AppColors.textBody)),
                          ))
                      .toList(),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildQrMode(AppLocalizations l10n) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(16),
      child: SizedBox(
        height: 320,
        child: MobileScanner(
          controller: _qrController,
          onDetect: _onQrDetect,
          errorBuilder: (context, error) => _cameraErrorView(l10n, error),
          placeholderBuilder: (context) => const ColoredBox(
            color: Colors.black,
            child: Center(child: CircularProgressIndicator(color: Colors.white)),
          ),
        ),
      ),
    );
  }

  Widget _cameraErrorView(AppLocalizations l10n, MobileScannerException error) {
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
                ElevatedButton(
                  onPressed: openAppSettings,
                  child: Text(l10n.openAppSettings),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildNfcMode(AppLocalizations l10n) {
    if (!NfcService.isSupportedPlatform) {
      return Text(l10n.nfcUnsupportedPlatform, style: const TextStyle(color: AppColors.textMuted));
    }
    switch (_nfcAvailability) {
      case null:
        return const Center(child: CircularProgressIndicator(color: AppColors.primary));
      case NfcAvailability.unsupported:
        return Text(l10n.nfcUnsupportedDevice, style: const TextStyle(color: AppColors.textMuted));
      case NfcAvailability.disabled:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.nfcDisabled, style: const TextStyle(color: AppColors.textMuted)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: openAppSettings, child: Text(l10n.openAppSettings)),
          ],
        );
      case NfcAvailability.enabled:
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(color: AppColors.chipBg, borderRadius: BorderRadius.circular(16)),
          child: Column(
            children: [
              Icon(Icons.nfc, size: 48, color: _nfcSessionActive ? AppColors.primary : AppColors.textFaint),
              const SizedBox(height: 12),
              Text(
                _nfcSessionActive ? l10n.nfcReadyToTap : l10n.nfcStarting,
                style: const TextStyle(color: AppColors.primary, fontWeight: FontWeight.w600),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        );
    }
  }

  Widget _buildManualMode(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SegmentedButton<bool>(
          segments: [
            ButtonSegment(value: false, label: Text(l10n.cardReferenceLabel)),
            ButtonSegment(value: true, label: Text(l10n.nfcUidLabel)),
          ],
          selected: {_manualIsNfc},
          onSelectionChanged: (s) => setState(() => _manualIsNfc = s.first),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _refController,
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(
            labelText: _manualIsNfc ? l10n.nfcUidLabel : l10n.cardReferenceLabel,
            hintText: _manualIsNfc ? null : l10n.cardReferenceHint,
          ),
        ),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _loading || _refController.text.trim().isEmpty
                ? null
                : () => _manualIsNfc
                    ? _lookup(nfcUid: _refController.text.trim())
                    : _lookup(cardReference: _refController.text.trim()),
            child: Text(_loading ? l10n.scanning : l10n.scanButton),
          ),
        ),
      ],
    );
  }
}
