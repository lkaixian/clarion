import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/audit_log_entry.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

/// Builds the "who" line for one audit-log row -- mirrors the fallback
/// logic used by the web console's `formatAuditActor` (see
/// web/src/pages/PatientDetail.jsx) so a patient sees the same story on
/// both surfaces: prefer the live-resolved display name + role (e.g.
/// "Dr. Aisyah Rahman (clinician)"), fall back to just the role when the
/// name can't be resolved (system row, unauthenticated emergency-scan
/// actor, or a deleted account), and fall back further to a generic
/// "system" label if even the role is missing. actorFacility is a
/// point-in-time snapshot, appended inline only when present -- never
/// render a "· null" or empty facility chip.
String _formatActor(AuditLogEntry entry, AppLocalizations l10n) {
  // Emergency-responder rows have no actorName (never a real users.id) but
  // the name the responder typed in is still recoverable from the raw
  // `actor` string, and their claimed org from `detail` -- mirrors the web
  // console's formatAuditActor (web/src/pages/PatientDetail.jsx), see that
  // function's comment for why the backend produces this shape and why
  // it's deliberately labeled "unverified" rather than shown like a real
  // staff name.
  if (_isUnverifiedResponder(entry)) {
    final typedName = entry.actor.substring(_responderPrefix.length).trim();
    final name = typedName.isEmpty ? 'unidentified' : typedName;
    final detail = entry.detail;
    String? org;
    if (detail != null && detail.startsWith('org=')) {
      final raw = detail.substring('org='.length);
      org = (raw.isEmpty || raw == 'None') ? null : raw;
    }
    final who = '$name (${l10n.auditActorEmergencyResponderUnverified})';
    return org != null ? '$who · $org' : who;
  }

  final name = entry.actorName;
  final role = entry.actorRole;
  final hasName = name != null && name.trim().isNotEmpty;
  final hasRole = role != null && role.trim().isNotEmpty;
  final who = hasName
      ? (hasRole ? '$name ($role)' : name)
      : (hasRole ? role : l10n.auditActorSystemFallback);
  final facility = entry.actorFacility;
  return (facility != null && facility.trim().isNotEmpty)
      ? '$who · $facility'
      : who;
}

const _responderPrefix = 'emergency_responder:';

bool _isUnverifiedResponder(AuditLogEntry entry) =>
    entry.actor.startsWith(_responderPrefix) ||
    entry.actorRole == 'emergency_responder';

/// How privacy-sensitive a given row *looks*, computed entirely client-side
/// from fields already present on each entry -- there's no dedicated
/// backend flag for this. [critical] = a failed/invalid access attempt
/// (someone tried a dead or bogus emergency card/UID against this record);
/// [attention] = a *successful* but unauthenticated emergency-responder
/// view (legitimate use case, but still worth a second glance since it's
/// self-reported and unverified, exactly like the web console's
/// `formatAuditActor` treats it); [routine] = everything else -- the
/// patient viewing their own record, authenticated staff doing normal
/// record-keeping, password/profile self-service, system-originated rows.
enum _AuditSeverity { routine, attention, critical }

_AuditSeverity _severityOf(AuditLogEntry entry) {
  if (entry.action == 'emergency_access_failed') return _AuditSeverity.critical;
  if (entry.action == 'emergency_access' ||
      entry.action == 'emergency_access_nfc') {
    return _AuditSeverity.attention;
  }
  // Defensive catch-all: any other row from an unverified responder actor
  // (shouldn't normally happen outside the two actions above, but if the
  // backend ever adds a new emergency-responder-originated action, don't
  // silently render it as "routine").
  if (_isUnverifiedResponder(entry)) return _AuditSeverity.attention;
  return _AuditSeverity.routine;
}

class _SeverityStyle {
  const _SeverityStyle({
    required this.color,
    required this.bg,
    required this.icon,
    required this.label,
  });
  final Color color;
  final Color bg;
  final IconData icon;
  final String label;
}

