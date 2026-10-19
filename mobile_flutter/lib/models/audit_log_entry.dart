/// Parses a server timestamp to local time; a value with no zone is UTC.
DateTime? parseServerTime(String raw) {
  if (raw.isEmpty) return null;
  final hasZone = RegExp(r'(Z|[+-]\d\d:?\d\d)$').hasMatch(raw);
  return DateTime.tryParse(hasZone ? raw : '${raw}Z')?.toLocal();
}

/// Mirrors an entry from `GET /patients/{id}/audit-log`.
class AuditLogEntry {
  final String actor;
  final String? actorRole;
  final String action;
  final List<String> fieldsAccessed;
  final String timestamp;
  final String? detail;

  /// Resolved LIVE against `users.full_name` at request time (not
  /// snapshotted) -- so it reflects e.g. a display-name change made after
  /// the access happened, and reads as `null` for the "system" actor, the
  /// unauthenticated emergency-scan endpoints' `"emergency_responder:name"`
  /// actor (neither has a matching `User` row), or a user account that's
  /// since been deleted. [actor] itself is still the raw stored actor id
  /// in all of those cases -- this field is purely a nicer display name
  /// layered on top, additive alongside the existing fields.
  final String? actorName;

  /// Point-in-time snapshot of the actor's facility taken when the access
  /// happened (unlike [actorName], this does NOT change retroactively if
  /// the actor later moves facilities). Also nullable/omitted for
  /// system/emergency-responder rows.
  final String? actorFacility;

  DateTime? get time => parseServerTime(timestamp);

  const AuditLogEntry({
    required this.actor,
    this.actorRole,
    required this.action,
    required this.fieldsAccessed,
    required this.timestamp,
    this.detail,
    this.actorName,
    this.actorFacility,
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
        actorName: json['actor_name'] as String?,
        actorFacility: json['actor_facility'] as String?,
      );
}
