import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:nfc_manager/nfc_manager.dart' show NfcAvailability;
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/emergency_scan_result.dart';
import '../providers/auth_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/device_lock.dart';
import '../services/nfc_service.dart';
import '../services/offline_read_log.dart';
import '../services/tag_crypto.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart' show EmptyText;
import '../widgets/loading_view.dart';
import '../widgets/record_widgets.dart';
import '../widgets/scan_widgets.dart';
import 'scan_hub_screen.dart' show QrKind, parseClarionQr;

const _kNameKey = 'mb_responder_name';
const _kOrgKey = 'mb_responder_org';
const _kAskedKey = 'mb_responder_asked';

enum _Mode { qr, nfc }

/// scanning: camera/NFC armed. looking: lookup in flight. result / failed.
enum _Phase { scanning, looking, result, failed }

/// Responder-facing "scan an emergency card" screen. Reachable from Login
/// WITHOUT signing in (the backend's /emergency/scan and /emergency/nfc/scan
/// need no auth) and from the signed-in Scan hub.
///
/// Scan-first: the camera opens immediately. Responder name/organisation
/// (sent for the card's audit trail) are remembered on this phone and asked
/// once in a bottom sheet.
class EmergencyScannerScreen extends StatefulWidget {
  const EmergencyScannerScreen({
    super.key,
    this.initialTag,
    this.initialCardReference,
    this.deliberateTap = false,
  });

  /// A card tapped while locked / app closed (see services/launch_tag.dart):
  /// skips the tap step and goes straight to the lookup.
  final NfcReadResult? initialTag;

  /// An emergency QR (`/e/<ref>` link or legacy `CLARION-EMERGENCY:`) already decoded elsewhere: straight to lookup.
  final String? initialCardReference;

  /// [initialTag] came from a deliberate in-app tap, not a launch from a
  /// locked phone, so a legacy plaintext tag may be shown offline.
  final bool deliberateTap;

  @override
  State<EmergencyScannerScreen> createState() => _EmergencyScannerScreenState();
}

class _EmergencyScannerScreenState extends State<EmergencyScannerScreen> {
  /// How long the online lookup gets before the tag's own record is used.
  static const _offlineFallbackTimeout = Duration(milliseconds: 1500);

  final _camera = MobileScannerController(formats: [BarcodeFormat.qrCode]);
  final _manual = TextEditingController();

  _Mode _mode = _Mode.qr;
  _Phase _phase = _Phase.scanning;
  bool _latched = false;
  Timer? _rearm;

  String _name = '';
  String _org = '';

  NfcAvailability? _nfcAvailability;
  bool _nfcSessionActive = false;
  int _gen = 0; // bumps on cancel/restart so stale async results are ignored
  NfcTagKind? _tagKind;
  // True when the tapped card has no sealed on-tag record (legacy/blank).
  bool _legacyTag = false;

  String? _notClarion;
  String? _error;
  VoidCallback? _retry;
  EmergencyScanResult? _result;
  // True when _result came from a tag's own on-card text (no network).
  bool _resultIsOffline = false;

  @override
  void initState() {
    super.initState();
    // Online now? Top up the cached tag keys and flush queued offline reads.
    context.read<AuthProvider>().syncOfflineTagData();
    unawaited(_loadIdentity());
    final tag = widget.initialTag;
    final ref = widget.initialCardReference;
    if (tag != null) {
      _mode = _Mode.nfc;
      _phase = _Phase.looking;
      _tagKind = tag.kind;
      _legacyTag = tagIsLegacy(tag.ndefText);
      WidgetsBinding.instance.addPostFrameCallback(
          (_) => _lookup(nfcUid: tag.uid, offlineNdefText: tag.ndefText));
    } else if (ref != null) {
      _phase = _Phase.looking;
      WidgetsBinding.instance.addPostFrameCallback((_) => _lookup(cardReference: ref));
    }
  }

  @override
  void dispose() {
    _rearm?.cancel();
    _gen++;
    _manual.dispose();
    _camera.dispose();
    NfcService.cancelSession();
    super.dispose();
  }

