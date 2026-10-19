import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/audit_log_entry.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/providers/patient_provider.dart';
import 'package:mobile_flutter/screens/audit_log_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/token_storage.dart';

// Local noon of today / yesterday, so the day buckets never straddle a zone.
String at(int daysAgo, int minute) {
  final n = DateTime.now();
  return DateTime(n.year, n.month, n.day - daysAgo, 12, minute).toUtc().toIso8601String();
}

AuditLogEntry e(String action, String ts, {String actor = 'u1', String? role}) =>
    AuditLogEntry(actor: actor, actorRole: role, action: action, fieldsAccessed: const [], timestamp: ts);

void main() {
  test('auditTagOf maps actions to tags, account wins over update_*', () {
    expect(auditTagOf('emergency_access_nfc'), AuditTag.emergency);
    expect(auditTagOf('emergency_access_failed'), AuditTag.failed);
    expect(auditTagOf('view_document_file'), AuditTag.views);
    expect(auditTagOf('run_interaction_check'), AuditTag.views);
    expect(auditTagOf('add_allergy'), AuditTag.changes);
    expect(auditTagOf('update_medication'), AuditTag.changes);
    expect(auditTagOf('upload_document'), AuditTag.changes);
    expect(auditTagOf('update_own_profile'), AuditTag.account);
    expect(auditTagOf('update_nfc_card'), AuditTag.account);
    expect(auditTagOf('password_reset_via_otp'), AuditTag.account);
    expect(auditTagOf('staff_clock_in'), AuditTag.all);
  });

  test('counts, tag filter and needs-attention filter', () {
    final entries = [
      e('view_full_record', at(0, 1)),
      e('emergency_access', at(0, 2), actor: 'emergency_responder:Sam'),
      e('emergency_access_failed', at(0, 3), actor: 'emergency_responder:'),
      e('add_condition', at(0, 4)),
      e('staff_clock_in', at(0, 5)),
    ];
    final c = auditTagCounts(entries);
    expect(c[AuditTag.all], 5);
    expect(c[AuditTag.emergency], 1);
    expect(c[AuditTag.failed], 1);
    expect(c[AuditTag.views], 1);
    expect(c[AuditTag.account], 0);

    expect(filterAudit(entries, tag: AuditTag.changes).single.action, 'add_condition');
    final attention = filterAudit(entries, attentionOnly: true);
    expect(attention.map((x) => x.action), ['emergency_access', 'emergency_access_failed']);
    expect(filterAudit(entries, tag: AuditTag.failed, attentionOnly: true), hasLength(1));
    expect(filterAudit(entries, tag: AuditTag.views, attentionOnly: true), isEmpty);
  });

  test('groups by day newest first and collapses only consecutive same actor+action', () {
    final entries = [
      e('view_full_record', at(1, 0)),
      e('view_full_record', at(0, 1), actor: 'a'),
      e('view_full_record', at(0, 2), actor: 'a'),
      e('view_document', at(0, 3), actor: 'a'),
      e('view_full_record', at(0, 4), actor: 'a'),
      e('view_full_record', at(0, 5), actor: 'b'),
    ];
    final days = groupAuditByDay(entries);
    expect(days, hasLength(2));
    final today = days.first.rows;
    // newest first: b, a(view_full_record x1), a(view_document), a x2
    expect(today.map((r) => r.count), [1, 1, 1, 2]);
    expect(today.last.latest.timestamp, at(0, 2));
    expect(days.last.rows.single.count, 1);
  });

  testWidgets('screen shows summary, filters by tag and expands a row', (tester) async {
    final storage = TokenStorage();
    final api = ApiClient(config: AppConfig(), tokenStorage: storage);
    final patient = PatientProvider(api: api)
      ..auditLog = [
        e('view_full_record', at(0, 9), actor: 'u1', role: 'clinician'),
        e('view_full_record', at(0, 8), actor: 'u1', role: 'clinician'),
        e('emergency_access', at(1, 7), actor: 'emergency_responder:Sam'),
        e('emergency_access_failed', at(1, 6), actor: 'emergency_responder:'),
      ];
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => AuthProvider(api: api, tokenStorage: storage)),
          ChangeNotifierProvider.value(value: patient),
        ],
        child: const MaterialApp(
          locale: Locale('en'),
          supportedLocales: [Locale('en')],
          localizationsDelegates: [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: AuditLogScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('4 accesses in the last 7 days, 2 need attention'), findsOneWidget);
    expect(find.text('Today'), findsOneWidget);
    expect(find.text('Yesterday'), findsOneWidget);
    // the two same-day views collapse into one row
    expect(find.textContaining('x2, latest'), findsOneWidget);

    await tester.tap(find.text('Emergency scans 1'));
    await tester.pump();
    expect(find.text('View full record'), findsNothing);
    expect(find.text('Emergency access'), findsOneWidget);

    await tester.tap(find.text('Emergency access'));
    await tester.pump();
    expect(find.text('Emergency access'), findsNWidgets(2)); // title + severity label
  });
}
