import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:nfc_manager/nfc_manager.dart' show NfcAvailability;
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/nfc_service.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';
import '../widgets/scan_widgets.dart';
import 'emergency_scanner_screen.dart';

enum QrKind { checkin, emergency }

const _kPrefixes = {
  'CLARION-STATION:': QrKind.checkin,
  'CLARION-EMERGENCY:': QrKind.emergency,
};

/// Classifies a scanned QR string by its CLARION prefix; null for anything
/// else (including a known prefix with an empty token).
({QrKind kind, String token})? parseClarionQr(String raw) {
  final value = raw.trim();
  for (final e in _kPrefixes.entries) {
    if (value.startsWith(e.key)) {
      final token = value.substring(e.key.length).trim();
      return token.isEmpty ? null : (kind: e.value, token: token);
    }
  }
  return null;
}

enum _Mode { qr, nfc }

/// The centre "Scan" tab: one QR viewfinder that routes by payload prefix
/// (clinic check-in or someone's emergency card) and an NFC mode for
/// emergency cards. [active] is false while another tab is showing, which
/// stops the camera and any NFC session.
class ScanHubScreen extends StatefulWidget {
  const ScanHubScreen({super.key, required this.active, required this.onCheckedIn});

  final bool active;

  /// Called after a successful self check-in so the shell can show the queue.
  final VoidCallback onCheckedIn;

  @override
  State<ScanHubScreen> createState() => _ScanHubScreenState();
}

class _ScanHubScreenState extends State<ScanHubScreen> {
  final _camera = MobileScannerController(formats: [BarcodeFormat.qrCode]);
  final _reason = TextEditingController();
  final _code = TextEditingController();

  _Mode _mode = _Mode.qr;
  // Set on the first detection until the result is handled (or re-armed).
  bool _latched = false;
  bool _busy = false;
  String? _error;
  Timer? _rearm;

