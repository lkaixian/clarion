import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/nfc_card.dart';
import '../models/patient.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../services/api_client.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/loading_view.dart';
import '../widgets/scan_widgets.dart' show LegacyTagBanner;
import '../widgets/section_card.dart';

/// Scope keys accepted by the backend's `POST /emergency/issue` endpoint
/// (see backend/app/schemas.py::EmergencyProfileRequest). The scope is fixed:
/// it is always sent in full, the patient cannot switch fields off.
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

/// What a responder sees from this patient's own record. Mirrors the
/// emergency endpoint's filtering (backend `_scoped_profile`): only items
/// flagged critical, medications must be active, resolved conditions dropped.
class EmergencyPreview {
  const EmergencyPreview({
    required this.bloodType,
    required this.allergies,
    required this.medications,
    required this.conditions,
    required this.omitted,
  });

  final String? bloodType;
  final List<String> allergies;
  final List<String> medications;
  final List<String> conditions;

  /// Items on file that are not shown (not flagged critical).
  final int omitted;

  factory EmergencyPreview.fromPatient(Patient p) {
    final meds = p.medications.where((m) => m.active).toList();
    final conds = p.conditions.where((c) => c.status != 'resolved').toList();
    String join(List<String?> parts) => parts.where((e) => e != null && e.trim().isNotEmpty).join(', ');
    return EmergencyPreview(
      bloodType: (p.bloodType == null || p.bloodType!.trim().isEmpty) ? null : p.bloodType,
      allergies: [
        for (final a in p.allergies.where((a) => a.criticalForEmergency))
          a.reaction == null || a.reaction!.isEmpty ? a.substance : '${a.substance} (${a.reaction})',
      ],
      medications: [
        for (final m in meds.where((m) => m.criticalForEmergency))
          m.drugName + (join([m.dosage, m.frequency]).isEmpty ? '' : ' - ${join([m.dosage, m.frequency])}'),
      ],
      conditions: [for (final c in conds.where((c) => c.criticalForEmergency)) c.name],
      omitted: p.allergies.where((a) => !a.criticalForEmergency).length +
          meds.where((m) => !m.criticalForEmergency).length +
          conds.where((c) => !c.criticalForEmergency).length,
    );
  }
}

class EmergencyScreen extends StatefulWidget {
  const EmergencyScreen({super.key});

