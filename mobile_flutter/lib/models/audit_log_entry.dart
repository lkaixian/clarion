/// Mirrors an entry from `GET /patients/{id}/audit-log`.
class AuditLogEntry {
  final String actor;
  final String? actorRole;
  final String action;
  final List<String> fieldsAccessed;
  final String timestamp;
  final String? detail;

  const AuditLogEntry({
    required this.actor,
    this.actorRole,
    required this.action,
    required this.fieldsAccessed,
    required this.timestamp,
    this.detail,
  });

  factory AuditLogEntry.fromJson(Map<String, dynamic> json) => AuditLogEntry(
        actor: json['actor'] as String? ?? 'unknown',
        actorRole: json['actor_role'] as String?,
        action: json['action'] as String? ?? '',
        fieldsAccessed: (json['fields_accessed'] as List<dynamic>? ?? [])
            .map((e) => e.toString())
            .toList(),
        timestamp: json['timestamp'] as String? ?? '',
        detail: json['detail'] as String?,
      );
}
