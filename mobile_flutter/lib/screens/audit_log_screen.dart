import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/audit_log_entry.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
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
    case 'update_nfc_card':
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

// ---------------------------------------------------------------------------
// Pure view-model helpers (tested in test/audit_log_logic_test.dart).
// ---------------------------------------------------------------------------

/// Single-choice tag filter. Actions not covered by any tag (e.g. staff
/// clock-in) only appear under [all].
enum AuditTag { all, emergency, views, changes, account, failed }

const _viewActions = {
  'view_full_record',
  'view_document',
  'view_document_file',
  'generate_handover_brief',
  'run_interaction_check',
};
const _accountActions = {
  'change_password',
  'update_own_profile',
  'register_nfc_card',
  'revoke_nfc_card',
  'update_nfc_card',
};

/// Which tag an action belongs to; [AuditTag.all] means "no specific tag".
AuditTag auditTagOf(String action) {
  if (action == 'emergency_access_failed') return AuditTag.failed;
  if (action == 'emergency_access' || action == 'emergency_access_nfc') return AuditTag.emergency;
  if (_accountActions.contains(action) || action.startsWith('password_reset')) return AuditTag.account;
  if (_viewActions.contains(action)) return AuditTag.views;
  if (action.startsWith('add_') ||
      action.startsWith('update_') ||
      action == 'create_patient' ||
      action == 'upload_document') {
    return AuditTag.changes;
  }
  return AuditTag.all;
}

/// A failed attempt, or any row from an unverified responder.
bool auditNeedsAttention(AuditLogEntry e) =>
    e.action == 'emergency_access_failed' || _isUnverifiedResponder(e);

Map<AuditTag, int> auditTagCounts(List<AuditLogEntry> entries) {
  final counts = {for (final t in AuditTag.values) t: 0};
  counts[AuditTag.all] = entries.length;
  for (final e in entries) {
    final t = auditTagOf(e.action);
    if (t != AuditTag.all) counts[t] = counts[t]! + 1;
  }
  return counts;
}

List<AuditLogEntry> filterAudit(
  List<AuditLogEntry> entries, {
  AuditTag tag = AuditTag.all,
  bool attentionOnly = false,
}) =>
    [
      for (final e in entries)
        if ((tag == AuditTag.all || auditTagOf(e.action) == tag) && (!attentionOnly || auditNeedsAttention(e))) e,
    ];

/// Consecutive entries by the same actor doing the same action on one day.
/// Entries are newest first, so `entries.first` is the latest.
class AuditRow {
  AuditRow(this.entries);
  final List<AuditLogEntry> entries;
  AuditLogEntry get latest => entries.first;
  int get count => entries.length;
}

class AuditDay {
  AuditDay(this.day, this.rows);
  final DateTime day;
  final List<AuditRow> rows;
}

/// Sorts newest first, groups by local calendar day and collapses
/// consecutive same actor + action entries inside a day.
List<AuditDay> groupAuditByDay(List<AuditLogEntry> entries) {
  final epoch = DateTime.fromMillisecondsSinceEpoch(0);
  final sorted = [...entries]..sort((a, b) => (b.time ?? epoch).compareTo(a.time ?? epoch));
  final days = <AuditDay>[];
  for (final e in sorted) {
    final t = e.time ?? epoch;
    final day = DateTime(t.year, t.month, t.day);
    if (days.isEmpty || days.last.day != day) days.add(AuditDay(day, []));
    final rows = days.last.rows;
    final last = rows.isEmpty ? null : rows.last.latest;
    if (last != null && last.actor == e.actor && last.action == e.action) {
      rows.last.entries.add(e);
    } else {
      rows.add(AuditRow([e]));
    }
  }
  return days;
}

// ---------------------------------------------------------------------------