// Takes [context] so the severity accents resolve against the active theme
// (context.palette) rather than being frozen to the light [AppColors] values.
_SeverityStyle _styleFor(
  BuildContext context,
  _AuditSeverity severity,
  AppLocalizations l10n,
) {
  final palette = context.palette;
  switch (severity) {
    case _AuditSeverity.critical:
      return _SeverityStyle(
        color: palette.emergency,
        bg: palette.emergencyBg,
        icon: Icons.report_gmailerrorred_outlined,
        label: l10n.auditSeverityCritical,
      );
    case _AuditSeverity.attention:
      return _SeverityStyle(
        color: palette.attention,
        bg: palette.attentionBg,
        icon: Icons.emergency_outlined,
        label: l10n.auditSeverityAttention,
      );
    case _AuditSeverity.routine:
      return _SeverityStyle(
        color: palette.success,
        bg: palette.successBg,
        icon: Icons.verified_user_outlined,
        label: l10n.auditSeverityRoutine,
      );
  }
}

/// A small, action-specific icon layered on top of the severity color --
/// purely cosmetic/legibility, doesn't affect the routine/attention
/// /critical classification above. Falls back to a generic clock icon for
/// any action name not explicitly recognized (including ones this app
/// doesn't know about yet), so a future backend action never renders
/// broken.
IconData _actionIcon(String action) {
  switch (action) {
    case 'view_full_record':
      return Icons.visibility_outlined;
    case 'view_document':
    case 'view_document_file':
      return Icons.description_outlined;
    case 'upload_document':
      return Icons.upload_file_outlined;
    case 'create_patient':
      return Icons.person_add_alt_outlined;
    case 'add_condition':
    case 'update_condition':
      return Icons.medical_information_outlined;
    case 'add_medication':
    case 'update_medication':
      return Icons.medication_outlined;
    case 'add_allergy':
    case 'update_allergy':
      return Icons.warning_amber_outlined;
    case 'add_encounter':
    case 'update_encounter':
      return Icons.event_note_outlined;
    case 'change_password':
    case 'password_reset_via_otp':
    case 'password_reset_otp_requested':
      return Icons.lock_outline;
    case 'update_own_profile':
      return Icons.person_outline;
    case 'generate_handover_brief':
      return Icons.summarize_outlined;
    case 'run_interaction_check':
      return Icons.science_outlined;
    case 'emergency_access':
    case 'emergency_access_nfc':
      return Icons.emergency_outlined;
    case 'emergency_access_failed':
      return Icons.report_gmailerrorred_outlined;
    case 'staff_clock_in':
    case 'staff_clock_out':
      return Icons.badge_outlined;
    case 'register_nfc_card':
    case 'revoke_nfc_card':
      return Icons.nfc;
    default:
      return Icons.history;
  }
}

/// `view_full_record` -> "View full record" -- these action codes come
/// straight from the backend as machine-readable snake_case (never
/// translated server-side), so rather than adding one localization key per
/// action (20+ and growing), this just reformats the same raw string more
/// legibly. Matches how this screen already displayed `entry.action`
/// verbatim before this redesign, just easier to read.
String _prettyAction(String action) {
  if (action.isEmpty) return action;
  final spaced = action.replaceAll('_', ' ');
  return spaced[0].toUpperCase() + spaced.substring(1);
}

/// `GET /patients/{id}/audit-log` — lets a patient see exactly who accessed
/// their record and when (the transparency half of the PDPA-aligned design
/// described in the backend). Redesigned from a plain text dump into
/// color-coded, icon-led cards: each row shows *when*, *who* (name + role +
/// facility when available, with the same "unverified emergency responder"
/// distinction the web console's `formatAuditActor` makes), and a visual
/// signal for whether the access looks routine or worth a second look — see
/// [_severityOf].
class AuditLogScreen extends StatefulWidget {
  const AuditLogScreen({super.key});

  @override
  State<AuditLogScreen> createState() => _AuditLogScreenState();
}

class _AuditLogScreenState extends State<AuditLogScreen> {
  // Lazy window: the last 7 days first, widened on demand (the full
  // history can be years of rows).
  static const _windows = [(7, '7d'), (30, '30d'), (365, '1y'), (2555, '7y')];
  int _days = 7;

