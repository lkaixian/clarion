import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/emergency_scan_result.dart';
import '../theme/app_theme.dart';
import 'record_widgets.dart';
import 'scan_widgets.dart' show LegacyTagBanner;

/// Where the scanner's own position stands for the scan on screen.
enum ScanLocStatus { sharing, shared, off, denied, unavailable }

/// Responder-facing label for a scan `tier`; null for an unknown value.
String? scanTierLabel(AppLocalizations l10n, String? tier) => switch (tier) {
      'public' => l10n.scanTierPublic,
      'responder' => l10n.scanTierResponder,
      'paramedic' => l10n.scanTierParamedic,
      'clinical' => l10n.scanTierClinical,
      _ => null,
    };

/// 0 = life-threatening first.
int _severityRank(String s) {
  final v = s.toLowerCase();
  if (v.contains('severe') || v.contains('life')) return 0;
  if (v.contains('moderate')) return 1;
  return 2;
}

String _severityWord(AppLocalizations l10n, String s) {
  final v = s.toLowerCase();
  if (v.contains('severe') || v.contains('life')) return l10n.scanSeveritySevere;
  if (v.contains('moderate')) return l10n.scanSeverityModerate;
  if (v.contains('mild')) return l10n.scanSeverityMild;
  return s.trim();
}

/// The scan result, laid out for a responder reading under stress: who and at
/// what access level, severe allergies first (red, severity in words and an
/// icon), conditions, medications, then ONE big Call button for the emergency
/// contact. Sections a tier does not include are left out rather than shown as
/// "none", so a missing list is never mistaken for an empty one.
class ScanResultView extends StatelessWidget {
  const ScanResultView({
    super.key,
    required this.result,
    required this.onScanAnother,
    this.offline = false,
    this.legacyTag = false,
    this.basicTagWarning = false,
    this.locStatus,
    this.locAccuracyM,
  });

  final EmergencyScanResult result;
  final VoidCallback onScanAnother;
  final bool offline;
  final bool legacyTag;

  /// The tapped tag is an NTAG without a tamper-proof read counter.
  final bool basicTagWarning;
  final ScanLocStatus? locStatus;

  /// Accuracy of the position that was shared (metres), when known.
  final double? locAccuracyM;

  bool get _isPublic => result.tier == 'public';
  bool get _showsMeds => !_isPublic && result.tier != 'responder';
  bool get _showsContact => result.contactPhone != null || (result.tier != null && !_isPublic);

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    final omitted = result.omittedNonCritical;
    final allergies = [...result.allergies]..sort((a, b) => _severityRank(a.severity).compareTo(_severityRank(b.severity)));
    final none = l10n.scanNoneCritical;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (offline)
          ScanBanner(
            icon: Icons.wifi_off,
            text: l10n.scanResultOfflineBanner,
            color: p.emergency,
            background: p.emergencyBg,
            bold: true,
          ),
        if (legacyTag) const LegacyTagBanner(),
        if (basicTagWarning)
          ScanBanner(
            icon: Icons.warning_amber_rounded,
            text: l10n.nfcBasicTagWarning,
            color: p.attention,
            background: p.attentionBg,
          ),
        _Header(result: result, l10n: l10n, showBlood: !_isPublic),
        const SizedBox(height: 16),
        _Section(
          title: l10n.allergiesTitle,
          icon: Icons.warning_amber_rounded,
          color: p.emergency,
          background: p.emergencyBg,
          borderWidth: 2,
          omittedNotice: (omitted['allergies'] ?? 0) > 0 ? l10n.scanResultOmittedAllergies(omitted['allergies']!) : null,
          children: allergies.isEmpty
              ? [_None(none)]
              : [for (final a in allergies) _AllergyRow(allergy: a, l10n: l10n)],
        ),
        _Section(
          title: l10n.activeConditionsTitle,
          icon: Icons.medical_information_outlined,
          color: p.primary,
          background: p.surface,
          omittedNotice: (omitted['conditions'] ?? 0) > 0 ? l10n.scanResultOmittedConditions(omitted['conditions']!) : null,
          children: result.conditions.isEmpty ? [_None(none)] : [for (final c in result.conditions) _Line(c)],
        ),
        if (_showsMeds)
          _Section(
            title: l10n.currentMedicationsTitle,
            icon: Icons.medication_outlined,
            color: p.primary,
            background: p.chipBg,
            omittedNotice:
                (omitted['medications'] ?? 0) > 0 ? l10n.scanResultOmittedMedications(omitted['medications']!) : null,
            children: result.medications.isEmpty
                ? [_None(none)]
                : [
                    for (final m in result.medications)
                      _Line(() {
                        final doseFreq = joinNonEmpty([m.dosage, m.frequency], ', ');
                        return doseFreq.isEmpty ? m.drugName : '${m.drugName} · $doseFreq';
                      }()),
                  ],
          ),
        if (_showsContact)
          _Section(
            title: l10n.emergencyContactSectionTitle,
            icon: Icons.contact_phone_outlined,
            color: p.primary,
            background: p.surface,
            children: [_Contact(result: result, l10n: l10n)],
          ),
        if (locStatus != null) _LocationLine(status: locStatus!, accuracyM: locAccuracyM, l10n: l10n),
        const SizedBox(height: 8),
        ElevatedButton.icon(
          style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(56)),
          onPressed: onScanAnother,
          icon: const Icon(Icons.qr_code_scanner),
          label: Text(l10n.scanAnotherCard),
        ),
      ],
    );
  }
}