/// `GET /patients/{id}/audit-log` -- who accessed the patient's record and
/// when. A pinned filter bar (time window, tag, needs-attention), a one-line
/// summary, then rows grouped by day with a thin severity edge.
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
  AuditTag _tag = AuditTag.all;
  bool _attentionOnly = false;
  final _expanded = <String>{};

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

  String _tagLabel(AppLocalizations l10n, AuditTag t) => switch (t) {
        AuditTag.all => l10n.auditTagAll,
        AuditTag.emergency => l10n.auditTagEmergency,
        AuditTag.views => l10n.auditTagViews,
        AuditTag.changes => l10n.auditTagChanges,
        AuditTag.account => l10n.auditTagAccount,
        AuditTag.failed => l10n.auditTagFailed,
      };

  String _windowLabel(AppLocalizations l10n) => switch (_days) {
        7 => l10n.auditWindow7d,
        30 => l10n.auditWindow30d,
        365 => l10n.auditWindow1y,
        _ => l10n.auditWindow7y,
      };

  void _showInfo() {
    final l10n = AppLocalizations.of(context);
    showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(l10n.auditInfoTitle),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(l10n.auditLogLegendIntro),
            const SizedBox(height: 12),
            for (final sev in _AuditSeverity.values.reversed)
              Builder(builder: (_) {
                final st = _styleFor(dialogContext, sev, l10n);
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Container(width: 4, height: 24, color: st.color),
                      const SizedBox(width: 10),
                      Icon(st.icon, size: 20, color: st.color),
                      const SizedBox(width: 8),
                      Expanded(child: Text(st.label)),
                    ],
                  ),
                );
              }),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: Text(MaterialLocalizations.of(dialogContext).closeButtonLabel),
          ),
        ],
      ),
    );
  }

  Widget _chipRow(List<Widget> chips) => SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(
          children: [for (final c in chips) Padding(padding: const EdgeInsets.symmetric(horizontal: 4), child: c)],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final state = context.watch<PatientProvider>();
    final p = context.palette;
    final all = state.auditLog;
    final counts = auditTagCounts(all);
    final tag = counts[_tag] == 0 ? AuditTag.all : _tag;
    final attentionCount = all.where(auditNeedsAttention).length;
    final filtered = filterAudit(all, tag: tag, attentionOnly: _attentionOnly);
    final locale = Localizations.localeOf(context).toString();
    final now = DateTime.now();

    Widget body;
    if (state.isLoadingAuditLog) {
      body = const LoadingView();
    } else if (state.auditLogError) {
      body = ErrorRetryView(message: l10n.auditLoadError, onRetry: _load);
    } else if (all.isEmpty) {
      body = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(l10n.noAccessLogged, style: TextStyle(color: p.textMuted)),
        ),
      );
    } else if (filtered.isEmpty) {
      body = Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(l10n.auditNoMatches, style: TextStyle(color: p.textMuted)),
            const SizedBox(height: 8),
            TextButton(
              onPressed: () => setState(() {
                _tag = AuditTag.all;
                _attentionOnly = false;
              }),
              child: Text(l10n.auditClearFilters),
            ),
          ],
        ),
      );
    } else {
      final groups = groupAuditByDay(filtered);
      body = CustomScrollView(
        slivers: [
          for (final g in groups)
            SliverMainAxisGroup(
              slivers: [
                SliverResizingHeader(
                  child: Container(
                    width: double.infinity,
                    color: p.background,
                    padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
                    child: Semantics(
                      header: true,
                      child: Text(
                        relativeDay(l10n, g.day, now, locale, maxDaysAgo: 1),
                        style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: p.textMuted),
                      ),
                    ),
                  ),
                ),
                SliverList.builder(
                  itemCount: g.rows.length,
                  itemBuilder: (context, i) {
                    final row = g.rows[i];
                    final key = '${row.latest.timestamp}|${row.latest.actor}|${row.latest.action}';
                    return _AuditRowTile(
                      row: row,
                      l10n: l10n,
                      expanded: _expanded.contains(key),
                      onTap: () => setState(() => _expanded.contains(key) ? _expanded.remove(key) : _expanded.add(key)),
                    );
                  },
                ),
              ],
            ),
          const SliverToBoxAdapter(child: SizedBox(height: 16)),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.auditLogTitle),
        actions: [
          IconButton(
            tooltip: l10n.auditInfoTooltip,
            onPressed: _showInfo,
            icon: const Icon(Icons.info_outline),
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            decoration: BoxDecoration(
              color: p.surface,
              border: Border(bottom: BorderSide(color: p.border)),
            ),
            padding: const EdgeInsets.only(top: 4, bottom: 4),
            child: Column(
              children: [
                _chipRow([
                  for (final (days, label) in _windows)
                    ChoiceChip(
                      label: Text(label),
                      selected: _days == days,
                      onSelected: (_) {
                        setState(() => _days = days);
                        _load();
                      },
                    ),
                  FilterChip(
                    avatar: const Icon(Icons.priority_high, size: 18),
                    label: Text('${l10n.auditNeedsAttention} $attentionCount'),
                    selected: _attentionOnly,
                    onSelected: attentionCount == 0 && !_attentionOnly
                        ? null
                        : (v) => setState(() => _attentionOnly = v),
                  ),
                ]),
                _chipRow([
                  for (final t in AuditTag.values)
                    ChoiceChip(
                      label: Text('${_tagLabel(l10n, t)} ${counts[t]}'),
                      selected: tag == t,
                      onSelected: counts[t] == 0 ? null : (_) => setState(() => _tag = t),
                    ),
                ]),
              ],
            ),
          ),
          if (!state.isLoadingAuditLog && !state.auditLogError && all.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  l10n.auditSummary(all.length, _windowLabel(l10n), attentionCount),
                  style: TextStyle(fontSize: 13, color: p.textBody),
                ),
              ),
            ),
          Expanded(child: body),
        ],
      ),
    );
  }
}

