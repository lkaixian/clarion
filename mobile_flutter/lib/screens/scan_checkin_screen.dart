import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import 'queue_status_screen.dart';

enum _CheckinMode { qr, manual }

/// Patient-facing "scan the reception desk's self-check-in QR code" screen —
/// modeled closely on EmergencyScannerScreen's QR-scan mode, but simpler:
/// no NFC, no responder-name/org fields, just a live camera QR scan for the
/// station's `CLARION-STATION:<token>` payload, plus a manual token-entry
/// fallback for when the camera can't be used. A successful check-in hands
/// the patient an active queue ticket, so this then hands off to
/// [QueueStatusScreen], which already polls and displays ticket status —
/// this screen doesn't reimplement any of that.
class ScanCheckinScreen extends StatefulWidget {
  const ScanCheckinScreen({super.key});

  @override
  State<ScanCheckinScreen> createState() => _ScanCheckinScreenState();
}

class _ScanCheckinScreenState extends State<ScanCheckinScreen> {
  _CheckinMode _mode = _CheckinMode.qr;

  final _tokenController = TextEditingController();
  final _reasonController = TextEditingController();

  MobileScannerController? _qrController;
  bool _qrHandledOnce = false;

  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _startModeResources();
  }

  @override
  void dispose() {
    _tokenController.dispose();
    _reasonController.dispose();
    _qrController?.dispose();
    super.dispose();
  }

  void _startModeResources() {
    if (_mode == _CheckinMode.qr) {
      _qrHandledOnce = false;
      _qrController ??= MobileScannerController(formats: [BarcodeFormat.qrCode]);
      _qrController!.start();
    } else {
      _qrController?.stop();
    }
  }

  void _switchMode(_CheckinMode mode) {
    if (mode == _mode) return;
    setState(() {
      _mode = mode;
      _error = null;
    });
    _startModeResources();
  }

  void _onQrDetect(BarcodeCapture capture) {
    if (_qrHandledOnce || _loading) return;
    for (final barcode in capture.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null) continue;
      // QR payload format encoded by the backend's reception self-check-in
      // station — see backend/app/routers/reception.py: `f"CLARION-STATION:
      // {station_token}"`. Mirrors how EmergencyScannerScreen._onQrDetect
      // strips its own `CLARION-EMERGENCY:` prefix.
      const prefix = 'CLARION-STATION:';
      final token = raw.startsWith(prefix) ? raw.substring(prefix.length) : raw;
      if (token.isEmpty) continue;
      _qrHandledOnce = true;
      _qrController?.stop();
      _checkIn(token);
      return;
    }
  }

  Future<void> _checkIn(String stationToken) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = context.read<ApiClient>();
      await api.selfCheckin(
        stationToken: stationToken,
        reason: _reasonController.text.trim().isEmpty ? null : _reasonController.text.trim(),
      );
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const QueueStatusScreen()),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        // A failed manual attempt shouldn't need a screen re-entry to try
        // again, but a failed QR scan needs the camera re-armed since
        // _qrHandledOnce latched it off after the first detection.
        _qrHandledOnce = false;
      });
    } catch (e) {
      // Deliberately not e.toString() here -- never interpolate a raw error
      // object into user-facing text (see api_exception.dart's hardening
      // against the same class of problem for backend errors).
      if (!mounted) return;
      setState(() {
        _error = AppLocalizations.of(context).unexpectedErrorGeneric;
        _qrHandledOnce = false;
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.scanCheckinTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l10n.scanCheckinDesc,
              style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
            ),
            const SizedBox(height: 16),
            SegmentedButton<_CheckinMode>(
              segments: [
                ButtonSegment(value: _CheckinMode.qr, label: Text(l10n.scanModeQr), icon: const Icon(Icons.qr_code_scanner)),
                ButtonSegment(value: _CheckinMode.manual, label: Text(l10n.scanModeManual), icon: const Icon(Icons.keyboard)),
              ],
              selected: {_mode},
              onSelectionChanged: (s) => _switchMode(s.first),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _reasonController,
              maxLines: 2,
              decoration: InputDecoration(
                labelText: l10n.checkinReasonLabel,
                hintText: l10n.checkinReasonHint,
              ),
            ),
            const SizedBox(height: 16),
            if (_mode == _CheckinMode.qr) _buildQrMode(l10n),
            if (_mode == _CheckinMode.manual) _buildManualMode(l10n),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(_error!, style: TextStyle(color: context.palette.emergency)),
              ),
            if (_loading)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Center(child: CircularProgressIndicator(color: context.palette.primary)),
              ),
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

  Widget _buildManualMode(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: _tokenController,
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(
            labelText: l10n.stationCodeLabel,
            hintText: l10n.stationCodeHint,
          ),
        ),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _loading || _tokenController.text.trim().isEmpty
                ? null
                : () => _checkIn(_tokenController.text.trim()),
            child: Text(_loading ? l10n.checkinSubmitting : l10n.checkinSubmitButton),
          ),
        ),
      ],
    );
  }
}
