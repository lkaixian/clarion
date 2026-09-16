import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:nfc_manager/nfc_manager.dart' show NfcAvailability;
import 'package:permission_handler/permission_handler.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/emergency_scan_result.dart';
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
///   `CLARION-EMERGENCY:<ref>` payload encoded in the QR.
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
  EmergencyScanResult? _result;
  // True when _result came from a tag's own on-card text (no network),
  // not a live server lookup -- drives the "offline / may be outdated"
  // banner in _buildResultCard. Always false outside NFC-tap mode.
  bool _resultIsOffline = false;

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
    // One tap reads BOTH the hardware UID (the online lookup key) and
    // whatever offline text is already written on the tag -- see
    // NfcService.readTagOnce's own doc comment for why this beats reading
    // the UID first and only deciding to re-tap for text if the network
    // call fails.
    final read = await NfcService.readTagOnce();
    if (!mounted) return;
    setState(() => _nfcSessionActive = false);
    if (read.uid != null) {
      await _lookup(nfcUid: read.uid, offlineNdefText: read.ndefText);
    }
  }

  void _switchMode(_ScanMode mode) {
    if (mode == _mode) return;
    setState(() {
      _mode = mode;
      _result = null;
      _error = null;
      _resultIsOffline = false;
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
      // `f"CLARION-EMERGENCY:{card_reference}"`.
      const prefix = 'CLARION-EMERGENCY:';
      final ref = raw.startsWith(prefix) ? raw.substring(prefix.length) : raw;
      if (ref.isEmpty) continue;
      _qrHandledOnce = true;
      _qrController?.stop();
      _lookup(cardReference: ref);
      return;
    }
  }

  Future<void> _lookup({String? cardReference, String? nfcUid, String? offlineNdefText}) async {
    setState(() {
      _loading = true;
      _error = null;
      _result = null;
      _resultIsOffline = false;
    });
    try {
      final api = context.read<ApiClient>();
      final raw = cardReference != null
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
      setState(() => _result = EmergencyScanResult.fromJson(raw));
    } on ApiException catch (e) {
      if (!mounted) return;
      // statusCode == null means no response reached us at all (a
      // connection error, not a real server answer like a 404) -- see
      // ApiException.data's doc comment. THAT specific case, and only
      // that case, is when falling back to whatever's written on the tag
      // itself is appropriate: a real 404 ("not registered") is an
      // authoritative answer from a server that IS reachable, and must
      // not be silently overridden by stale on-tag data.
      if (e.statusCode == null && offlineNdefText != null) {
        final l10n = AppLocalizations.of(context);
        setState(() {
          _result = EmergencyScanResult.fromCompactTagText(
            offlineNdefText,
            placeholderName: l10n.scanResultOfflinePlaceholderName,
          );
          _resultIsOffline = true;
          _error = null;
        });
      } else {
        setState(() => _error = e.message);
      }
    } catch (e) {
      // Deliberately not e.toString() here — never interpolate a raw
      // error object into user-facing text (see api_exception.dart's
      // hardening against the same class of problem for backend errors).
      if (!mounted) return;
      setState(() => _error = AppLocalizations.of(context).unexpectedErrorGeneric);
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
              style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
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
                child: Text(_error!, style: TextStyle(color: context.palette.emergency)),
              ),
            if (_loading)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Center(child: CircularProgressIndicator(color: context.palette.primary)),
              ),
            if (_result != null) ...[
              const SizedBox(height: 20),
              _buildResultCard(l10n, _result!),
            ],
          ],
        ),
      ),
    );
  }

  /// Renders a successful scan lookup as a structured, category-per-card
  /// layout instead of the old flat `key: value` text dump -- deliberately
  /// mirrors the visual language HomeScreen uses for "my own record"
  /// (SectionCard + bulleted lines) so a responder scanning someone else's
  /// card and the patient viewing their own record see the same product,
  /// not two unrelated designs. Distinct colouring per category comes
  /// entirely from the existing AppColors palette (no new colours
  /// invented): allergies use the app's established emergency red, since
  /// that's already the "urgent" colour everywhere else in this app.
  Widget _buildResultCard(AppLocalizations l10n, EmergencyScanResult result) {
    final omitted = result.omittedNonCritical;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 4, bottom: 8),
          child: Text(
            l10n.scanResultFoundTitle,
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: context.palette.textMuted, letterSpacing: 0.5),
          ),
        ),
        // Only ever shown when the server was unreachable and this came
        // from the tag's own on-card text instead -- see _lookup's
        // statusCode == null branch. Deliberately loud (not a quiet
        // footnote): a responder acting on this must know it could be
        // stale, and that a name/age/full history couldn't fit on the tag.
        if (_resultIsOffline) ...[
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            margin: const EdgeInsets.only(bottom: 12),
            decoration: BoxDecoration(
              color: context.palette.emergencyBg,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: context.palette.emergency),
            ),
            child: Row(
              children: [
                Icon(Icons.wifi_off, size: 18, color: context.palette.emergency),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    l10n.scanResultOfflineBanner,
                    style: TextStyle(fontSize: 12, color: context.palette.textBody, fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          ),
        ],
        _ScanResultHeader(result: result, l10n: l10n),
        const SizedBox(height: 16),
        // Allergies first and in the app's established "urgent" red -- the
        // single highest-stakes category for a responder about to
        // administer anything.
        _CategorySection(
          title: l10n.allergiesTitle,
          icon: Icons.warning_amber_rounded,
          iconColor: context.palette.emergency,
          backgroundColor: context.palette.emergencyBg,
          borderColor: context.palette.emergency,
          omittedNotice: (omitted['allergies'] ?? 0) > 0 ? l10n.scanResultOmittedAllergies(omitted['allergies']!) : null,
          child: result.allergies.isEmpty
              ? _EmptyText(l10n.noAllergies)
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: result.allergies.map((a) {
                    final reaction = a.reaction;
                    final title = (reaction != null && reaction.trim().isNotEmpty)
                        ? '${a.substance} (${a.severity}) — $reaction'
                        : '${a.substance} (${a.severity})';
                    return _ScanBulletLine(title);
                  }).toList(),
                ),
        ),
        _CategorySection(
          title: l10n.currentMedicationsTitle,
          icon: Icons.medication_outlined,
          iconColor: context.palette.primary,
          backgroundColor: context.palette.chipBg,
          borderColor: context.palette.primaryLight,
          omittedNotice:
              (omitted['medications'] ?? 0) > 0 ? l10n.scanResultOmittedMedications(omitted['medications']!) : null,
          child: result.medications.isEmpty
              ? _EmptyText(l10n.noActiveMedications)
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: result.medications.map((m) {
                    // Dosage/frequency shown alongside the drug name --
                    // this is the whole point of the backend shape change
                    // this screen is built on top of (medications used to
                    // be bare name strings).
                    final doseFreq = _joinNonEmpty([m.dosage, m.frequency], ', ');
                    final title = doseFreq.isEmpty ? m.drugName : '${m.drugName} — $doseFreq';
                    return _ScanBulletLine(title);
                  }).toList(),
                ),
        ),
        _CategorySection(
          title: l10n.activeConditionsTitle,
          icon: Icons.medical_information_outlined,
          iconColor: context.palette.primary,
          backgroundColor: context.palette.surface,
          borderColor: context.palette.border,
          omittedNotice: (omitted['conditions'] ?? 0) > 0 ? l10n.scanResultOmittedConditions(omitted['conditions']!) : null,
          child: result.conditions.isEmpty
              ? _EmptyText(l10n.noConditions)
              : Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: result.conditions
                      .map((c) => Chip(
                            label: Text(c, style: TextStyle(fontSize: 12, color: context.palette.textBody)),
                            backgroundColor: context.palette.chipBg,
                            side: BorderSide.none,
                          ))
                      .toList(),
                ),
        ),
      ],
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
      return Text(l10n.nfcUnsupportedPlatform, style: TextStyle(color: context.palette.textMuted));
    }
    switch (_nfcAvailability) {
      case null:
        return Center(child: CircularProgressIndicator(color: context.palette.primary));
      case NfcAvailability.unsupported:
        return Text(l10n.nfcUnsupportedDevice, style: TextStyle(color: context.palette.textMuted));
      case NfcAvailability.disabled:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.nfcDisabled, style: TextStyle(color: context.palette.textMuted)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: openAppSettings, child: Text(l10n.openAppSettings)),
          ],
        );
      case NfcAvailability.enabled:
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(color: context.palette.chipBg, borderRadius: BorderRadius.circular(16)),
          child: Column(
            children: [
              Icon(Icons.nfc, size: 48, color: _nfcSessionActive ? context.palette.primary : context.palette.textFaint),
              const SizedBox(height: 12),
              Text(
                _nfcSessionActive ? l10n.nfcReadyToTap : l10n.nfcStarting,
                style: TextStyle(color: context.palette.primary, fontWeight: FontWeight.w600),
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

/// Joins the non-empty entries of [parts] with [separator] -- used to fold
/// optional dosage/frequency fields into a single display string without
/// stray separators when one is missing. Mirrors the identically-named
/// private helper in home_screen.dart (not shared/imported since that one
/// is file-private) so medication lines read the same way on both
/// "my own record" and "what a responder sees".
String _joinNonEmpty(List<String?> parts, String separator) {
  return parts.where((p) => p != null && p.trim().isNotEmpty).join(separator);
}

/// Name / date-of-birth / blood-type header for a scan result -- blood
/// type is deliberately the most visually prominent element here (large,
/// boxed, high-contrast against the primary-coloured header) since that's
/// exactly the kind of at-a-glance fact a first responder scans a card
/// for, before reading anything else.
class _ScanResultHeader extends StatelessWidget {
  const _ScanResultHeader({required this.result, required this.l10n});

  final EmergencyScanResult result;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: context.palette.primary,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  result.fullName,
                  style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                ),
                const SizedBox(height: 4),
                Text(
                  l10n.scanResultAgeValue(
                    result.age?.toString() ?? l10n.scanResultBloodTypeUnknown,
                  ),
                  style: const TextStyle(fontSize: 13, color: Colors.white70),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          _BloodTypeBadge(bloodType: result.bloodType, l10n: l10n),
        ],
      ),
    );
  }
}

