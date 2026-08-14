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
  const responderPrefix = 'emergency_responder:';
  if (entry.actor.startsWith(responderPrefix)) {
    final typedName = entry.actor.substring(responderPrefix.length).trim();
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
  return (facility != null && facility.trim().isNotEmpty) ? '$who · $facility' : who;
}

/// `GET /patients/{id}/audit-log` — lets a patient see exactly who accessed
/// their record and when (the transparency half of the PDPA-aligned design
/// described in the backend).
class AuditLogScreen extends StatefulWidget {
  const AuditLogScreen({super.key});

  @override
  State<AuditLogScreen> createState() => _AuditLogScreenState();
}

class _AuditLogScreenState extends State<AuditLogScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final patientId = context.read<AuthProvider>().user?.patientId;
      if (patientId != null) {
        context.read<PatientProvider>().loadAuditLog(patientId);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();

    return Scaffold(
      appBar: AppBar(title: Text(l10n.auditLogTitle)),
      body: patientState.isLoadingAuditLog
          ? const LoadingView()
          : patientState.auditLog.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(l10n.noAccessLogged, style: const TextStyle(color: AppColors.textMuted)),
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: patientState.auditLog.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, i) {
                    final entry = patientState.auditLog[i];
                    return Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: AppColors.border),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(entry.action, style: const TextStyle(fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
                          const SizedBox(height: 4),
                          Text(_formatActor(entry, l10n),
                              style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                          if (entry.fieldsAccessed.isNotEmpty)
                            Text(l10n.fieldsLabel(entry.fieldsAccessed.join(', ')),
                                style: const TextStyle(fontSize: 12, color: AppColors.textMuted)),
                          const SizedBox(height: 4),
                          Text(entry.timestamp, style: const TextStyle(fontSize: 11, color: AppColors.textFaint)),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}
