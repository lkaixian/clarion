import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

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
                          Text('${entry.actor}${entry.actorRole != null ? ' (${entry.actorRole})' : ''}',
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
