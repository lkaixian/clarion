import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/user.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/providers/locale_provider.dart';
import 'package:mobile_flutter/providers/patient_provider.dart';
import 'package:mobile_flutter/providers/queue_provider.dart';
import 'package:mobile_flutter/providers/reminders_provider.dart';
import 'package:mobile_flutter/screens/main_shell.dart';
import 'package:mobile_flutter/screens/scan_hub_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/token_storage.dart';
import 'package:mobile_flutter/widgets/scan_widgets.dart';

Future<void> openShell(WidgetTester tester, {MBUser? user}) async {
  final storage = TokenStorage();
  final api = ApiClient(config: AppConfig(), tokenStorage: storage);
  final auth = AuthProvider(api: api, tokenStorage: storage)..user = user;
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: auth),
        ChangeNotifierProvider(create: (_) => PatientProvider(api: api)),
        ChangeNotifierProvider(create: (_) => QueueProvider(api: api)),
        ChangeNotifierProvider(create: (_) => RemindersProvider()),
        ChangeNotifierProvider(create: (_) => LocaleProvider()),
        Provider<ApiClient>.value(value: api),
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
        home: MainShell(),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  test('parseClarionQr routes by prefix', () {
    expect(parseClarionQr('CLARION-STATION:abc')?.kind, QrKind.checkin);
    expect(parseClarionQr(' CLARION-EMERGENCY:xyz ')?.token, 'xyz');
    expect(parseClarionQr('CLARION-STATION:'), isNull);
    expect(parseClarionQr('https://example.com'), isNull);
    expect(parseClarionQr('abc'), isNull);
  });

  testWidgets('shell has 5 destinations and works without a patient record', (tester) async {
    await openShell(tester);
    for (final l in ['Home', 'Care', 'Scan', 'Queue', 'Profile']) {
      expect(find.text(l), findsOneWidget, reason: l);
    }
    // Emergency stays on Home, and the no-record state is a short notice.
    expect(find.text('Emergency'), findsNothing);
    expect(find.textContaining('No linked patient record'), findsOneWidget);

    await tester.tap(find.byKey(const Key('nav-1')));
    await tester.pump();
    expect(find.textContaining('No linked patient record'), findsWidgets);

    await tester.tap(find.byKey(const Key('nav-4')));
    await tester.pump();
    expect(find.text('Sign out'), findsOneWidget);
    expect(find.text('Write Offline Tag'), findsNothing); // staff-only
  });

  testWidgets('centre Scan opens the hub and QR/NFC segments switch', (tester) async {
    await openShell(tester);
    await tester.tap(find.byKey(const Key('nav-2')));
    await tester.pump();
    expect(find.text('Scan QR'), findsOneWidget);
    expect(find.text('Tap NFC'), findsOneWidget);
    expect(find.byWidgetPredicate((w) => w is SegmentedButton), findsOneWidget);

    await tester.tap(find.text('Tap NFC'));
    await tester.pump(const Duration(milliseconds: 100));
    // Test host is not Android-with-NFC: an unavailable state is shown.
    expect(find.textContaining('NFC'), findsWidgets);
    expect(find.textContaining('clinic check-in code or an emergency card QR'), findsNothing);

    await tester.tap(find.text('Scan QR'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.textContaining('clinic check-in code or an emergency card QR'), findsOneWidget);
  });

  testWidgets('staff accounts get the offline tag tool in Profile', (tester) async {
    await openShell(
      tester,
      user: const MBUser(id: 'u1', email: 'dr@example.com', fullName: 'Dr Test', role: 'clinician'),
    );
    await tester.tap(find.byKey(const Key('nav-4')));
    await tester.pump();
    expect(find.text('Write Offline Tag'), findsOneWidget);
    expect(find.text('Dr Test'), findsOneWidget);
  });

  test('tagIsLegacy: plaintext or empty record is legacy, sealed C1 is not', () {
    expect(tagIsLegacy(null), isTrue);
    expect(tagIsLegacy(''), isTrue);
    expect(tagIsLegacy('BT:O+|AL:Penicillin(severe)'), isTrue);
    expect(tagIsLegacy('C1.1.abcdef'), isFalse);
  });

  testWidgets('LegacyTagBanner shows an icon and plain wording', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        locale: Locale('en'),
        supportedLocales: [Locale('en')],
        localizationsDelegates: [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
        ],
        home: Scaffold(body: LegacyTagBanner()),
      ),
    );
    await tester.pump();
    expect(find.text('Older NFC card'), findsOneWidget);
    expect(find.textContaining('not encrypted'), findsOneWidget);
    expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
  });
}