class ScanBanner extends StatelessWidget {
  const ScanBanner({
    super.key,
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
                fontSize: 14,
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

/// Name + age, access-level badge and (above all) the blood type.
class _Header extends StatelessWidget {
  const _Header({required this.result, required this.l10n, required this.showBlood});
  final EmergencyScanResult result;
  final AppLocalizations l10n;
  final bool showBlood;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final fg = context.onFill;
    final isPublic = result.tier == 'public';
    final tierLabel = scanTierLabel(l10n, result.tier);
    final name = result.fullName.trim().isEmpty ? l10n.scanNameHidden : result.fullName;
    final age = result.age != null
        ? l10n.scanResultAgeValue(result.age.toString())
        : (isPublic ? null : l10n.scanResultAgeValue(l10n.scanResultBloodTypeUnknown));
    final blood = (result.bloodType ?? '').trim();
    final semantics = [
      name,
      ?age,
      if (showBlood) '${l10n.scopeBloodType}: ${blood.isEmpty ? l10n.scanResultBloodTypeUnknown : blood}',
      if (tierLabel != null) l10n.scanTierSemantics(tierLabel),
    ].join('. ');

    return Semantics(
      container: true,
      label: semantics,
      excludeSemantics: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(color: p.primary, borderRadius: BorderRadius.circular(16)),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 12,
              runSpacing: 12,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: TextStyle(fontSize: 26, fontWeight: FontWeight.bold, color: fg)),
                    if (age != null) Text(age, style: TextStyle(fontSize: 16, color: fg)),
                  ],
                ),
                if (showBlood) _BloodBadge(bloodType: blood, l10n: l10n),
              ],
            ),
            if (tierLabel != null) ...[
              const SizedBox(height: 12),
              _TierBadge(label: isPublic ? l10n.scanTierPublic : tierLabel, isPublic: isPublic),
            ],
            if (isPublic) ...[
              const SizedBox(height: 8),
              Text(l10n.scanTierPublicHint, style: TextStyle(fontSize: 14, color: fg, height: 1.3)),
            ],
          ],
        ),
      ),
    );
  }
}

class _TierBadge extends StatelessWidget {
  const _TierBadge({required this.label, required this.isPublic});
  final String label;
  final bool isPublic;

  @override
  Widget build(BuildContext context) {
    // Fixed white pill (like the blood-type chip): same look in both themes.
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(20)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(isPublic ? Icons.lock_outline : Icons.verified_user_outlined, size: 18, color: AppColors.primary),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              label,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: AppColors.primary),
            ),
          ),
        ],
      ),
    );
  }
}

class _BloodBadge extends StatelessWidget {
  const _BloodBadge({required this.bloodType, required this.l10n});
  final String bloodType;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final hasType = bloodType.isNotEmpty;
    // Fixed white chip on the header, dark-on-white in both themes.
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12)),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            l10n.scopeBloodType.toUpperCase(),
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: AppColors.textBody, letterSpacing: 0.5),
          ),
          const SizedBox(height: 2),
          Text(
            hasType ? bloodType : l10n.scanResultBloodTypeUnknown,
            style: TextStyle(fontSize: hasType ? 40 : 16, fontWeight: FontWeight.w800, color: AppColors.primary),
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({
    required this.title,
    required this.icon,
    required this.color,
    required this.background,
    required this.children,
    this.borderWidth = 1,
    this.omittedNotice,
  });

  final String title;
  final IconData icon;
  final Color color;
  final Color background;
  final double borderWidth;
  final List<Widget> children;
  final String? omittedNotice;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final notice = omittedNotice;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: borderWidth > 1 ? color : p.border, width: borderWidth),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            header: true,
            child: Row(
              children: [
                ExcludeSemantics(child: Icon(icon, size: 22, color: color)),
                const SizedBox(width: 8),
                Expanded(child: Text(title, style: TextStyle(fontWeight: FontWeight.w800, color: color, fontSize: 18))),
              ],
            ),
          ),
          const SizedBox(height: 10),
          ...children,
          if (notice != null) ...[
            const SizedBox(height: 8),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ExcludeSemantics(child: Icon(Icons.info_outline, size: 18, color: p.textBody)),
                const SizedBox(width: 6),
                Expanded(child: Text(notice, style: TextStyle(fontSize: 14, color: p.textBody, height: 1.3))),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _None extends StatelessWidget {
  const _None(this.text);
  final String text;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: TextStyle(fontSize: 16, color: context.palette.textBody, height: 1.3));
}