  @override
  State<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends State<EmergencyScreen> {
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
    // Keep polling the backend's read-only view of whichever QR card is
    // actually live, so one issued/revoked elsewhere shows up here too.
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

  Future<void> _issue() async {
    final l10n = AppLocalizations.of(context);
    final patientState = context.read<PatientProvider>();

    // The backend auto-revokes the previous QR card on issue; say so first.
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

    final patientId = context.read<AuthProvider>().user?.patientId;
    if (patientId == null) return;
    final ok = await patientState.issueEmergencyCard(patientId: patientId, scope: kScopeKeys);
    if (!mounted) return;
    if (ok) {
      final revokedCount = patientState.emergencyCard?.previousCardsRevoked ?? 0;
      context.snack(revokedCount > 0 ? l10n.cardIssuedWithRevokeSnack(revokedCount) : l10n.cardIssuedSnack);
    } else {
      context.snack(patientState.emergencyError ?? l10n.cardIssueFailedSnack);
    }
  }

  Future<void> _revoke() async {
    final l10n = AppLocalizations.of(context);
    final ok = await context.read<PatientProvider>().revokeCurrentCard();
    if (mounted) context.snack(ok ? l10n.cardRevokedSnack : l10n.cardRevokeFailedSnack);
  }

  void _showPreview() {
    final l10n = AppLocalizations.of(context);
    final patient = context.read<PatientProvider>().patient;
    final preview = patient == null ? null : EmergencyPreview.fromPatient(patient);
    showDialog<void>(
      context: context,
      builder: (dialogContext) {
        final p = dialogContext.palette;
        Widget section(String title, List<String> lines) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary)),
                  if (lines.isEmpty)
                    Text(l10n.previewNone, style: TextStyle(color: p.textMuted))
                  else
                    for (final line in lines) Text(line, style: TextStyle(color: p.textBody)),
                ],
              ),
            );
        return AlertDialog(
          title: Text(l10n.previewTitle),
          content: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(l10n.previewIntro, style: TextStyle(fontSize: 13, color: p.textMuted, height: 1.4)),
                const SizedBox(height: 12),
                section(l10n.scopeBloodType, [if (preview?.bloodType != null) preview!.bloodType!]),
                section(l10n.scopeAllergies, preview?.allergies ?? const []),
                section(l10n.scopeMedications, preview?.medications ?? const []),
                section(l10n.scopeConditions, preview?.conditions ?? const []),
                if (preview != null && preview.omitted > 0)
                  Text(l10n.previewOmitted(preview.omitted), style: TextStyle(fontSize: 12, color: p.textMuted)),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text(MaterialLocalizations.of(dialogContext).closeButtonLabel),
            ),
          ],
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final card = patientState.emergencyCard;
    final p = context.palette;
    final canRegenerate = card != null && !card.revoked;

    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: Text(l10n.emergencyCardTitle),
          bottom: TabBar(tabs: [Tab(text: l10n.emergencyTabQr), Tab(text: l10n.emergencyTabCard)]),
        ),
        body: TabBarView(
          children: [
            SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l10n.emergencyAccessCardTitle,
                      style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: p.emergency)),
                  const SizedBox(height: 8),
                  Text(l10n.emergencyDescFixed,
                      style: TextStyle(fontSize: 13, color: p.textMuted, height: 1.4)),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: Text(l10n.whatWillBeShared,
                            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: p.textPrimary)),
                      ),
                      IconButton(
                        tooltip: l10n.previewTooltip,
                        onPressed: _showPreview,
                        icon: Icon(Icons.info_outline, color: p.primary),
                      ),
                    ],
                  ),
                  for (final key in kScopeKeys)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        children: [
                          Icon(Icons.check_circle_outline, size: 20, color: p.success),
                          const SizedBox(width: 10),
                          Text(scopeLabel(l10n, key), style: TextStyle(fontSize: 14, color: p.textBody)),
                        ],
                      ),
                    ),
                  const SizedBox(height: 4),
                  Text(l10n.sharedAlwaysNote, style: TextStyle(fontSize: 12, color: p.textMuted)),
                  const SizedBox(height: 2),
                  Text(l10n.onlyOneLiveCardNote, style: TextStyle(fontSize: 12, color: p.textMuted)),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: p.emergency,
                        foregroundColor: context.onFill,
                      ),
                      onPressed: patientState.isIssuingCard ? null : _issue,
                      child: Text(
                        patientState.isIssuingCard
                            ? l10n.issuing
                            : (canRegenerate ? l10n.regenerateButton : l10n.generateButton),
                      ),
                    ),
                  ),
                  if (patientState.isIssuingCard)
                    const Padding(padding: EdgeInsets.only(top: 16), child: LoadingView()),
                  if (card != null) _EmergencyCardResult(onRevoke: _revoke),
                ],
              ),
            ),
            const _CardTab(),
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
    final card = context.watch<PatientProvider>().emergencyCard!;
    final imageBytes = card.qrImageBytes;

    final expiry = card.expiryAsDateTime;
    final expiryText = expiry != null
        ? DateFormat('d MMM yyyy', Localizations.localeOf(context).toString()).format(expiry)
        : card.grantValidUntil;

    // Deliberately NOT theme-aware: a fixed white "printable card" surface
    // whose QR needs a light quiet zone to scan, in both app themes.
    return Container(
      margin: const EdgeInsets.only(top: 24),
      padding: const EdgeInsets.all(20),
      width: double.infinity,
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
              child: Image.memory(imageBytes, width: 180, height: 180, semanticLabel: l10n.emergencyAccessCardTitle),
            )
          else
            SizedBox(width: 180, height: 180, child: Center(child: Text(l10n.couldNotRenderQr))),
          const SizedBox(height: 12),
          SelectableText(l10n.referenceLabel(card.cardReference),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13, color: AppColors.textBody)),
          const SizedBox(height: 4),
          Text(l10n.validUntilLabel(expiryText), style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
          const SizedBox(height: 8),
          Text(
            l10n.printNote,
            style: const TextStyle(fontSize: 12, color: AppColors.textMuted),
            textAlign: TextAlign.center,
          ),
          if (!card.revoked) ...[
            const SizedBox(height: 12),
            TextButton.icon(
              onPressed: onRevoke,
              icon: const Icon(Icons.block, color: AppColors.emergency),
              label: Text(l10n.revokeCard, style: const TextStyle(color: AppColors.emergency)),
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- Card tab

String _statusLabel(AppLocalizations l10n, String status) => switch (status) {
      'revoked' => l10n.cardStatusRevoked,
      'expired' => l10n.cardStatusExpired,
      _ => l10n.cardStatusActive,
    };

class _CardTab extends StatefulWidget {
  const _CardTab();

  @override
  State<_CardTab> createState() => _CardTabState();
}

class _CardTabState extends State<_CardTab> {
  final _artKey = GlobalKey();
  String? _selectedId;
  int _tick = 0; // bumped on pull-to-refresh so history reloads too

  String? get _patientId => context.read<AuthProvider>().user?.patientId;

  Future<void> _load() async {
    final id = _patientId;
    if (id == null) return;
    await context.read<PatientProvider>().loadNfcCards(id);
    if (mounted) setState(() => _tick++);
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _share(NfcCard card) async {
    final l10n = AppLocalizations.of(context);
    try {
      final boundary = _artKey.currentContext!.findRenderObject() as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 3);
      final data = await image.toByteData(format: ui.ImageByteFormat.png);
      final dir = await Directory.systemTemp.createTemp('clarion_card');
      final file = File('${dir.path}/clarion-card-${card.last4}.png');
      await file.writeAsBytes(data!.buffer.asUint8List());
      await Share.shareXFiles([XFile(file.path)]);
    } catch (_) {
      if (mounted) context.snack(l10n.shareCardFailed);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final state = context.watch<PatientProvider>();
    final cards = state.nfcCards;
    final p = context.palette;

    if (cards.isEmpty) {
      if (state.isLoadingNfcCards) return const LoadingView();
      if (state.nfcCardsError) return ErrorRetryView(message: l10n.cardsLoadError, onRetry: _load);
      return ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const SizedBox(height: 32),
          Icon(Icons.nfc, size: 56, color: p.textMuted),
          const SizedBox(height: 16),
          Text(l10n.cardsEmptyTitle,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700, color: p.textPrimary)),
          const SizedBox(height: 8),
          Text(l10n.cardsEmptyBody,
              textAlign: TextAlign.center, style: TextStyle(fontSize: 14, color: p.textBody, height: 1.4)),
        ],
      );
    }

    final card = cards.firstWhere((c) => c.id == _selectedId, orElse: () => cards.first);
    final locale = Localizations.localeOf(context).toString();
    final df = DateFormat('d MMM yyyy', locale);
    final validUntil = card.validUntil;
    final validText = validUntil != null ? df.format(validUntil) : card.grantValidUntil;
    final created = card.created;
    final chipLabel = switch (card.tagType) {
      'ntag21x' => l10n.chipNtag21x,
      'ntag424' => l10n.chipNtag424,
      _ => l10n.chipUnknown,
    };
    final patient = state.patient;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(20),
        children: [
          if (cards.length > 1)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  for (final c in cards)
                    ChoiceChip(
                      label: Text('••••${c.last4}  ${_statusLabel(l10n, c.status)}'),
                      selected: c.id == card.id,
                      onSelected: (_) => setState(() => _selectedId = c.id),
                    ),
                ],
              ),
            ),
          RepaintBoundary(
            key: _artKey,
            child: _CardArt(
              name: patient?.fullName ?? '',
              bloodType: patient?.bloodType,
              card: card,
              validText: validText,
            ),
          ),
          const SizedBox(height: 12),
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 12,
            runSpacing: 8,
            children: [
              _StatusChip(status: card.status, label: _statusLabel(l10n, card.status)),
              OutlinedButton.icon(
                onPressed: () => _share(card),
                icon: const Icon(Icons.ios_share),
                label: Text(l10n.shareCardImage),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (card.outdated)
            LegacyTagBanner(title: l10n.cardOutdatedTitle, body: l10n.cardOutdatedBody(validText)),
          SectionCard(
            title: l10n.cardInfoTitle,
            child: Column(
              children: [
                _InfoRow(l10n.cardChipLabel, chipLabel),
                _InfoRow(l10n.cardRegisteredLabel, created != null ? df.format(created) : card.createdAt),
                _InfoRow(
                  l10n.cardValidUntilLabel,
                  card.validDaysLeft != null && card.status == 'active'
                      ? '$validText (${l10n.cardDaysLeft(card.validDaysLeft!)})'
                      : validText,
                ),
                _InfoRow(l10n.cardSharesLabel, card.scope.map((k) => scopeLabel(l10n, k)).join(', ')),
              ],
            ),
          ),
          SectionCard(
            title: l10n.cardHistoryTitle,
            child: _CardHistory(
              key: ValueKey('${card.id}-$_tick'),
              patientId: _patientId,
              cardId: card.id,
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 110, child: Text(label, style: TextStyle(fontSize: 13, color: p.textMuted))),
          Expanded(child: Text(value, style: TextStyle(fontSize: 13, color: p.textPrimary))),
        ],
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.status, required this.label});
  final String status;
  final String label;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final (color, bg, icon) = switch (status) {
      'revoked' => (p.emergency, p.emergencyBg, Icons.block),
      'expired' => (p.attention, p.attentionBg, Icons.schedule),
      _ => (p.success, p.successBg, Icons.check_circle_outline),
    };
    return Semantics(
      label: label,
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(20)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: color)),
          ],
        ),
      ),
    );
  }
}