class _BloodTypeBadge extends StatelessWidget {
  const _BloodTypeBadge({required this.bloodType, required this.l10n});

  final String? bloodType;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final hasType = bloodType != null && bloodType!.trim().isNotEmpty;
    // Deliberately NOT theme-aware: a fixed white chip on the primary-coloured
    // header for maximum at-a-glance prominence in both themes, so its text
    // stays on the light [AppColors] palette (dark-on-white) regardless.
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text(
            l10n.scopeBloodType.toUpperCase(),
            style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: AppColors.textMuted, letterSpacing: 0.5),
          ),
          const SizedBox(height: 2),
          Text(
            hasType ? bloodType! : l10n.scanResultBloodTypeUnknown,
            style: TextStyle(
              fontSize: hasType ? 24 : 12,
              fontWeight: FontWeight.w800,
              color: AppColors.primary,
            ),
          ),
        ],
      ),
    );
  }
}

/// One category card (Allergies / Medications / Conditions) in the scan
/// result -- structurally the same idea as widgets/section_card.dart's
/// `SectionCard`, but with per-category icon/colour and an optional
/// omitted-items notice, neither of which SectionCard supports, so this is
/// a sibling widget rather than a forced reuse of that one.
class _CategorySection extends StatelessWidget {
  const _CategorySection({
    required this.title,
    required this.icon,
    required this.iconColor,
    required this.backgroundColor,
    required this.borderColor,
    required this.child,
    this.omittedNotice,
  });