class _Line extends StatelessWidget {
  const _Line(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text('•  $text', style: TextStyle(fontSize: 18, color: context.palette.textPrimary, height: 1.4)),
    );
  }
}

class _AllergyRow extends StatelessWidget {
  const _AllergyRow({required this.allergy, required this.l10n});
  final ScanAllergy allergy;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final rank = _severityRank(allergy.severity);
    final severity = _severityWord(l10n, allergy.severity);
    final reaction = (allergy.reaction ?? '').trim();
    final icon = switch (rank) {
      0 => Icons.dangerous_outlined,
      1 => Icons.warning_amber_rounded,
      _ => Icons.info_outline,
    };
    return Semantics(
      label: [
        allergy.substance,
        if (severity.isNotEmpty) l10n.scanSeverityLabel(severity),
        if (reaction.isNotEmpty) reaction,
      ].join('. '),
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 26, color: p.emergency),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    allergy.substance,
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: p.textPrimary, height: 1.2),
                  ),
                  if (severity.isNotEmpty)
                    Text(
                      reaction.isEmpty ? severity : '$severity · $reaction',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: p.emergency),
                    )
                  else if (reaction.isNotEmpty)
                    Text(reaction, style: TextStyle(fontSize: 16, color: p.textBody)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Contact extends StatelessWidget {
  const _Contact({required this.result, required this.l10n});
  final EmergencyScanResult result;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final phone = result.contactPhone;
    if (phone == null) return _None(l10n.scanNoContact);
    final who = joinNonEmpty([result.contactName, result.contactRelationship], ' · ');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (who.isNotEmpty) Text(who, style: TextStyle(fontSize: 18, color: p.textPrimary)),
        Text(phone, style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            key: const Key('call-contact'),
            style: ElevatedButton.styleFrom(
              minimumSize: const Size.fromHeight(60),
              backgroundColor: p.success,
              foregroundColor: context.onFill,
              textStyle: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
            ),
            onPressed: () => unawaited(
              launchUrl(Uri(scheme: 'tel', path: phone)).then((_) => true, onError: (_) => false),
            ),
            icon: const Icon(Icons.call),
            label: Text(l10n.callContactLabel(result.contactName ?? phone)),
          ),
        ),
      ],
    );
  }
}

class _LocationLine extends StatelessWidget {
  const _LocationLine({required this.status, required this.l10n, this.accuracyM});
  final ScanLocStatus status;
  final double? accuracyM;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final (icon, text, color) = switch (status) {
      ScanLocStatus.shared => (
          Icons.check_circle_outline,
          accuracyM == null || !accuracyM!.isFinite
              ? l10n.scanLocShared
              : (accuracyM! > 500 ? l10n.scanLocSharedApprox : l10n.scanLocSharedAccuracy(accuracyM!.round())),
          p.success,
        ),
      ScanLocStatus.sharing => (Icons.my_location, l10n.scanLocSharing, p.primary),
      ScanLocStatus.off => (Icons.location_off_outlined, l10n.scanLocOff, p.textBody),
      ScanLocStatus.denied => (Icons.location_off_outlined, l10n.scanLocDenied, p.textBody),
      ScanLocStatus.unavailable => (Icons.location_disabled_outlined, l10n.scanLocUnavailable, p.textBody),
    };
    return Semantics(
      liveRegion: true,
      container: true,
      label: text,
      excludeSemantics: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, size: 20, color: color),
            const SizedBox(width: 8),
            Expanded(child: Text(text, style: TextStyle(fontSize: 14, color: p.textBody, height: 1.3))),
          ],
        ),
      ),
    );
  }
}