/// The card drawn like an ID card; exported as a PNG by "Share card image".
/// Fixed colours (not themed): it is a picture of a physical card.
class _CardArt extends StatelessWidget {
  const _CardArt({required this.name, required this.bloodType, required this.card, required this.validText});

  final String name;
  final String? bloodType;
  final NfcCard card;
  final String validText;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final active = card.status == 'active';
    const white = TextStyle(color: Colors.white, fontSize: 12.5, height: 1.35);
    final blood = (bloodType == null || bloodType!.isEmpty) ? l10n.previewNone : bloodType!;
    return Semantics(
      label: '${l10n.cardEndingIn(card.last4)}, ${_statusLabel(l10n, card.status)}',
      child: AspectRatio(
        aspectRatio: 1.586,
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            color: active ? AppColors.primary : const Color(0xFF4B5563),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8)),
                    child: Image.asset(
                      'assets/images/clarion_logo_full.png',
                      height: 24,
                      errorBuilder: (_, _, _) => const Text('CLARION',
                          style: TextStyle(fontWeight: FontWeight.w800, color: AppColors.primary)),
                    ),
                  ),
                  const Spacer(),
                  Text(_statusLabel(l10n, card.status).toUpperCase(),
                      style: white.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1)),
                ],
              ),
              const Spacer(),
              Text(name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700)),
              const SizedBox(height: 6),
              Text('${l10n.scopeBloodType}: $blood', style: white),
              Text(l10n.cardEndingIn(card.last4), style: white.copyWith(fontFamily: 'monospace')),
              Text(l10n.validUntilLabel(validText), style: white),
            ],
          ),
        ),
      ),
    );
  }
}

