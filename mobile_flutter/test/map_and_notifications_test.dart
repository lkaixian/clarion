import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/app_notification.dart';
import 'package:mobile_flutter/models/scan_location_entry.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/screens/card_scan_locations_screen.dart';
import 'package:mobile_flutter/screens/notifications_screen.dart';
import 'package:mobile_flutter/models/user.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/map_launcher.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class FakeApi extends ApiClient {
  FakeApi() : super(config: AppConfig(), tokenStorage: TokenStorage());
  @override
  Future<List<AppNotification>> getNotifications({int limit = 50}) async => [
        const AppNotification(
          id: 'n1',
          title: 'Card scanned',
          body: 'Position reported by the scanner\'s phone',
          link: 'https://maps.google.com/?q=3.139,101.687',
        ),
        const AppNotification(id: 'n2', title: 'Appointment', link: '/appointments'),
      ];

  @override
  Future<List<ScanLocationEntry>> getScanLocations(String patientId) async => [
        ScanLocationEntry(
          lat: 3.139,
          lng: 101.687,
          accuracyM: 15,
          tier: 'paramedic',
          actorFacility: 'Klinik A',
          createdAt: DateTime(2026, 10, 22, 9, 30),
        ),
        ScanLocationEntry(lat: 3.2, lng: 101.7, createdAt: DateTime(2026, 10, 22, 8, 0)),
      ];
}

Future<void> pump(WidgetTester tester, Widget home, FakeApi api) async {
  final auth = AuthProvider(api: api, tokenStorage: TokenStorage())
    ..user = MBUser.fromJson({
      'id': 'u', 'email': 'a@b.c', 'full_name': 'N', 'role': 'patient', 'patient_id': 'p1', 'acting_for': false,
    });
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
      home: home,
    ),
  ));
  await tester.pump();
  await tester.pump();
}

void main() {
  group('openMap platform selection', () {
    Future<List<String>> run(TargetPlatform p, {bool geoWorks = true}) async {
      final tried = <String>[];
      await openMap(3.139, 101.687, platform: p, open: (u) async {
        tried.add(u.toString());
        return u.scheme == 'geo' ? geoWorks : true;
      });
      return tried;
    }

    test('android: geo: intent first', () async {
      expect(await run(TargetPlatform.android), ['geo:3.139000,101.687000?q=3.139000,101.687000(CLARION)']);
    });
    test('android: falls back to the Google Maps web link', () async {
      final t = await run(TargetPlatform.android, geoWorks: false);
      expect(t.last, 'https://maps.google.com/?q=3.139000,101.687000');
      expect(t.length, 2);
    });
    test('iOS: Apple Maps', () async {
      expect(await run(TargetPlatform.iOS), ['https://maps.apple.com/?q=3.139000,101.687000']);
    });
    test('other platforms: web link', () async {
      expect(await run(TargetPlatform.windows), ['https://maps.google.com/?q=3.139000,101.687000']);
    });
    test('a launcher that throws gives false, never a crash', () async {
      expect(await openMap(1, 2, platform: TargetPlatform.android, open: (_) async => throw Exception('x')), isFalse);
    });
  });

  testWidgets('https notification link: pin + Open in Maps, opens externally; other links get no button', (tester) async {
    final opened = <Uri>[];
    await pump(tester, NotificationsScreen(open: (u) async { opened.add(u); return true; }), FakeApi());
    expect(find.text('Open in Maps'), findsOneWidget);
    expect(find.byIcon(Icons.place_outlined), findsOneWidget);
    await tester.tap(find.byKey(const Key('open-maps-n1')));
    await tester.pump();
    expect(opened.single.toString(), 'https://maps.google.com/?q=3.139,101.687');
  });

  testWidgets('a failing launch shows a snackbar, not a crash', (tester) async {
    await pump(tester, NotificationsScreen(open: (u) async => false), FakeApi());
    await tester.tap(find.byKey(const Key('open-maps-n1')));
    await tester.pump();
    expect(find.text('Could not open a maps app.'), findsOneWidget);
  });

  test('only https links count as external', () {
    expect(const AppNotification(id: '1', title: 't', link: 'http://x').isExternalLink, isFalse);
    expect(const AppNotification(id: '1', title: 't', link: 'javascript:alert(1)').isExternalLink, isFalse);
    expect(const AppNotification(id: '1', title: 't', link: 'https://x').isExternalLink, isTrue);
  });

  testWidgets('Where my card was scanned: rows show who/accuracy and tap opens the map', (tester) async {
    final opened = <Uri>[];
    await pump(tester, CardScanLocationsScreen(open: (u) async { opened.add(u); return true; }), FakeApi());
    expect(find.text('Where my card was scanned'), findsOneWidget);
    expect(find.textContaining('scanner\'s phone'), findsOneWidget);
    expect(find.textContaining('Paramedic · Klinik A'), findsOneWidget);
    expect(find.textContaining('about 15 m'), findsOneWidget);
    expect(find.textContaining('Someone not signed in'), findsOneWidget);
    await tester.tap(find.byKey(const Key('scan-location-0')));
    await tester.pump();
    expect(opened.length, greaterThanOrEqualTo(1));
  });
}
