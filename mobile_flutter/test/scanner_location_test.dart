import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/screens/emergency_scanner_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/api_exception.dart';
import 'package:mobile_flutter/services/scan_location.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class MemStorage extends TokenStorage {
  String? token;
  @override
  Future<String?> readToken() async => token;
}

class FakeApi extends ApiClient {
  FakeApi() : super(config: AppConfig(), tokenStorage: MemStorage());
  final scanBodies = <Map<String, dynamic>?>[];
  final shares = <List<Object?>>[];
  bool shareFails = false;
  bool rejectLocation = false;

  @override
  Future<Map<String, dynamic>> scanEmergencyCard({
    required String cardReference,
    String? responderName,
    String? responderOrg,
    Map<String, dynamic>? location,
  }) async {
    scanBodies.add(location);
    if (location != null && rejectLocation) throw ApiException('bad', statusCode: 422);
    return {
      'full_name': 'Aisyah Rahman',
      'age': 34,
      'blood_type': 'O+',
      'tier': 'responder',
      'allergies': [
        {'substance': 'Penicillin', 'severity': 'severe'}
      ],
      'medications': [],
      'conditions': [],
      'location_token': 'opaque-token',
    };
  }

  @override
  Future<void> shareScanLocation(String token, Map<String, dynamic> location) async {
    shares.add([token, location]);
    if (shareFails) throw ApiException('expired', statusCode: 400);
  }
}

class FakeSource implements ScanLocationSource {
  FakeSource({this.perm = LocPermission.granted, this.last, this.fixOnCall});
  LocPermission perm;
  ScanFix? last;
  int? fixOnCall; // current() returns a fix from this call number on
  int currentCalls = 0;
  int requests = 0;

  @override
  Future<LocPermission> checkPermission() async => perm;
  @override
  Future<LocPermission> requestPermission() async {
    requests++;
    return perm;
  }

  @override
  Future<ScanFix?> lastKnown() async => last;
  @override
  Future<ScanFix?> current() async {
    currentCalls++;
    if (fixOnCall != null && currentCalls >= fixOnCall!) return ScanFix(3.139, 101.687, DateTime.now(), accuracyM: 15);
    return null;
  }
}

ScanFix freshFix({double? acc = 12}) => ScanFix(3.139, 101.687, DateTime.now(), accuracyM: acc);

Future<void> open(WidgetTester tester, FakeApi api, FakeSource src) async {
  tester.view.physicalSize = const Size(500, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final auth = AuthProvider(api: api, tokenStorage: MemStorage());
  await tester.pumpWidget(MultiProvider(
    providers: [
      ChangeNotifierProvider.value(value: auth),
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
      home: EmergencyScannerScreen(initialCardReference: 'REF', locationSource: src),
    ),
  ));
}

Future<void> settle(WidgetTester tester, {int seconds = 1}) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 700));
  for (var i = 0; i < seconds * 2; i++) {
    await tester.pump(const Duration(milliseconds: 500));
  }
}

Future<void> end(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox());
  await tester.pump(const Duration(seconds: 3));
}