class _CardHistory extends StatefulWidget {
  const _CardHistory({super.key, required this.patientId, required this.cardId});
  final String? patientId;
  final String cardId;

  @override
  State<_CardHistory> createState() => _CardHistoryState();
}

class _CardHistoryState extends State<_CardHistory> {
  late Future<List<NfcCardEvent>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final id = widget.patientId;
    _future = id == null
        ? Future.value(const <NfcCardEvent>[])
        : context.read<ApiClient>().getNfcCardHistory(id, widget.cardId);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    return FutureBuilder<List<NfcCardEvent>>(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Padding(padding: EdgeInsets.all(16), child: LoadingView());
        }
        if (snap.hasError) {
          return Row(
            children: [
              Expanded(child: Text(l10n.cardHistoryError, style: TextStyle(color: p.textBody))),
              TextButton(onPressed: () => setState(_load), child: Text(l10n.retry)),
            ],
          );
        }
        final events = snap.data!;
        if (events.isEmpty) return EmptyText(l10n.cardHistoryEmpty);
        return Column(
          children: [
            for (var i = 0; i < events.length; i++)
              _TimelineRow(event: events[i], isLast: i == events.length - 1),
          ],
        );
      },
    );
  }
}

class _TimelineRow extends StatelessWidget {
  const _TimelineRow({required this.event, required this.isLast});
  final NfcCardEvent event;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    final locale = Localizations.localeOf(context).toString();
    final (label, icon, color) = switch (event.event) {
      'registered' => (l10n.cardEventRegistered, Icons.add_circle_outline, p.primary),
      'renewed' => (l10n.cardEventRenewed, Icons.autorenew, p.primary),
      'revoked' => (l10n.cardEventRevoked, Icons.block, p.emergency),
      'scanned' => (l10n.cardEventScanned, Icons.nfc, p.attention),
      _ => (event.event, Icons.history, p.textMuted),
    };
    final t = event.time;
    final when = t == null
        ? event.at
        : '${relativeDay(l10n, t, DateTime.now(), locale)}, ${DateFormat.Hm(locale).format(t)}';
    final who = [event.byRole, event.byOrg, event.facility].where((e) => e != null && e.trim().isNotEmpty).join(' · ');
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 28,
            child: Column(
              children: [
                Icon(icon, size: 20, color: color),
                if (!isLast) Expanded(child: Container(width: 2, color: p.border)),
              ],
            ),
          ),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 14, left: 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: p.textPrimary)),
                  Text(when, style: TextStyle(fontSize: 12, color: p.textMuted)),
                  if (who.isNotEmpty)
                    Text(l10n.cardEventBy(who), style: TextStyle(fontSize: 12, color: p.textMuted)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