class _AuditRowTile extends StatelessWidget {
  const _AuditRowTile({required this.row, required this.l10n, required this.expanded, required this.onTap});

  final AuditRow row;
  final AppLocalizations l10n;
  final bool expanded;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final entry = row.latest;
    final style = _styleFor(context, _severityOf(entry), l10n);
    final locale = Localizations.localeOf(context).toString();
    final t = entry.time;
    final timeText = t == null ? entry.timestamp : DateFormat.Hm(locale).format(t);
    final trailing = row.count > 1 ? l10n.auditCollapsedCount(row.count, timeText) : timeText;
    final detail = entry.detail;
    final showDetail =
        detail != null && detail.isNotEmpty && !(_isUnverifiedResponder(entry) && detail.startsWith('org='));

    return Semantics(
      container: true,
      expanded: expanded,
      child: InkWell(
        onTap: onTap,
        child: Container(
          constraints: const BoxConstraints(minHeight: 56),
          margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
          padding: const EdgeInsets.fromLTRB(10, 8, 8, 8),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(8),
            border: Border(left: BorderSide(color: style.color, width: 3)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(_actionIcon(entry.action), size: 20, color: style.color),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _prettyAction(entry.action),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontWeight: FontWeight.w700, fontSize: 14, color: p.textPrimary),
                        ),
                        Text(
                          _formatActor(entry, l10n),
                          maxLines: expanded ? 3 : 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 12, color: p.textBody),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(trailing, style: TextStyle(fontSize: 12, color: p.textMuted)),
                  Icon(expanded ? Icons.expand_less : Icons.expand_more, size: 20, color: p.textMuted),
                ],
              ),
              if (expanded)
                Padding(
                  padding: const EdgeInsets.only(left: 30, top: 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(style.icon, size: 14, color: style.color),
                          const SizedBox(width: 4),
                          Text(style.label,
                              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: style.color)),
                        ],
                      ),
                      if (entry.fieldsAccessed.isNotEmpty)
                        Text(l10n.fieldsLabel(entry.fieldsAccessed.join(', ')),
                            style: TextStyle(fontSize: 12, color: p.textMuted)),
                      if (showDetail)
                        Text(l10n.auditDetailLabel(detail), style: TextStyle(fontSize: 12, color: p.textMuted)),
                      Text(
                        row.count > 1
                            ? l10n.auditTimesLabel(row.entries
                                .map((e) => e.time == null ? e.timestamp : DateFormat.Hms(locale).format(e.time!))
                                .join(', '))
                            : (t == null ? entry.timestamp : DateFormat('d MMM yyyy, HH:mm:ss', locale).format(t)),
                        style: TextStyle(fontSize: 12, color: p.textMuted),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