  NfcAvailability? _nfc;
  bool _nfcActive = false;
  int _nfcGen = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _sync());
  }

  @override
  void didUpdateWidget(ScanHubScreen old) {
    super.didUpdateWidget(old);
    if (old.active != widget.active) _sync();
  }

  @override
  void dispose() {
    _rearm?.cancel();
    _nfcGen++;
    NfcService.cancelSession();
    _camera.dispose();
    _reason.dispose();
    _code.dispose();
    super.dispose();
  }

  /// Makes the camera and NFC session match (active tab, selected mode).
  void _sync() {
    if (!mounted) return;
    final qr = widget.active && _mode == _Mode.qr;
    if (qr) {
      _latched = false;
      _camera.start().catchError((Object _) {});
    } else {
      _camera.stop().catchError((Object _) {});
    }
    if (widget.active && _mode == _Mode.nfc) {
      _startNfc();
    } else {
      _nfcGen++;
      _nfcActive = false;
      NfcService.cancelSession();
    }
  }

  void _setMode(_Mode mode) {
    if (mode == _mode) return;
    setState(() {
      _mode = mode;
      _error = null;
    });
    _sync();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_latched || _busy || !widget.active || _mode != _Mode.qr) return;
    String? raw;
    for (final b in capture.barcodes) {
      raw = b.rawValue;
      if (raw != null) break;
    }
    if (raw == null) return;
    _latched = true;
    final parsed = parseClarionQr(raw);
    if (parsed == null) {
      setState(() => _error = AppLocalizations.of(context).scanHubNotClarion);
      // Keep the camera running but ignore the same code for a moment.
      _rearm = Timer(const Duration(seconds: 2), () {
        if (!mounted) return;
        setState(() => _error = null);
        _latched = false;
      });
    } else if (parsed.kind == QrKind.checkin) {
      _checkIn(parsed.token);
    } else {
      _openEmergency(parsed.token);
    }
  }

  Future<void> _checkIn(String stationToken) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<ApiClient>().selfCheckin(stationToken: stationToken, reason: _reason.text);
      if (!mounted) return;
      _code.clear();
      widget.onCheckedIn();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      // Never interpolate a raw error object into user-facing text.
      if (mounted) setState(() => _error = AppLocalizations.of(context).unexpectedErrorGeneric);
    } finally {
      _latched = false;
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openEmergency(String cardReference) async {
    _camera.stop().catchError((Object _) {});
    await Navigator.of(context).push<void>(MaterialPageRoute<void>(
      builder: (_) => EmergencyScannerScreen(initialCardReference: cardReference),
    ));
    if (!mounted) return;
    _latched = false;
    _sync();
  }

  Future<void> _startNfc() async {
    final gen = ++_nfcGen;
    NfcAvailability availability;
    try {
      availability = await NfcService.checkAvailability();
    } catch (_) {
      availability = NfcAvailability.unsupported;
    }
    if (!mounted || gen != _nfcGen) return;
    setState(() {
      _nfc = availability;
      _error = null;
    });
    if (availability != NfcAvailability.enabled) return;

    setState(() => _nfcActive = true);
    NfcReadResult read;
    try {
      read = await NfcService.readTagOnce();
    } catch (_) {
      read = const NfcReadResult();
    }
    if (!mounted || gen != _nfcGen) return;
    setState(() => _nfcActive = false);
    if (read.uid == null) {
      setState(() => _error = AppLocalizations.of(context).scanHubUnreadableTag);
      return;
    }
    await Navigator.of(context).push<void>(MaterialPageRoute<void>(
      builder: (_) => EmergencyScannerScreen(initialTag: read, deliberateTap: true),
    ));
    if (mounted && widget.active && _mode == _Mode.nfc) _startNfc();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.navScan)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SegmentedButton<_Mode>(
              style: SegmentedButton.styleFrom(minimumSize: const Size(0, 48)),
              segments: [
                ButtonSegment(value: _Mode.qr, label: Text(l10n.scanModeQr), icon: const Icon(Icons.qr_code_scanner)),
                ButtonSegment(value: _Mode.nfc, label: Text(l10n.scanModeNfc), icon: const Icon(Icons.nfc)),
              ],
              selected: {_mode},
              onSelectionChanged: (s) => _setMode(s.first),
            ),
            const SizedBox(height: 16),
            if (_mode == _Mode.qr) ..._qrMode(l10n) else ..._nfcMode(l10n),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Semantics(
                  liveRegion: true,
                  child: Text(_error!, style: TextStyle(color: p.emergency)),
                ),
              ),
            if (_busy) const Padding(padding: EdgeInsets.only(top: 16), child: LoadingView()),
          ],
        ),
      ),
    );
  }

  List<Widget> _qrMode(AppLocalizations l10n) {
    return [
      Text(
        l10n.scanHubQrHint,
        style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
      ),
      const SizedBox(height: 12),
      ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: SizedBox(
          height: 300,
          child: MobileScanner(
            controller: _camera,
            onDetect: _onDetect,
            errorBuilder: (context, error) => CameraErrorView(error),
            placeholderBuilder: (context) => const ColoredBox(
              color: Colors.black,
              child: Center(child: CircularProgressIndicator(color: Colors.white)),
            ),
          ),
        ),
      ),
      const SizedBox(height: 16),
      TextField(
        controller: _reason,
        maxLines: 2,
        decoration: InputDecoration(labelText: l10n.checkinReasonLabel, hintText: l10n.checkinReasonHint),
      ),
      // Typed fallback, only when the camera can't run (e.g. permission denied).
      ValueListenableBuilder<MobileScannerState>(
        valueListenable: _camera,
        builder: (context, state, _) {
          if (state.error == null) return const SizedBox.shrink();
          return Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: _code,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(labelText: l10n.stationCodeLabel, hintText: l10n.stationCodeHint),
                ),
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: _busy || _code.text.trim().isEmpty ? null : () => _checkIn(_code.text.trim()),
                  child: Text(_busy ? l10n.checkinSubmitting : l10n.checkinSubmitButton),
                ),
              ],
            ),
          );
        },
      ),
    ];
  }

  List<Widget> _nfcMode(AppLocalizations l10n) {
    return [
      NfcStatusPanel(availability: _nfc, sessionActive: _nfcActive),
      if (_nfc == NfcAvailability.enabled && !_nfcActive)
        Padding(
          padding: const EdgeInsets.only(top: 12),
          child: OutlinedButton(onPressed: _startNfc, child: Text(l10n.tryAgain)),
        ),
    ];
  }
}
