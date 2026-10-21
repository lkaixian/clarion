import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/user.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/providers/patient_provider.dart';
import 'package:mobile_flutter/providers/queue_provider.dart';
import 'package:mobile_flutter/providers/reminders_provider.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/api_exception.dart';
import 'package:mobile_flutter/services/token_storage.dart';
import 'package:mobile_flutter/theme/app_theme.dart';
import 'package:mobile_flutter/widgets/role_switcher.dart';

class MemStorage extends TokenStorage {
  final m = <String, Object?>{};
  @override
  Future<void> saveToken(String t) async => m['token'] = t;
  @override
  Future<void> saveUser(Map<String, dynamic> u) async => m['user'] = u;
  @override
  Future<void> saveActivePatient(String? id) async => m['active'] = id;
  @override
  Future<void> saveActiveRole(String? r) async => m['role'] = r;
}

Map<String, dynamic> userJson(String role, List<String>? roles) => {
      'id': 'u1',
      'email': 'a@x.test',
      'full_name': 'Nia',
      'role': role,
      'patient_id': role == 'patient' ? 'p1' : null,
      'acting_for': false,
      'roles': ?roles,
      'responder_tier': null,
    };

class FakeApi extends ApiClient {
  FakeApi(MemStorage s) : super(config: AppConfig(), tokenStorage: s);
  bool fail = false;
  bool needReauth = false;
  bool needsCode = false;
  final calls = <List<String?>>[];
  @override
  Future<Map<String, dynamic>> switchRole(String role, {String? password, String? code}) async {
    calls.add([role, password, code]);
    if (fail) throw ApiException('No such role.', statusCode: 403);
    if (needReauth && role == 'admin') {
      if (password == null) {
        throw ApiException('x', statusCode: 428, data: {
          'detail': {'detail': 'Confirm', 'reauth_required': true, 'needs_code': needsCode}
        });
      }
      if (password != 'pw' || (needsCode && code != '123456')) {
        throw ApiException('Wrong password.', statusCode: 400);
      }
    }
    return {'access_token': 'tok-$role', 'user': userJson(role, ['clinician', 'patient', 'admin'])};
  }
}

