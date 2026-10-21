import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/family.dart';
import 'package:mobile_flutter/models/user.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/providers/patient_provider.dart';
import 'package:mobile_flutter/providers/queue_provider.dart';
import 'package:mobile_flutter/providers/reminders_provider.dart';
import 'package:mobile_flutter/screens/family_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/api_exception.dart';
import 'package:mobile_flutter/services/token_storage.dart';
import 'package:mobile_flutter/widgets/profile_switcher.dart';

class MemStorage extends TokenStorage {
  final m = <String, Object?>{};
  @override
  Future<void> saveToken(String t) async => m['token'] = t;
  @override
  Future<String?> readToken() async => m['token'] as String?;
  @override
  Future<void> saveRefreshToken(String t) async => m['refresh'] = t;
  @override
  Future<String?> readRefreshToken() async => m['refresh'] as String?;
  @override
  Future<void> saveUser(Map<String, dynamic> u) async => m['user'] = u;
  @override
  Future<Map<String, dynamic>?> readUser() async => m['user'] as Map<String, dynamic>?;
  @override
  Future<void> saveActivePatient(String? id) async => m['active'] = id;
  @override
  Future<void> clear() async => m.clear();
  @override
  Future<String?> readActivePatient() async => m['active'] as String?;
}

Map<String, dynamic> userJson({required String pid, required String name, bool acting = false}) => {
      'id': 'u1',
      'email': 'a@x.test',
      'full_name': name,
      'role': 'patient',
      'patient_id': pid,
      'acting_for': acting,
      'home_patient_id': 'own',
    };

class FakeApi extends ApiClient {
  FakeApi(this.storage) : super(config: AppConfig(), tokenStorage: storage);
  final MemStorage storage;
  final switched = <String>[];
  ApiException? addError;
  int adds = 0;

  @override
  Future<Map<String, dynamic>> switchProfile(String patientId) async {
    switched.add(patientId);
    if (switchFails) throw ApiException('Waiting for their approval.', statusCode: 403);
    final own = patientId == 'own';
    return {
      'access_token': 'tok-$patientId',
      'token_type': 'bearer',
      'user': userJson(pid: patientId, name: own ? 'Me' : 'Kid', acting: !own),
    };
  }

  @override
  Future<List<FamilyProfile>> getProfiles() async => const [
        FamilyProfile(patientId: 'own', fullName: 'Me', isSelf: true, age: 40),
        FamilyProfile(patientId: 'kid', fullName: 'Kid', age: 6, relationCode: '1', linkId: 'l1'),
        FamilyProfile(patientId: 'mum', fullName: 'Mum', age: 70, relationCode: '3', pendingApproval: true),
      ];

  final approved = <String>[];
  bool switchFails = false;
  bool refreshOk = true;

  @override
  Future<void> approveGuardian(String linkId) async => approved.add(linkId);

  @override
  Future<bool> refreshSession() async => refreshOk;

  @override
  Future<List<Guardian>> getGuardians() async => const [
        Guardian(linkId: 'g1', fullName: 'Dad', relationCode: '4'),
        Guardian(linkId: 'g2', fullName: 'Aunt', relationCode: '99', approved: false, pending: true),
      ];

  @override
  Future<FamilyProfile> addProfile({
    required String fullName,
    required String dateOfBirth,
    required String relationCode,
  }) async {
    adds++;
    if (addError != null) throw addError!;
    return FamilyProfile(patientId: 'n', fullName: fullName);
  }
}

class Harness {
  Harness(this.api, this.auth, this.queue);
  final FakeApi api;
  final AuthProvider auth;
  final QueueProvider queue;
}

Future<Harness> open(WidgetTester tester, Widget home, {bool acting = false}) async {
  final storage = MemStorage();
  final api = FakeApi(storage);
  final auth = AuthProvider(api: api, tokenStorage: storage)
    ..user = MBUser.fromJson(
        acting ? userJson(pid: 'kid', name: 'Kid', acting: true) : userJson(pid: 'own', name: 'Me'));
  final queue = QueueProvider(api: api)..error = 'stale';
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => PatientProvider(api: api)),
        ChangeNotifierProvider.value(value: queue),
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
        home: home,
      ),
    ),
  );
  await tester.pump();
  return Harness(api, auth, queue);
}