  void _load() {
    final patientId = context.read<AuthProvider>().user?.patientId;
    if (patientId != null) {
      context.read<PatientProvider>().loadAuditLog(patientId, days: _days);
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();

    return Scaffold(
      appBar: AppBar(title: Text(l10n.auditLogTitle)),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
            child: Wrap(
              spacing: 8,
              children: [
                for (final (days, label) in _windows)
                  ChoiceChip(
                    label: Text(label),
                    selected: _days == days,
                    onSelected: (_) {
                      setState(() => _days = days);
                      _load();
                    },
                  ),
              ],
            ),
          ),
          Expanded(
            child: patientState.isLoadingAuditLog
                ? const LoadingView()
                : patientState.auditLog.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        l10n.noAccessLogged,
                        style: TextStyle(color: context.palette.textMuted),
                      ),
                    ),
                  )
                : Column(
                    children: [
                      _LegendBar(l10n: l10n),
                      Expanded(
                        child: ListView.separated(
                          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                          itemCount: patientState.auditLog.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 8),
                          itemBuilder: (context, i) => _AuditEntryCard(
                            entry: patientState.auditLog[i],
                            l10n: l10n,
                          ),
                        ),
                      ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

class _LegendBar extends StatelessWidget {
  const _LegendBar({required this.l10n});

  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      decoration: BoxDecoration(
        color: context.palette.surface,
        border: Border(bottom: BorderSide(color: context.palette.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            l10n.auditLogLegendIntro,
            style: TextStyle(fontSize: 11, color: context.palette.textFaint),
          ),
          const SizedBox(height: 6),
          Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              _LegendDot(
                color: context.palette.success,
                label: l10n.auditSeverityRoutine,
              ),
              _LegendDot(
                color: context.palette.attention,
                label: l10n.auditSeverityAttention,
              ),
              _LegendDot(
                color: context.palette.emergency,
                label: l10n.auditSeverityCritical,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(
          label,
          style: TextStyle(
            fontSize: 11,
            color: context.palette.textMuted,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _AuditEntryCard extends StatelessWidget {
  const _AuditEntryCard({required this.entry, required this.l10n});

  final AuditLogEntry entry;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final severity = _severityOf(entry);
    final style = _styleFor(context, severity, l10n);

    return Container(
      decoration: BoxDecoration(
        color: context.palette.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: context.palette.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A000000),
            blurRadius: 3,
            offset: Offset(0, 1),
          ),
        ],
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Left accent bar — the primary, always-visible severity signal
            // (color alone), backed up by the icon badge + text chip below
            // so this isn't a color-only indicator.
            Container(
              width: 5,
              decoration: BoxDecoration(
                color: style.color,
                borderRadius: const BorderRadius.horizontal(
                  left: Radius.circular(12),
                ),
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          width: 32,
                          height: 32,
                          decoration: BoxDecoration(
                            color: style.bg,
                            shape: BoxShape.circle,
                          ),
                          child: Icon(
                            _actionIcon(entry.action),
                            size: 18,
                            color: style.color,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _prettyAction(entry.action),
                            style: TextStyle(
                              fontWeight: FontWeight.w700,
                              fontSize: 14,
                              color: context.palette.textPrimary,
                            ),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 3,
                          ),
                          decoration: BoxDecoration(
                            color: style.bg,
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            style.label,
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: style.color,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Icon(
                          Icons.person_outline,
                          size: 14,
                          color: context.palette.textFaint,
                        ),
                        const SizedBox(width: 4),
                        Expanded(
                          child: Text(
                            _formatActor(entry, l10n),
                            style: TextStyle(
                              fontSize: 12,
                              color: context.palette.textBody,
                            ),
                          ),
                        ),
                      ],
                    ),
                    if (entry.fieldsAccessed.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        l10n.fieldsLabel(entry.fieldsAccessed.join(', ')),
                        style: TextStyle(
                          fontSize: 11,
                          color: context.palette.textMuted,
                        ),
                      ),
                    ],
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Icon(
                          Icons.schedule,
                          size: 12,
                          color: context.palette.textFaint,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          entry.timestamp,
                          style: TextStyle(
                            fontSize: 11,
                            color: context.palette.textFaint,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