void main() {
  test('User roles default to [role]; tier parsed', () {
    final u = MBUser.fromJson(userJson('clinician', null));
    expect(u.roles, ['clinician']);
    final v = MBUser.fromJson({...userJson('patient', ['patient', 'emergency_responder']), 'responder_tier': 'paramedic'});
    expect(v.roles.length, 2);
    expect(MBUser.fromJson(v.toJson()).responderTier, 'paramedic');
  });

  test('switchRole stores token, user, role; drops profile; errors returned', () async {
    final storage = MemStorage();
    final api = FakeApi(storage);
    final auth = AuthProvider(api: api, tokenStorage: storage);
    expect((await auth.switchRole('patient')).ok, isTrue);
    expect(storage.m['token'], 'tok-patient');
    expect(storage.m['role'], 'patient');
    expect(storage.m['active'], isNull);
    expect(auth.user!.role, 'patient');
    expect(auth.user!.patientId, 'p1');
    api.fail = true;
    expect((await auth.switchRole('admin')).error, 'No such role.');
    expect(auth.user!.role, 'patient');
  });

  Future<AuthProvider> open(WidgetTester tester, List<String> roles, {FakeApi? withApi}) async {
    final storage = MemStorage();
    final api = withApi ?? FakeApi(storage);
    final auth = AuthProvider(api: api, tokenStorage: storage)
      ..user = MBUser.fromJson(userJson('clinician', roles));
    await tester.pumpWidget(MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => PatientProvider(api: api)),
        ChangeNotifierProvider(create: (_) => QueueProvider(api: api)),
        ChangeNotifierProvider(create: (_) => RemindersProvider()),
        Provider<ApiClient>.value(value: api),
      ],
      child: MaterialApp(
        locale: const Locale('en'),
        supportedLocales: const [Locale('en')],
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Scaffold(appBar: AppBar(actions: const [RoleSwitcherAction()])),
      ),
    ));
    await tester.pump();
    return auth;
  }

  testWidgets('hidden with one role', (tester) async {
    await open(tester, ['clinician']);
    expect(find.byKey(const Key('role-switcher')), findsNothing);
  });

  testWidgets('visible with two roles and switches', (tester) async {
    final auth = await open(tester, ['clinician', 'patient']);
    expect(find.text('Clinician'), findsOneWidget);
    expect(tester.getSize(find.byKey(const Key('role-switcher'))).height, greaterThanOrEqualTo(48));
    await tester.tap(find.byKey(const Key('role-switcher')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('role-patient')));
    await tester.pumpAndSettle();
    expect(auth.user!.role, 'patient');
    expect(find.text('Patient'), findsOneWidget);
  });

  testWidgets('428 asks for password + code, wrong one shows error, retry switches', (tester) async {
    final api = FakeApi(MemStorage())
      ..needReauth = true
      ..needsCode = true;
    final auth = await open(tester, ['clinician', 'patient', 'admin'], withApi: api);
    await tester.tap(find.byKey(const Key('role-switcher')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('role-admin')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('reauth-password')), findsOneWidget);
    expect(find.byKey(const Key('reauth-code')), findsOneWidget);
    expect(auth.user!.role, 'clinician');

    await tester.enterText(find.byKey(const Key('reauth-password')), 'bad');
    await tester.enterText(find.byKey(const Key('reauth-code')), '123456');
    await tester.tap(find.byKey(const Key('reauth-confirm')));
    await tester.pumpAndSettle();
    expect(find.text('Wrong password.'), findsOneWidget);
    expect(find.byKey(const Key('reauth-password')), findsOneWidget);

    await tester.enterText(find.byKey(const Key('reauth-password')), 'pw');
    await tester.tap(find.byKey(const Key('reauth-confirm')));
    await tester.pumpAndSettle();
    expect(api.calls.last, ['admin', 'pw', '123456']);
    expect(find.byKey(const Key('reauth-password')), findsNothing);
    expect(auth.user!.role, 'admin');
  });

  testWidgets('428 without needs_code shows no code field', (tester) async {
    final api = FakeApi(MemStorage())..needReauth = true;
    await open(tester, ['clinician', 'patient', 'admin'], withApi: api);
    await tester.tap(find.byKey(const Key('role-switcher')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('role-admin')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('reauth-password')), findsOneWidget);
    expect(find.byKey(const Key('reauth-code')), findsNothing);
  });

  Future<AuthProvider> openChipsWith(WidgetTester tester, FakeApi api, MemStorage storage) async {
    final auth = AuthProvider(api: api, tokenStorage: storage)
      ..user = MBUser.fromJson(userJson('clinician', ['clinician', 'patient', 'admin']));
    await tester.pumpWidget(MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => PatientProvider(api: api)),
        ChangeNotifierProvider(create: (_) => QueueProvider(api: api)),
        ChangeNotifierProvider(create: (_) => RemindersProvider()),
        Provider<ApiClient>.value(value: api),
      ],
      child: MaterialApp(
        locale: const Locale('en'),
        supportedLocales: const [Locale('en')],
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: const Scaffold(body: RoleChips()),
      ),
    ));
    await tester.pump();
    return auth;
  }

  Future<AuthProvider> openChips(WidgetTester tester, List<String> roles, {String role = 'clinician', String? tier, Brightness b = Brightness.light}) async {
    final storage = MemStorage();
    final api = FakeApi(storage);
    final auth = AuthProvider(api: api, tokenStorage: storage)
      ..user = MBUser.fromJson({...userJson(role, roles), 'responder_tier': tier});
    await tester.pumpWidget(MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => PatientProvider(api: api)),
        ChangeNotifierProvider(create: (_) => QueueProvider(api: api)),
        ChangeNotifierProvider(create: (_) => RemindersProvider()),
        Provider<ApiClient>.value(value: api),
      ],
      child: MaterialApp(
        locale: const Locale('en'),
        supportedLocales: const [Locale('en')],
        theme: b == Brightness.dark ? ThemeData.dark() : ThemeData.light(),
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: const Scaffold(body: RoleChips()),
      ),
    ));
    await tester.pump();
    return auth;
  }

  testWidgets('chips hidden with one role', (tester) async {
    await openChips(tester, ['clinician']);
    expect(find.byType(InkWell), findsNothing);
  });

  testWidgets('chips: one per role, active has a check, others tap-to-switch (48dp)', (tester) async {
    final auth = await openChips(tester, ['clinician', 'patient']);
    expect(find.byKey(const Key('role-chip-clinician')), findsOneWidget);
    expect(find.byKey(const Key('role-chip-patient')), findsOneWidget);
    expect(find.byIcon(Icons.check), findsOneWidget); // only the active one
    expect(tester.getSize(find.byKey(const Key('role-chip-patient'))).height, greaterThanOrEqualTo(48));
    await tester.tap(find.byKey(const Key('role-chip-patient')));
    await tester.pumpAndSettle();
    expect(auth.user!.role, 'patient');
  });

  testWidgets('chip switch to admin goes through the password re-auth dialog', (tester) async {
    final storage = MemStorage();
    final api = FakeApi(storage)..needReauth = true;
    await open(tester, ['clinician', 'patient', 'admin'], withApi: api);
    await tester.pumpWidget(const SizedBox());
    final auth = await openChipsWith(tester, api, storage);
    await tester.tap(find.byKey(const Key('role-chip-admin')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('reauth-password')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('reauth-password')), 'pw');
    await tester.tap(find.byKey(const Key('reauth-confirm')));
    await tester.pumpAndSettle();
    expect(auth.user!.role, 'admin');
  });

  testWidgets('paramedic responder chip says so', (tester) async {
    await openChips(tester, ['patient', 'emergency_responder'], role: 'patient', tier: 'paramedic');
    expect(find.textContaining('Paramedic'), findsOneWidget);
  });

  test('every role colour pair is >= 4.5:1 in light and dark, and the roles are all distinct', () {
    double ratio(Color a, Color b) {
      final l1 = a.computeLuminance(), l2 = b.computeLuminance();
      return (l1 > l2 ? l1 + .05 : l2 + .05) / (l1 > l2 ? l2 + .05 : l1 + .05);
    }

    const roles = ['patient', 'clinician', 'emergency_responder', 'pharmacist', 'receptionist', 'records_officer', 'admin'];
    for (final b in Brightness.values) {
      final surface = b == Brightness.dark ? AppColorsDark.surface : AppColors.surface;
      final accents = <Color>{};
      for (final r in roles) {
        for (final tier in [null, 'paramedic']) {
          final s = roleStyleFor(b, r, tier: tier);
          expect(ratio(s.accent, surface), greaterThanOrEqualTo(4.5), reason: '$r $b text on surface');
          expect(ratio(s.onSolid, s.accent), greaterThanOrEqualTo(4.5), reason: '$r $b text on fill');
        }
        accents.add(roleStyleFor(b, r).accent);
      }
      expect(accents.length, roles.length);
    }
    expect(roleStyleFor(Brightness.light, 'emergency_responder', tier: 'paramedic').accent,
        isNot(roleStyleFor(Brightness.light, 'emergency_responder').accent));
  });
}