  final String title;
  final IconData icon;
  final Color iconColor;
  final Color backgroundColor;
  final Color borderColor;
  final Widget child;
  final String? omittedNotice;

  @override
  Widget build(BuildContext context) {
    final notice = omittedNotice;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: borderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: iconColor),
              const SizedBox(width: 8),
              Text(title, style: TextStyle(fontWeight: FontWeight.bold, color: iconColor, fontSize: 14)),
            ],
          ),
          const SizedBox(height: 8),
          child,
          // Deliberately secondary styling (small, muted, italic) -- this
          // is a "the list might be incomplete" caveat, not itself a piece
          // of clinical data, so it must never visually compete with the
          // actual allergy/medication/condition entries above it.
          if (notice != null) ...[
            const SizedBox(height: 8),
            Text(
              notice,
              style: TextStyle(fontSize: 11, color: context.palette.textMuted, fontStyle: FontStyle.italic, height: 1.3),
            ),
          ],
        ],
      ),
    );
  }
}

class _ScanBulletLine extends StatelessWidget {
  const _ScanBulletLine(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text('•  $text', style: TextStyle(fontSize: 14, color: context.palette.textBody, height: 1.4)),
    );
  }
}

class _EmptyText extends StatelessWidget {
  const _EmptyText(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: TextStyle(fontSize: 13, color: context.palette.textFaint));
  }
}