  Future<void> _loadIdentity() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      _name = prefs.getString(_kNameKey) ?? '';
      _org = prefs.getString(_kOrgKey) ?? '';
    });
    final asked = prefs.getBool(_kAskedKey) ?? false;
    if (!asked && (_name.isEmpty || _org.isEmpty) && _phase == _Phase.scanning) {
      await _editIdentity();
    }
  }

  Future<void> _editIdentity() async {
    final name = TextEditingController(text: _name);
    final org = TextEditingController(text: _org);
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) {
        final l10n = AppLocalizations.of(ctx);
        return Padding(
          padding: EdgeInsets.fromLTRB(20, 20, 20, 20 + MediaQuery.of(ctx).viewInsets.bottom),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(l10n.responderIdentityTitle,
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: ctx.palette.textPrimary)),
              const SizedBox(height: 4),
              Text(l10n.responderIdentityNote, style: TextStyle(fontSize: 13, color: ctx.palette.textMuted)),
              const SizedBox(height: 16),
              TextField(
                controller: name,
                textCapitalization: TextCapitalization.words,
                decoration: InputDecoration(labelText: l10n.responderNameLabel),
              ),
              const SizedBox(height: 12),
              TextField(controller: org, decoration: InputDecoration(labelText: l10n.responderOrgLabel)),
              const SizedBox(height: 16),
              ElevatedButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(l10n.save)),
            ],
          ),
        );
      },
    );
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_kAskedKey, true);
    if (saved == true) {
      await prefs.setString(_kNameKey, name.text.trim());
      await prefs.setString(_kOrgKey, org.text.trim());
      if (mounted) {
        setState(() {
          _name = name.text.trim();
          _org = org.text.trim();
        });
      }
    }
    name.dispose();
    org.dispose();
  }

  // ---- scanning ----------------------------------------------------------

  /// Re-arms whichever input the current mode uses.
  void _arm() {
    _latched = false;
    if (_mode == _Mode.qr) {
      NfcService.cancelSession();
      _nfcSessionActive = false;
      _camera.start().catchError((Object _) {});
    } else {
      _camera.stop().catchError((Object _) {});
      unawaited(_checkNfcAndStartSession());
    }
  }

  void _disarm() {
    _gen++;
    _camera.stop().catchError((Object _) {});
    NfcService.cancelSession();
    _nfcSessionActive = false;
  }

  void _setMode(_Mode mode) {
    if (mode == _mode) return;
    setState(() {
      _mode = mode;
      _notClarion = null;
    });
    _disarm();
    _arm();
  }

  void _scanAnother() {
    setState(() {
      _phase = _Phase.scanning;
      _result = null;
      _error = null;
      _notClarion = null;
      _tagKind = null;
      _legacyTag = false;
      _resultIsOffline = false;
    });
    _arm();
  }

  void _onQrDetect(BarcodeCapture capture) {
    if (_latched || _phase != _Phase.scanning || _mode != _Mode.qr) return;
    String? raw;
    for (final b in capture.barcodes) {
      raw = b.rawValue;
      if (raw != null) break;
    }
    if (raw == null) return;
    _latched = true;
    final parsed = parseClarionQr(raw);
    if (parsed == null || parsed.kind != QrKind.emergency) {
      // Not an emergency card (clinic check-in codes land here too): say so
      // and keep scanning after a short pause on the same code.
      setState(() => _notClarion = AppLocalizations.of(context).scanHubNotClarion);
      _rearm?.cancel();
      _rearm = Timer(const Duration(seconds: 2), () {
        if (!mounted) return;
        setState(() => _notClarion = null);
        _latched = false;
      });
      return;
    }
    _startLookup(cardReference: parsed.token);
  }

  void _startLookup({String? cardReference, String? nfcUid, String? offlineNdefText}) {
    _camera.stop().catchError((Object _) {});
    _lookup(cardReference: cardReference, nfcUid: nfcUid, offlineNdefText: offlineNdefText);
  }

  Future<void> _checkNfcAndStartSession() async {
    final gen = ++_gen;
    NfcAvailability availability;
    try {
      availability = await NfcService.checkAvailability();
    } catch (_) {
      availability = NfcAvailability.unsupported;
    }
    if (!mounted || gen != _gen) return;
    setState(() => _nfcAvailability = availability);
    if (availability != NfcAvailability.enabled) return;

    setState(() => _nfcSessionActive = true);
    // One tap reads BOTH the hardware UID (online lookup key) and whatever
    // offline text is on the tag; see NfcService.readTagOnce.
    NfcReadResult read;
    try {
      read = await NfcService.readTagOnce();
    } catch (_) {
      read = const NfcReadResult();
    }
    if (!mounted || gen != _gen) return;
    setState(() {
      _nfcSessionActive = false;
      _tagKind = read.uid != null ? read.kind : null;
      _legacyTag = tagIsLegacy(read.ndefText);
    });
    if (read.uid != null) {
      _startLookup(nfcUid: read.uid, offlineNdefText: read.ndefText);
    } else {
      setState(() => _notClarion = AppLocalizations.of(context).scanHubUnreadableTag);
    }
  }

  // ---- lookup (online first, on-tag record only on a real outage) --------

  /// "The server can't be used right now": no network path (timeout /
  /// connection error / our own 1.5 s cap) or the edge/limiter answering for
  /// a down or overloaded backend. NEVER a 401/403/404 (a real answer, e.g. a
  /// revoked card) and never a TLS failure.
  static bool _isOutage(ApiException e) =>
      e.isUnreachable || const {429, 502, 503, 504}.contains(e.statusCode);

  /// Decrypts the tag's own record on this device (sealed `C1.` blobs) or
  /// passes a legacy plaintext one through, and logs the read to the
  /// hash-chained offline log so it can be attributed on the next sync.
  /// Requires a signed-in user: an offline read nobody can be held to is
  /// refused, not served. The failed attempt is logged too.
  Future<({String? text, _OfflineFailure? failure})> _openOfflineTag(String ndefText, String uid) async {
    final auth = context.read<AuthProvider>();
    final log = auth.offlineLog;
    final userId = auth.user?.id;
    final unlockReason = AppLocalizations.of(context).offlineUnlockReason;
    if (userId == null) return (text: null, failure: _OfflineFailure.needsSignIn);

    String? plain;
    _OfflineFailure? failure;
    var keyId = 0;
    final sealed = TagCrypto.looksSealed(ndefText);
    final revocation = await log.checkRevocation(uid);
    if (revocation == RevocationCheck.revoked) {
      // Revoked while this device was offline: refuse before anything is shown
      // (the read is still logged below, as a failed attempt).
      keyId = sealed ? (TagCrypto.keyIdOf(ndefText) ?? 0) : 0;
      failure = _OfflineFailure.revoked;
    } else if (revocation == RevocationCheck.unknown && !sealed) {
      // No fresh revoked list, and a plaintext tag needs no key to open: refuse
      // rather than show a card that may have been revoked. (A sealed tag
      // needs the cached keys, which share this list's lifetime.)
      failure = _OfflineFailure.keyMissing;
    } else if (sealed) {
      keyId = TagCrypto.keyIdOf(ndefText) ?? 0;
      try {
        // Biometric / device PIN first: the keys are not read until it passes.
        final keys = await log.readKeys(reason: unlockReason);
        plain = await TagCrypto.open(ndefText, uid, keys);
        if (plain == null) {
          failure = keys.containsKey('$keyId') ? _OfflineFailure.damaged : _OfflineFailure.keyMissing;
        }
      } on DeviceLockException catch (e) {
        failure = e.result == DeviceLockResult.noScreenLock
            ? _OfflineFailure.lockRequired
            : _OfflineFailure.authFailed;
      }
    } else if (widget.initialTag != null && !widget.deliberateTap) {
      // Launched from a card tap: anything can claim to be a CLARION card, so
      // only a sealed (authenticated) blob is ever shown on this path.
      failure = _OfflineFailure.damaged;
    } else {
      plain = ndefText; // legacy plaintext tag, deliberate in-app tap
    }
    if (plain != null && _isLapsed(plain)) {
      plain = null;
      failure = _OfflineFailure.expired;
    }
    await log.append(
      userId: userId, uid: uid, keyId: keyId,
      outcome: plain == null ? 'failed' : 'decrypted',
    );
    // Online now? Flush the new entry straight away (no-op when offline).
    auth.syncOfflineTagData();
    return (text: plain, failure: failure);
  }

  /// A sealed record carries `X:<yyyymmdd>` -- the grant's own expiry.
  static bool _isLapsed(String plain) {
    final m = RegExp(r'(?:^|\|)X:(\d{4})(\d{2})(\d{2})(?:\||$)').firstMatch(plain);
    if (m == null) return false;
    final exp = DateTime.utc(int.parse(m.group(1)!), int.parse(m.group(2)!), int.parse(m.group(3)!), 23, 59, 59);
    return DateTime.now().toUtc().isAfter(exp);
  }

  Future<void> _lookup({String? cardReference, String? nfcUid, String? offlineNdefText}) async {
    final gen = ++_gen;
    _retry = () => _startLookup(cardReference: cardReference, nfcUid: nfcUid, offlineNdefText: offlineNdefText);
    setState(() {
      _phase = _Phase.looking;
      _error = null;
      _result = null;
      _resultIsOffline = false;
    });
    try {
      final api = context.read<ApiClient>();
      final raw = cardReference != null
          ? await api.scanEmergencyCard(cardReference: cardReference, responderName: _name, responderOrg: _org)
          : await api.scanNfcCard(
              nfcUid: nfcUid!,
              responderName: _name,
              responderOrg: _org,
              // The tag carries its own record: don't make a responder wait
              // out the client's 12 s default when the network is down.
              timeout: offlineNdefText != null ? _offlineFallbackTimeout : null,
            );
      if (!mounted || gen != _gen) return;
      setState(() {
        _result = EmergencyScanResult.fromJson(raw);
        _phase = _Phase.result;
      });
    } on ApiException catch (e) {
      if (!mounted || gen != _gen) return;
      // Only a genuine no-response outage may fall back to the on-tag record;
      // a real 404 ("not registered", revoked) is authoritative.
      if (_isOutage(e) && offlineNdefText != null) {
        final l10n = AppLocalizations.of(context);
        final opened = await _openOfflineTag(offlineNdefText, nfcUid ?? '');
        if (!mounted || gen != _gen) return;
        setState(() {
          if (opened.text == null) {
            _error = switch (opened.failure!) {
              _OfflineFailure.needsSignIn => l10n.scanResultOfflineSignIn,
              _OfflineFailure.keyMissing => l10n.scanResultOfflineKeyMissing,
              _OfflineFailure.expired => l10n.scanResultOfflineExpired,
              _OfflineFailure.damaged => l10n.scanResultOfflineDamaged,
              _OfflineFailure.revoked => l10n.scanResultOfflineRevoked,
              _OfflineFailure.lockRequired => l10n.scanResultOfflineLockRequired,
              _OfflineFailure.authFailed => l10n.scanResultOfflineAuthFailed,
            };
            _phase = _Phase.failed;
          } else {
            _result = EmergencyScanResult.fromCompactTagText(
              opened.text!,
              placeholderName: l10n.scanResultOfflinePlaceholderName,
            );
            _resultIsOffline = true;
            _phase = _Phase.result;
          }
        });
      } else {
        setState(() {
          _error = e.message;
          _phase = _Phase.failed;
        });
      }
    } catch (_) {
      // Never interpolate a raw error object into user-facing text.
      if (!mounted || gen != _gen) return;
      setState(() {
        _error = AppLocalizations.of(context).unexpectedErrorGeneric;
        _phase = _Phase.failed;
      });
    }
  }

  // ---- build -------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final Widget body;
    switch (_phase) {
      case _Phase.scanning:
        body = _buildScanning(l10n);
      case _Phase.looking:
        body = _buildLooking(l10n);
      case _Phase.failed:
        body = _buildFailed(l10n);
      case _Phase.result:
        body = _buildResult(l10n, _result!);
    }
    return Scaffold(
      appBar: AppBar(title: Text(l10n.responderScanTitle)),
      body: SafeArea(child: body),
    );
  }

  Widget _buildScanning(AppLocalizations l10n) {
    final p = context.palette;
    final who = joinNonEmpty([_name, _org], ', ');
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
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
          const SizedBox(height: 12),
          if (_mode == _Mode.qr) ..._qrBody(l10n) else ..._nfcBody(l10n),
          if (_notClarion != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Semantics(
                liveRegion: true,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.info_outline, size: 18, color: p.attention),
                    const SizedBox(width: 8),
                    Expanded(child: Text(_notClarion!, style: TextStyle(color: p.textBody))),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: _editIdentity,
              icon: const Icon(Icons.badge_outlined),
              label: Text(who.isEmpty ? l10n.responderAdd : '${l10n.responderScanningAs(who)}  ·  ${l10n.responderChange}'),
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _qrBody(AppLocalizations l10n) {
    return [
      ClipRRect(
        borderRadius: BorderRadius.circular(16),
        child: SizedBox(
          height: 340,
          child: MobileScanner(
            controller: _camera,
            onDetect: _onQrDetect,
            errorBuilder: (context, error) => CameraErrorView(error),
            placeholderBuilder: (context) => const ColoredBox(
              color: Colors.black,
              child: Center(child: CircularProgressIndicator(color: Colors.white)),
            ),
          ),
        ),
      ),
      // Typed fallback, only when the camera can't run.
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
                  controller: _manual,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(labelText: l10n.cardReferenceLabel, hintText: l10n.cardReferenceHint),
                ),
                const SizedBox(height: 12),
                ElevatedButton(
                  onPressed: _manual.text.trim().isEmpty ? null : () => _startLookup(cardReference: _manual.text.trim()),
                  child: Text(l10n.scanButton),
                ),
              ],
            ),
          );
        },
      ),
    ];
  }

  List<Widget> _nfcBody(AppLocalizations l10n) {
    return [
      NfcStatusPanel(availability: _nfcAvailability, sessionActive: _nfcSessionActive),
      if (_nfcAvailability == NfcAvailability.enabled && !_nfcSessionActive)
        Padding(
          padding: const EdgeInsets.only(top: 12),
          child: OutlinedButton(onPressed: _arm, child: Text(l10n.tryAgain)),
        ),
    ];
  }

  Widget _buildLooking(AppLocalizations l10n) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const LoadingView(),
            const SizedBox(height: 12),
            Text(l10n.scanning, style: TextStyle(color: context.palette.textBody)),
            const SizedBox(height: 16),
            OutlinedButton(
              onPressed: () {
                _gen++; // drop the in-flight lookup's result
                _scanAnother();
              },
              child: Text(l10n.cancel),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFailed(AppLocalizations l10n) {
    final p = context.palette;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 44, color: p.emergency),
            const SizedBox(height: 12),
            Semantics(
              liveRegion: true,
              child: Text(_error ?? '', textAlign: TextAlign.center, style: TextStyle(color: p.textBody, fontSize: 16)),
            ),
            const SizedBox(height: 20),
            if (_retry != null) ElevatedButton(onPressed: _retry, child: Text(l10n.retry)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _scanAnother, child: Text(l10n.scanAnotherCard)),
          ],
        ),
      ),
    );
  }

  /// Result: what a responder acts on first (blood type, allergies,
  /// conditions, medications) in large type, then emergency contacts.
  Widget _buildResult(AppLocalizations l10n, EmergencyScanResult result) {
    final omitted = result.omittedNonCritical;
    final p = context.palette;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (_resultIsOffline)
          _Banner(
            icon: Icons.wifi_off,
            text: l10n.scanResultOfflineBanner,
            color: p.emergency,
            background: p.emergencyBg,
            bold: true,
          ),
        if (_legacyTag) const LegacyTagBanner(),
        if (_tagKind != null && !_tagKind!.hasReadCounter)
          _Banner(
            icon: Icons.warning_amber_rounded,
            text: l10n.nfcBasicTagWarning,
            color: p.attention,
            background: p.attentionBg,
          ),
        _ScanResultHeader(result: result, l10n: l10n),
        const SizedBox(height: 16),
        _CategorySection(
          title: l10n.allergiesTitle,
          icon: Icons.warning_amber_rounded,
          iconColor: p.emergency,
          backgroundColor: p.emergencyBg,
          borderColor: p.emergency,
          omittedNotice: (omitted['allergies'] ?? 0) > 0 ? l10n.scanResultOmittedAllergies(omitted['allergies']!) : null,
          child: result.allergies.isEmpty
              ? EmptyText(l10n.noAllergies)
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: result.allergies.map((a) {
                    final reaction = a.reaction;
                    final title = (reaction != null && reaction.trim().isNotEmpty)
                        ? '${a.substance} (${a.severity}) · $reaction'
                        : '${a.substance} (${a.severity})';
                    return _ScanBulletLine(title);
                  }).toList(),
                ),
        ),
        _CategorySection(
          title: l10n.activeConditionsTitle,
          icon: Icons.medical_information_outlined,
          iconColor: p.primary,
          backgroundColor: p.surface,
          borderColor: p.border,
          omittedNotice: (omitted['conditions'] ?? 0) > 0 ? l10n.scanResultOmittedConditions(omitted['conditions']!) : null,
          child: result.conditions.isEmpty
              ? EmptyText(l10n.noConditions)
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: result.conditions.map((c) => _ScanBulletLine(c)).toList(),
                ),
        ),
        _CategorySection(
          title: l10n.currentMedicationsTitle,
          icon: Icons.medication_outlined,
          iconColor: p.primary,
          backgroundColor: p.chipBg,
          borderColor: p.primaryLight,
          omittedNotice:
              (omitted['medications'] ?? 0) > 0 ? l10n.scanResultOmittedMedications(omitted['medications']!) : null,
          child: result.medications.isEmpty
              ? EmptyText(l10n.noActiveMedications)
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: result.medications.map((m) {
                    final doseFreq = joinNonEmpty([m.dosage, m.frequency], ', ');
                    return _ScanBulletLine(doseFreq.isEmpty ? m.drugName : '${m.drugName} · $doseFreq');
                  }).toList(),
                ),
        ),
        if (result.contactPhone != null)
          _CategorySection(
            title: l10n.emergencyContactSectionTitle,
            icon: Icons.contact_phone_outlined,
            iconColor: p.primary,
            backgroundColor: p.surface,
            borderColor: p.border,
            child: _ContactRow(result: result),
          ),
        const SizedBox(height: 8),
        ElevatedButton.icon(
          onPressed: _scanAnother,
          icon: const Icon(Icons.qr_code_scanner),
          label: Text(l10n.scanAnotherCard),
        ),
      ],
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({
    required this.icon,
    required this.text,
    required this.color,
    required this.background,
    this.bold = false,
  });
  final IconData icon;
  final String text;
  final Color color;
  final Color background;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(
                fontSize: 13,
                color: context.palette.textBody,
                fontWeight: bold ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ContactRow extends StatelessWidget {
  const _ContactRow({required this.result});
  final EmergencyScanResult result;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final phone = result.contactPhone!;
    final label = joinNonEmpty([result.contactName, result.contactRelationship], ' · ');
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (label.isNotEmpty) Text(label, style: TextStyle(fontSize: 17, color: context.palette.textPrimary)),
              Text(
                phone,
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: context.palette.textPrimary),
              ),
            ],
          ),
        ),
        IconButton.filled(
          tooltip: l10n.callContactLabel(result.contactName ?? phone),
          icon: const Icon(Icons.call),
          onPressed: () => launchUrl(Uri(scheme: 'tel', path: phone)),
        ),
      ],
    );
  }
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
                  style: const TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: Colors.white),
                ),
                const SizedBox(height: 4),
                Text(
                  l10n.scanResultAgeValue(
                    result.age?.toString() ?? l10n.scanResultBloodTypeUnknown,
                  ),
                  style: const TextStyle(fontSize: 15, color: Colors.white),
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
              fontSize: hasType ? 36 : 14,
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
              Text(title, style: TextStyle(fontWeight: FontWeight.bold, color: iconColor, fontSize: 16)),
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
      child: Text('•  $text', style: TextStyle(fontSize: 18, color: context.palette.textBody, height: 1.4)),
    );
  }
}

/// Why a tag couldn't be read without the server -- picks the responder-facing
/// message so each case says what to do next.
enum _OfflineFailure { needsSignIn, keyMissing, expired, damaged, revoked, lockRequired, authFailed }
