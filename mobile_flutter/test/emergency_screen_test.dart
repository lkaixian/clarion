import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/nfc_card.dart';
import 'package:mobile_flutter/models/patient.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/providers/patient_provider.dart';
import 'package:mobile_flutter/screens/emergency_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class FakeApi extends ApiClient {
  FakeApi() : super(config: AppConfig(), tokenStorage: TokenStorage());

  @override
  Future<List<NfcCardEvent>> getNfcCardHistory(String patientId, String cardId) async => const [
        NfcCardEvent(at: '2026-10-01T08:00:00Z', event: 'registered', byRole: 'admin', facility: 'Clinic A'),
      ];
}

NfcCard card(String id, String status, String created, {bool outdated = false}) => NfcCard.fromJson({
      'id': id,
      'nfc_uid_last4': id.padLeft(4, '0'),
      'scope': ['allergies', 'blood_type'],
      'grant_valid_until': '2029-10-01T00:00:00Z',
      'revoked': status == 'revoked',
      'created_at': created,
      'tag_type': outdated ? 'ntag21x' : 'ntag424',
      'outdated': outdated,
      'status': status,
      'valid_days_left': status == 'active' ? 900 : null,
    });

Patient patient() => Patient(
      id: 'p1',
      fullName: 'Aisyah Rahman',
      dateOfBirth: '1990-01-01',
      bloodType: 'O+',
      seniorCitizenMode: false,
      conditions: const [
        Condition(id: 'c1', name: 'Asthma', status: 'active', isChronic: true, criticalForEmergency: true),
        Condition(id: 'c2', name: 'Old fracture', status: 'resolved', isChronic: false, criticalForEmergency: true),
      ],
      medications: const [
        Medication(id: 'm1', drugName: 'Warfarin', dosage: '5mg', active: true, criticalForEmergency: true),
        Medication(id: 'm2', drugName: 'Stopped drug', active: false, criticalForEmergency: true),
        Medication(id: 'm3', drugName: 'Vitamin C', active: true, criticalForEmergency: false),
      ],
      allergies: const [Allergy(id: 'a1', substance: 'Penicillin', severity: 'severe', criticalForEmergency: true)],
      encounters: const [],
    );

void main() {
  test('preview mirrors the emergency endpoint filtering', () {
    final p = EmergencyPreview.fromPatient(patient());
    expect(p.bloodType, 'O+');
    expect(p.allergies, ['Penicillin']);
    expect(p.medications, ['Warfarin - 5mg']);
    expect(p.conditions, ['Asthma']);
    expect(p.omitted, 1);
  });

  test('sortNfcCards puts active first, then newest', () {
    final sorted = sortNfcCards([
      card('1', 'revoked', '2026-09-01T00:00:00Z'),
      card('2', 'active', '2026-01-01T00:00:00Z'),
      card('3', 'active', '2026-05-01T00:00:00Z'),
    ]);
    expect(sorted.map((c) => c.id), ['3', '2', '1']);
  });

  testWidgets('QR tab has no field checkboxes; Card tab shows status, banner and history', (tester) async {
    tester.view.physicalSize = const Size(400, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final api = FakeApi();
    final storage = TokenStorage();
    final state = PatientProvider(api: api)
      ..patient = patient()
      ..nfcCards = [card('7', 'active', '2026-05-01T00:00:00Z', outdated: true)];
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider(create: (_) => AuthProvider(api: api, tokenStorage: storage)),
          ChangeNotifierProvider.value(value: state),
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
          home: EmergencyScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.byType(Checkbox), findsNothing);
    expect(find.text('What will be shared'), findsOneWidget);
    await tester.tap(find.byTooltip('Preview what a responder sees'));
    await tester.pumpAndSettle();
    expect(find.text('Warfarin - 5mg'), findsOneWidget);
    expect(find.text('Stopped drug'), findsNothing);
    expect(find.text('Old fracture'), findsNothing);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Card'));
    await tester.pumpAndSettle();
    expect(find.text('Older NFC chip'), findsOneWidget);
    expect(find.text('Share card image'), findsOneWidget);
    expect(find.text('Active'), findsWidgets);
    expect(find.text('Registered'), findsWidgets); // info row + history event
  });
}