void main() {
  void prefs({bool share = true, bool asked = true}) => SharedPreferences.setMockInitialValues({
        'mb_responder_asked': true,
        'mb_scan_loc_asked': asked,
        if (share) 'mb_scan_loc_share': true,
      });

  testWidgets('fresh fix present: scan body carries location, status says shared with accuracy', (tester) async {
    prefs();
    final api = FakeApi();
    await open(tester, api, FakeSource(last: freshFix()));
    await settle(tester);
    expect(api.scanBodies.single, containsPair('lat', 3.139));
    expect(api.scanBodies.single!['accuracy_m'], 12);
    expect(api.shares, isEmpty);
    expect(find.textContaining('about 12 m'), findsOneWidget);
    await end(tester);
  });

  testWidgets('poor accuracy is called approximate', (tester) async {
    prefs();
    final api = FakeApi();
    await open(tester, api, FakeSource(last: freshFix(acc: 800)));
    await settle(tester);
    expect(find.textContaining('(approximate)'), findsOneWidget);
    await end(tester);
  });

  testWidgets('no fix at scan time: one follow-up share with the scan token', (tester) async {
    prefs();
    final api = FakeApi();
    await open(tester, api, FakeSource(fixOnCall: 3));
    await settle(tester);
    expect(api.scanBodies.single, isNull);
    expect(find.text('Sharing location...'), findsOneWidget);
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(seconds: 2));
    }
    expect(api.shares.length, 1);
    expect(api.shares.single[0], 'opaque-token');
    expect(find.textContaining('Location shared with the patient'), findsOneWidget);
    await end(tester);
  });

  testWidgets('second-use 400 is handled quietly: no retry, status says not shared', (tester) async {
    prefs();
    final api = FakeApi()..shareFails = true;
    await open(tester, api, FakeSource(fixOnCall: 3));
    await settle(tester);
    for (var i = 0; i < 12; i++) {
      await tester.pump(const Duration(seconds: 2));
    }
    expect(api.shares.length, 1);
    expect(find.textContaining('Location not shared'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await end(tester);
  });

  testWidgets('permission denied: no location, scan still works', (tester) async {
    prefs();
    final api = FakeApi();
    await open(tester, api, FakeSource(perm: LocPermission.denied, last: freshFix()));
    await settle(tester);
    expect(api.scanBodies.single, isNull);
    expect(api.shares, isEmpty);
    expect(find.text('Aisyah Rahman'), findsOneWidget);
    expect(find.textContaining('permission not allowed'), findsOneWidget);
    await end(tester);
  });

  testWidgets('toggle OFF (default until the sheet is accepted): nothing is sent', (tester) async {
    prefs(share: false);
    final api = FakeApi();
    await open(tester, api, FakeSource(last: freshFix(), fixOnCall: 1));
    await settle(tester);
    for (var i = 0; i < 4; i++) {
      await tester.pump(const Duration(seconds: 2));
    }
    expect(api.scanBodies.single, isNull);
    expect(api.shares, isEmpty);
    expect(find.textContaining('sharing is turned off'), findsOneWidget);
    await end(tester);
  });

  testWidgets('a position the server refuses (422) never costs the scan', (tester) async {
    prefs();
    final api = FakeApi()..rejectLocation = true;
    await open(tester, api, FakeSource(last: freshFix()));
    await settle(tester);
    expect(api.scanBodies.length, 2);
    expect(api.scanBodies.last, isNull);
    expect(find.text('Aisyah Rahman'), findsOneWidget);
    await end(tester);
  });

  test('ScanFix rejects (0,0), out of range and non-finite', () {
    final now = DateTime.now();
    expect(ScanFix(0, 0, now).isValid, isFalse);
    expect(ScanFix(91, 10, now).isValid, isFalse);
    expect(ScanFix(double.nan, 10, now).isValid, isFalse);
    expect(ScanFix(3, 101, now).isValid, isTrue);
    expect(ScanFix(3, 101, now, accuracyM: double.infinity).toJson().containsKey('accuracy_m'), isFalse);
  });

  testWidgets('first-time sheet discloses and Allow switches sharing on; chip keeps default off until then', (tester) async {
    SharedPreferences.setMockInitialValues({'mb_responder_asked': true});
    final api = FakeApi();
    final src = FakeSource(perm: LocPermission.denied);
    final auth = AuthProvider(api: api, tokenStorage: MemStorage());
    await tester.pumpWidget(MultiProvider(
      providers: [ChangeNotifierProvider.value(value: auth), Provider<ApiClient>.value(value: api)],
      child: MaterialApp(
        locale: const Locale('en'),
        supportedLocales: const [Locale('en')],
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: EmergencyScannerScreen(locationSource: src),
      ),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.textContaining('90 days'), findsOneWidget);
    expect(find.textContaining('map link'), findsOneWidget);
    expect(find.textContaining('care team'), findsOneWidget);
    await tester.tap(find.byKey(const Key('scan-loc-allow')));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump(const Duration(milliseconds: 500));
    expect(src.requests, 1);
    final saved = await SharedPreferences.getInstance();
    expect(saved.getBool('mb_scan_loc_share'), isTrue);
    await tester.pumpWidget(const SizedBox());
    await tester.pump(const Duration(seconds: 3));
  });

  test('signed-in follow-up keeps the session: bearer is sent with POST /emergency/location', () async {
    final storage = MemStorage()..token = 'sess-123';
    final api = ApiClient(config: AppConfig(), tokenStorage: storage);
    final seen = <RequestOptions>[];
    api.dioForTest.httpClientAdapter = _Adapter((o) {
      seen.add(o);
      return ResponseBody.fromString(jsonEncode({'status': 'ok'}), 200,
          headers: {Headers.contentTypeHeader: [Headers.jsonContentType]});
    });
    await api.shareScanLocation('tok', {'lat': 3.1, 'lng': 101.6});
    expect(seen.single.path, '/emergency/location');
    expect(seen.single.headers['Authorization'], 'Bearer sess-123');
    expect(seen.single.data, {'token': 'tok', 'location': {'lat': 3.1, 'lng': 101.6}});
  });
}

class _Adapter implements HttpClientAdapter {
  _Adapter(this.respond);
  final ResponseBody Function(RequestOptions) respond;
  @override
  void close({bool force = false}) {}
  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async =>
      respond(options);
}