void main() {
  test('User model reads acting_for and home_patient_id', () {
    final u = MBUser.fromJson(userJson(pid: 'kid', name: 'Kid', acting: true));
    expect(u.actingFor, isTrue);
    expect(u.homePatientId, 'own');
    expect(MBUser.fromJson(u.toJson()).actingFor, isTrue);
  });

  test('switchProfile stores token + user + active profile; own profile clears it', () async {
    final storage = MemStorage();
    final auth = AuthProvider(api: FakeApi(storage), tokenStorage: storage);
    expect(await auth.switchProfile('kid'), isNull);
    expect(storage.m['token'], 'tok-kid');
    expect(storage.m['active'], 'kid');
    expect((storage.m['user'] as Map)['patient_id'], 'kid');
    expect(auth.user!.patientId, 'kid');
    expect(auth.user!.actingFor, isTrue);

    expect(await auth.switchProfile('own'), isNull);
    expect(storage.m['token'], 'tok-own');
    expect(storage.m['active'], isNull);
    expect(auth.user!.actingFor, isFalse);
  });

  testWidgets('banner shows while acting; Back switches home and clears cached state', (tester) async {
    final h = await open(tester, const Scaffold(body: ActingBanner()), acting: true);
    expect(find.text('Acting for Kid'), findsOneWidget);
    await tester.tap(find.byKey(const Key('acting-back')));
    await tester.pumpAndSettle();
    expect(h.api.switched, ['own']);
    expect(h.auth.user!.actingFor, isFalse);
    expect(h.queue.error, isNull); // cached state cleared
    expect(find.text('Acting for Kid'), findsNothing);
  });

  testWidgets('no banner when not acting', (tester) async {
    await open(tester, const Scaffold(body: ActingBanner()));
    expect(find.textContaining('Acting for'), findsNothing);
  });

  testWidgets('profile sheet marks own profile as You and switches', (tester) async {
    final h = await open(
      tester,
      Scaffold(appBar: AppBar(actions: const [ProfileSwitcherAction()])),
    );
    await tester.tap(find.byKey(const Key('profile-switcher')));
    await tester.pumpAndSettle();
    expect(find.text('You'), findsOneWidget);
    expect(find.text('Add a family member'), findsOneWidget);
    await tester.tap(find.byKey(const Key('profile-kid')));
    await tester.pumpAndSettle();
    expect(h.api.switched, ['kid']);
    expect(h.auth.user!.fullName, 'Kid');
  });

  testWidgets('My family lists profiles with age and guardians', (tester) async {
    await open(tester, const FamilyScreen());
    await tester.pump();
    expect(find.text('Me'), findsOneWidget);
    expect(find.textContaining('6 yrs'), findsOneWidget);
    expect(find.text('Aunt wants to manage your account'), findsOneWidget);
    expect(find.text('Who can act for my account'), findsOneWidget);
    expect(find.text('Dad'), findsOneWidget);
  });

  testWidgets('pending-approval profile has Switch disabled; guardian approval works', (tester) async {
    final h = await open(tester, const FamilyScreen());
    await tester.pump();
    expect(find.textContaining('Waiting for their approval'), findsOneWidget);
    final sw = tester.widget<TextButton>(find.widgetWithText(TextButton, 'Switch').last);
    expect(sw.onPressed, isNull);
    await tester.tap(find.byKey(const Key('guardian-approve-g2')));
    await tester.pump();
    expect(h.api.approved, ['g2']);
  });

  testWidgets('a refused switch shows the server detail', (tester) async {
    final h = await open(tester, const FamilyScreen());
    await tester.pump();
    h.api.switchFails = true;
    await tester.tap(find.widgetWithText(TextButton, 'Switch').first);
    await tester.pump();
    await tester.pump();
    expect(find.text('Waiting for their approval.'), findsOneWidget);
    expect(h.auth.user!.patientId, 'own');
  });

  test('refresh that drops act_as clears the active id and flags the notice', () async {
    final storage = MemStorage()..m['active'] = 'kid';
    final auth = AuthProvider(api: FakeApi(storage), tokenStorage: storage)
      ..user = MBUser.fromJson(userJson(pid: 'kid', name: 'Kid', acting: true));
    auth.adoptRefreshedUser(userJson(pid: 'own', name: 'Me'), true);
    await Future<void>.delayed(Duration.zero);
    expect(auth.user!.patientId, 'own');
    expect(auth.actingLinkRemoved, isTrue);
    expect(storage.m['active'], isNull);

    auth.actingLinkRemoved = false;
    auth.adoptRefreshedUser(userJson(pid: 'own', name: 'Me'), false);
    expect(auth.actingLinkRemoved, isFalse);
  });

  test('link removed: failed switch-back keeps the session via refresh, logs out only if that fails', () async {
    final storage = MemStorage()..m['active'] = 'kid'..m['token'] = 't';
    final api = FakeApi(storage)..switchFails = true;
    final auth = AuthProvider(api: api, tokenStorage: storage)
      ..user = MBUser.fromJson(userJson(pid: 'kid', name: 'Kid', acting: true))
      ..status = AuthStatus.authenticated;
    await auth.handleActingLinkRemoved();
    expect(auth.status, AuthStatus.authenticated);
    expect(auth.actingLinkRemoved, isTrue);
    expect(storage.m['active'], isNull);

    storage.m['active'] = 'kid';
    api.refreshOk = false;
    auth.user = MBUser.fromJson(userJson(pid: 'kid', name: 'Kid', acting: true));
    // forceLogout runs (storage wiped); its offline-key wipe needs a real plugin, so ignore that tail.
    await auth.handleActingLinkRemoved().catchError((Object _) {});
    expect(storage.m, isEmpty);
  });

  testWidgets('add form validates, then shows the server detail on 409', (tester) async {
    final h = await open(tester, const AddFamilyMemberScreen());
    await tester.tap(find.byKey(const Key('add-submit')));
    await tester.pump();
    expect(find.text('Enter a name.'), findsOneWidget);
    expect(find.text('Choose a date of birth.'), findsOneWidget);
    expect(find.text('Choose a relationship.'), findsOneWidget);
    expect(find.textContaining('ask the clinic desk'), findsOneWidget); // IC hint
    expect(find.byKey(const Key('add-ic')), findsNothing);
    expect(h.api.adds, 0);

    await tester.enterText(find.byKey(const Key('add-name')), 'Baby');
    await tester.tap(find.byKey(const Key('add-dob')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-relation')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Child').last);
    await tester.pumpAndSettle();

    h.api.addError = ApiException('Could not save this profile. Please try again.', statusCode: 409);
    await tester.tap(find.byKey(const Key('add-submit')));
    await tester.pump();
    await tester.pump();
    expect(h.api.adds, 1);
    expect(find.text('Could not save this profile. Please try again.'), findsOneWidget);
  });
}
