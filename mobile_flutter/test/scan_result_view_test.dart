import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations_en.dart';
import 'package:mobile_flutter/models/emergency_scan_result.dart';
import 'package:mobile_flutter/widgets/scan_result_view.dart';

Widget host(Widget child, {double scale = 1, ThemeMode mode = ThemeMode.light}) => MaterialApp(
      locale: const Locale('en'),
      supportedLocales: const [Locale('en')],
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      themeMode: mode,
      theme: ThemeData.light(),
      darkTheme: ThemeData.dark(),
      builder: (context, c) => MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
        child: c!,
      ),
      home: Scaffold(body: child),
    );

EmergencyScanResult result(String tier, {bool contact = true}) => EmergencyScanResult.fromJson({
      'full_name': tier == 'public' ? '' : 'Aisyah Rahman',
      'age': tier == 'public' ? null : 34,
      'blood_type': tier == 'public' ? null : 'O+',
      'tier': tier,
      'allergies': [
        {'substance': 'Pollen', 'severity': 'mild'},
        {'substance': 'Penicillin', 'severity': 'severe', 'reaction': 'anaphylaxis'},
      ],
      'conditions': ['Asthma'],
      'medications': tier == 'public' || tier == 'responder'
          ? []
          : [
              {'drug_name': 'Warfarin', 'dosage': '5mg', 'frequency': 'daily'}
            ],
      'omitted_non_critical': {'conditions': 2},
      if (contact && tier != 'public') ...{
        'emergency_contact_name': 'Siti',
        'emergency_contact_phone': '+60123456789',
        'emergency_contact_relationship': 'Sister',
      },
    });

void main() {
  void tall(WidgetTester tester) {
    tester.view.physicalSize = const Size(400, 4000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
  }

  testWidgets('public tier: basic info only, no name/blood/meds/contact, hint shown', (tester) async {
    tall(tester);
    await tester.pumpWidget(host(ScanResultView(result: result('public'), onScanAnother: () {})));
    expect(find.text('Basic information only'), findsOneWidget);
    expect(find.textContaining('Sign in as a responder'), findsOneWidget);
    expect(find.text('Name not shown at this access level'), findsOneWidget);
    expect(find.text('Current medications'), findsNothing);
    expect(find.byKey(const Key('call-contact')), findsNothing);
    expect(find.text('Penicillin'), findsOneWidget);
  });

  testWidgets('paramedic: tier badge, severe allergy first with words, meds with dose, big call button', (tester) async {
    tall(tester);
    await tester.pumpWidget(host(ScanResultView(result: result('paramedic'), onScanAnother: () {})));
    expect(find.text('Paramedic'), findsOneWidget);
    expect(find.text('Aisyah Rahman'), findsOneWidget);
    expect(find.text('O+'), findsOneWidget);
    expect(find.textContaining('Severe'), findsOneWidget);
    expect(find.textContaining('Warfarin · 5mg, daily'), findsOneWidget);
    // severe allergy is listed above the mild one
    expect(tester.getTopLeft(find.text('Penicillin')).dy, lessThan(tester.getTopLeft(find.text('Pollen')).dy));
    final call = find.byKey(const Key('call-contact'));
    expect(tester.getSize(call).height, greaterThanOrEqualTo(48));
    expect(tester.getSize(call).width, greaterThan(300));
    // omitted note is readable (>= 13sp, not italic)
    final note = tester.widget<Text>(find.textContaining('2 more conditions'));
    expect(note.style!.fontSize, greaterThanOrEqualTo(13));
    expect(note.style!.fontStyle, isNot(FontStyle.italic));
  });

  testWidgets('responder tier hides medications (not included) instead of saying none', (tester) async {
    tall(tester);
    await tester.pumpWidget(host(ScanResultView(result: result('responder'), onScanAnother: () {})));
    expect(find.text('Responder'), findsOneWidget);
    expect(find.text('Current medications'), findsNothing);
  });

  testWidgets('empty sections say None recorded as critical', (tester) async {
    tall(tester);
    final r = EmergencyScanResult.fromJson({
      'full_name': 'A', 'tier': 'clinical', 'allergies': [], 'conditions': [], 'medications': [],
    });
    await tester.pumpWidget(host(ScanResultView(result: r, onScanAnother: () {})));
    expect(find.text('None recorded as critical'), findsNWidgets(3));
  });

  for (final mode in [ThemeMode.light, ThemeMode.dark]) {
    testWidgets('200% text scale does not overflow ($mode)', (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host(
        ScanResultView(
          result: result('paramedic'),
          offline: true,
          legacyTag: false,
          locStatus: ScanLocStatus.shared,
          onScanAnother: () {},
        ),
        scale: 2,
        mode: mode,
      ));
      await tester.scrollUntilVisible(find.byKey(const Key('call-contact')), 300, scrollable: find.byType(Scrollable));
      await tester.scrollUntilVisible(find.text('Scan another card'), 300, scrollable: find.byType(Scrollable));
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets('semantics: sections are headers in priority order', (tester) async {
    tall(tester);
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(host(ScanResultView(result: result('paramedic'), onScanAnother: () {})));
    final headers = find.byWidgetPredicate((w) => w is Semantics && w.properties.header == true);
    expect(headers, findsNWidgets(4)); // allergies, conditions, medications, contact
    expect(tester.getTopLeft(find.text(AppLocalizationsEn().allergiesTitle)).dy, lessThan(tester.getTopLeft(find.text(AppLocalizationsEn().activeConditionsTitle)).dy));
    expect(find.bySemanticsLabel(RegExp('Access level: Paramedic')), findsOneWidget);
    handle.dispose();
  });
}
