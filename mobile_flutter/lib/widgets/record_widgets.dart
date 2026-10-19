import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../theme/app_theme.dart';

/// Small-caps muted heading above a run of cards.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key});
  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Text(
        title.toUpperCase(),
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: context.palette.textMuted,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

/// Short empty state for parts of the app that need a linked patient record.
class NoRecordNotice extends StatelessWidget {
  const NoRecordNotice({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.folder_off_outlined, size: 40, color: context.palette.textFaint),
            const SizedBox(height: 12),
            Text(
              AppLocalizations.of(context).noPatientRecord,
              textAlign: TextAlign.center,
              style: TextStyle(color: context.palette.textMuted),
            ),
          ],
        ),
      ),
    );
  }
}

/// Joins the non-empty entries of [parts] with [separator].
String joinNonEmpty(List<String?> parts, String separator) {
  return parts.where((p) => p != null && p.trim().isNotEmpty).join(separator);
}

String docTypeLabel(AppLocalizations l10n, String docType) {
  switch (docType) {
    case 'prescription':
      return l10n.docTypePrescription;
    case 'discharge_summary':
      return l10n.docTypeDischargeSummary;
    case 'lab_report':
      return l10n.docTypeLabReport;
    case 'imaging':
      return l10n.docTypeImaging;
    default:
      return l10n.docTypeOther;
  }
}

/// One bullet in a record card, with an optional muted second line and an
/// optional trailing widget (e.g. a share button).
class BulletLine extends StatelessWidget {
  const BulletLine(this.text, {super.key, this.subtitle, this.trailing, this.maxLines = 2});
  final String text;
  final String? subtitle;
  final Widget? trailing;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    final subtitleText = subtitle;
    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '•  $text',
          style: TextStyle(fontSize: 14, color: context.palette.textBody, height: 1.4),
        ),
        if (subtitleText != null && subtitleText.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 18, top: 1),
            child: Text(
              subtitleText,
              maxLines: maxLines,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: context.palette.textMuted, height: 1.3),
            ),
          ),
      ],
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: trailing == null
          ? content
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [Expanded(child: content), trailing!],
            ),
    );
  }
}
