import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/booking.dart';
import 'package:mobile_flutter/models/server_appointment.dart';
import 'package:mobile_flutter/providers/patient_provider.dart';
import 'package:mobile_flutter/providers/reminders_provider.dart';
import 'package:mobile_flutter/screens/book_appointment_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/api_exception.dart';
import 'package:mobile_flutter/services/location_service.dart';
import 'package:mobile_flutter/services/token_storage.dart';

const _slot9 = '2026-10-20T09:00:00+08:00';
const _slot930 = '2026-10-20T09:30:00+08:00';

class FakeBookingApi extends ApiClient {
  FakeBookingApi() : super(config: AppConfig(), tokenStorage: TokenStorage());

  final facilityQueries = <Map<String, dynamic>>[];
  final posted = <Map<String, dynamic>>[];
  int availabilityCalls = 0;
  ApiException? postError;
  List<BookingProfile> profiles = const [
    BookingProfile(id: 'p1', fullName: 'Aisyah Ali', relationship: 'child', dateOfBirth: '2018-03-01'),
  ];

  @override
  Future<List<BookingCategory>> getBookingCategories() async => const [
        BookingCategory(code: 'general', label: 'General consultation'),
        BookingCategory(code: 'dental', label: 'Dental'),
      ];

  @override
  Future<List<BookingFacility>> getBookingFacilities({
    required String category,
    String? q,
    double? lat,
    double? lng,
    int limit = 20,
  }) async {
    facilityQueries.add({'category': category, 'q': q, 'lat': lat, 'lng': lng});
    return const [
      BookingFacility(
        facilityName: 'hosp-a',
        displayName: 'Hospital Kota',
        address: '1 Jalan Kota',
        distanceKm: 2.43,
        nextAvailableAt: _slot9,
      ),
    ];
  }

  @override
  Future<FacilityAvailability> getBookingAvailability(String facilityName, String category, {int days = 14}) async {
    availabilityCalls++;
    return const FacilityAvailability(slotMinutes: 30, capacity: 3, days: [
      AvailabilityDay(date: '2026-10-19', openSlots: 0),
      AvailabilityDay(date: '2026-10-20', openSlots: 2),
    ]);
  }

  @override
  Future<List<BookingSlot>> getBookingSlots(String facilityName, String category, String date) async => const [
        BookingSlot(start: _slot9, end: '2026-10-20T09:30:00+08:00', remaining: 2),
        BookingSlot(start: _slot930, end: '2026-10-20T10:00:00+08:00', remaining: 0),
      ];

  @override
  Future<List<BookingProfile>> getBookingProfiles() async => profiles;

  @override
  Future<ServerAppointment> createBookingAppointment(Map<String, dynamic> body) async {
    if (postError != null) throw postError!;
    posted.add(body);
    return ServerAppointment.fromJson({
      'id': 'a1',
      'patient_id': 'pt',
      'facility_name': 'hosp-a',
      'scheduled_at': body['scheduled_at'],
      'booking_category': 'general',
    });
  }
}

Future<void> open(
  WidgetTester tester,
  FakeBookingApi api, {
  Future<bool> Function()? mySejahtera,
  LocateFn? locate,
}) async {
  tester.view.physicalSize = const Size(800, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider(create: (_) => PatientProvider(api: api)),
        ChangeNotifierProvider(create: (_) => RemindersProvider()),
      ],
      child: MaterialApp(
        localizationsDelegates: const [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: AppLocalizations.supportedLocales,
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => BookAppointmentScreen(
                    openMySejahtera: mySejahtera ?? () async => true,
                    locate: locate ?? () async => const LocationFix(1.5, 103.0),
                  ),
                )),
                child: const Text('open'),
              ),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pumpAndSettle();
}

Future<void> pickCategoryAndHospital(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('cat-general')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('facility-hosp-a')));
  await tester.pumpAndSettle();
}

void main() {
  group('pure helpers', () {
    test('wallClock keeps the hospital clock regardless of offset', () {
      final t = wallClock('2026-10-20T09:30:00+08:00');
      expect([t.hour, t.minute, t.day], [9, 30, 20]);
      final z = wallClock('2026-10-20T01:30:00Z');
      expect(z.hour, 1);
    });

    test('buildBookingBody omits a blank reason and passes the slot start untouched', () {
      expect(
        buildBookingBody(facilityName: 'h', category: 'dental', scheduledAt: _slot9, profileId: 'p1', reason: '  '),
        {'facility_name': 'h', 'category': 'dental', 'scheduled_at': _slot9, 'profile_id': 'p1'},
      );
      expect(
        buildBookingBody(facilityName: 'h', category: 'dental', scheduledAt: _slot9, reason: ' cough ')['reason'],
        'cough',
      );
    });

    test('distanceKmLabel and firstOpenDay', () {
      expect(distanceKmLabel(2.43), '2.4');
      expect(distanceKmLabel(12.04), '12');
      expect(distanceKmLabel(null), isNull);
      expect(
        firstOpenDay(const [AvailabilityDay(date: 'a', openSlots: 0), AvailabilityDay(date: 'b', openSlots: 1)])?.date,
        'b',
      );
      expect(firstOpenDay(const [AvailabilityDay(date: 'a', openSlots: 0)]), isNull);
    });

    test('ServerAppointment parses booking fields and tolerates their absence', () {
      final a = ServerAppointment.fromJson({
        'id': '1',
        'patient_id': 'p',
        'facility_name': 'f',
        'scheduled_at': _slot9,
        'self_booked': true,
        'booking_category': 'dental',
        'attendee_name': 'Aisyah',
        'attendee_relationship': 'child',
      });
      expect([a.selfBooked, a.bookingCategory, a.attendeeName, a.attendeeRelationship],
          [true, 'dental', 'Aisyah', 'child']);
      final b = ServerAppointment.fromJson({'id': '2', 'scheduled_at': _slot9});
      expect([b.selfBooked, b.bookingCategory, b.attendeeName], [false, null, null]);
    });
  });

  group('BookAppointmentScreen', () {
    testWidgets('category, typed search, hospital, slot, saved person, confirm posts the right body', (tester) async {
      final api = FakeBookingApi();
      await open(tester, api);

      // step 1: category grid
      expect(find.text('General consultation'), findsOneWidget);
      expect(find.text('Dental'), findsOneWidget);
      await tester.tap(find.byKey(const Key('cat-general')));
      await tester.pumpAndSettle();

      // step 2: typed search
      await tester.enterText(find.byKey(const Key('facility-search')), 'kota');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();
      expect(api.facilityQueries.last, {'category': 'general', 'q': 'kota', 'lat': null, 'lng': null});
      expect(find.text('Hospital Kota'), findsOneWidget);
      expect(find.text('1 Jalan Kota'), findsOneWidget);
      expect(find.textContaining('2.4 km away'), findsOneWidget);
      expect(find.textContaining('Next available'), findsOneWidget);
      await tester.tap(find.byKey(const Key('facility-hosp-a')));
      await tester.pumpAndSettle();

      // step 3: date strip + slots; the 19th has no open slots and is disabled
      expect(find.byKey(const Key('date-strip')), findsOneWidget);
      final fullDay = tester.widget<InkWell>(find.byKey(const Key('day-2026-10-19')));
      expect(fullDay.onTap, isNull);
      expect(find.text('9:00 AM  |  2 left'), findsOneWidget);
      final fullSlot = tester.widget<ChoiceChip>(find.byKey(const Key(('slot-$_slot930'))));
      expect(fullSlot.onSelected, isNull);
      await tester.tap(find.byKey(const Key('slot-$_slot9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('timetable-continue')));
      await tester.pumpAndSettle();

      // step 4: saved person
      expect(find.text('Aisyah Ali'), findsOneWidget);
      await tester.tap(find.byKey(const Key('person-p1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('person-continue')));
      await tester.pumpAndSettle();

      // step 5: confirm
      expect(find.text('Hospital Kota'), findsOneWidget);
      await tester.tap(find.byKey(const Key('confirm-booking')));
      await tester.pumpAndSettle();

      expect(api.posted, [
        {
          'facility_name': 'hosp-a',
          'category': 'general',
          'scheduled_at': _slot9,
          'profile_id': 'p1',
        },
      ]);
      expect(find.byKey(const Key('view-appointments')), findsOneWidget);
    });

    testWidgets('booking for myself sends a null profile and the typed reason', (tester) async {
      final api = FakeBookingApi();
      await open(tester, api);
      await pickCategoryAndHospital(tester);
      await tester.tap(find.byKey(const Key('slot-$_slot9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('timetable-continue')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('person-continue'))); // "Myself" is preselected
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('reason')), 'cough');
      await tester.tap(find.byKey(const Key('confirm-booking')));
      await tester.pumpAndSettle();
      expect(api.posted.single['profile_id'], isNull);
      expect(api.posted.single['reason'], 'cough');
    });

    testWidgets('409 goes back to the slots and refreshes them', (tester) async {
      final api = FakeBookingApi()..postError = ApiException('taken', statusCode: 409);
      await open(tester, api);
      await pickCategoryAndHospital(tester);
      await tester.tap(find.byKey(const Key('slot-$_slot9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('timetable-continue')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('person-continue')));
      await tester.pumpAndSettle();
      expect(api.availabilityCalls, 1);
      await tester.tap(find.byKey(const Key('confirm-booking')));
      await tester.pumpAndSettle();

      expect(find.text('That time was just taken. Please pick another time.'), findsOneWidget);
      expect(find.byKey(const Key('date-strip')), findsOneWidget);
      expect(api.availabilityCalls, 2);
      // nothing selected any more, so Continue is disabled
      expect(tester.widget<FilledButton>(find.byKey(const Key('timetable-continue'))).onPressed, isNull);
    });

    testWidgets('403 explains the missing patient record and offers a retry', (tester) async {
      final api = FakeBookingApi()..postError = ApiException('no patient', statusCode: 403);
      await open(tester, api);
      await pickCategoryAndHospital(tester);
      await tester.tap(find.byKey(const Key('slot-$_slot9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('timetable-continue')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('person-continue')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-booking')));
      await tester.pumpAndSettle();
      expect(find.textContaining('not linked to a patient record'), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });

    testWidgets('network error shows a retry that succeeds', (tester) async {
      final api = FakeBookingApi()..postError = ApiException('x', isUnreachable: true);
      await open(tester, api);
      await pickCategoryAndHospital(tester);
      await tester.tap(find.byKey(const Key('slot-$_slot9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('timetable-continue')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('person-continue')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-booking')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Could not reach the server'), findsOneWidget);
      api.postError = null;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();
      expect(api.posted, hasLength(1));
    });

    testWidgets('denied location shows a message and typed search still works', (tester) async {
      final api = FakeBookingApi();
      await open(tester, api, locate: () async => throw const LocationException(LocationFailure.denied));
      await tester.tap(find.byKey(const Key('cat-general')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('use-location')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('location-message')), findsOneWidget);
      expect(find.textContaining('Location permission was denied'), findsOneWidget);
      // the list was still searched, without coordinates
      expect(api.facilityQueries.last['lat'], isNull);

      await tester.enterText(find.byKey(const Key('facility-search')), 'johor');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();
      expect(api.facilityQueries.last['q'], 'johor');
      expect(find.text('Hospital Kota'), findsOneWidget);
    });

    testWidgets('a granted location is sent with the search', (tester) async {
      final api = FakeBookingApi();
      await open(tester, api);
      await tester.tap(find.byKey(const Key('cat-general')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('use-location')));
      await tester.pumpAndSettle();
      expect(api.facilityQueries.last['lat'], 1.5);
      expect(api.facilityQueries.last['lng'], 103.0);
    });

    testWidgets('MySejahtera banner button calls the launcher; Book here dismisses it', (tester) async {
      var launched = 0;
      await open(tester, FakeBookingApi(), mySejahtera: () async {
        launched++;
        return true;
      });
      expect(find.text('Prefer MySejahtera?'), findsOneWidget);
      await tester.tap(find.text('Open MySejahtera'));
      await tester.pumpAndSettle();
      expect(launched, 1);
      await tester.tap(find.text('Book here'));
      await tester.pumpAndSettle();
      expect(find.text('Prefer MySejahtera?'), findsNothing);
    });

    testWidgets('Back walks the steps instead of leaving the flow', (tester) async {
      await open(tester, FakeBookingApi());
      await pickCategoryAndHospital(tester);
      expect(find.byKey(const Key('date-strip')), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('facility-hosp-a')), findsOneWidget); // location step
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('cat-general')), findsOneWidget); // category step
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('open'), findsOneWidget); // left the flow
    });

    testWidgets('no saved people shows the empty state; a person can be added', (tester) async {
      final api = FakeBookingApi()..profiles = const [];
      await open(tester, api);
      await pickCategoryAndHospital(tester);
      await tester.tap(find.byKey(const Key('slot-$_slot9')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('timetable-continue')));
      await tester.pumpAndSettle();
      expect(find.textContaining('You have not saved anyone yet'), findsOneWidget);
      await tester.tap(find.byKey(const Key('add-person')));
      await tester.pumpAndSettle();
      // saving with nothing filled in is refused locally
      await tester.tap(find.byKey(const Key('profile-save')));
      await tester.pumpAndSettle();
      expect(find.text('Enter a full name.'), findsOneWidget);
      expect(find.text('Pick a date of birth.'), findsOneWidget);
    });
  });
}
