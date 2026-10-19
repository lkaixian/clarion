import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/models/bill.dart';
import 'package:mobile_flutter/screens/my_bills_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/api_exception.dart';
import 'package:mobile_flutter/services/token_storage.dart';

PatientBill bill({int due = 5000, int pending = 0, PaymentIntent? intent}) => PatientBill(
      id: 'b1',
      facilityName: 'Hospital A',
      totalCents: 5000,
      paidCents: 5000 - due - pending,
      claimedPendingCents: pending,
      amountDueCents: due + pending,
      patientDueCents: due,
      items: const [BillLine(description: 'Consult', quantity: 1, amountCents: 5000)],
      pendingIntent: intent,
    );

class FakeApi extends ApiClient {
  FakeApi() : super(config: AppConfig(), tokenStorage: TokenStorage());

  List<PatientBill> bills = [bill()];
  int loads = 0;
  final created = <int>[];
  String outcome = 'succeeded';
  ApiException? createError;

  @override
  Future<List<PatientBill>> getMyBills() async {
    loads++;
    return bills;
  }

  @override
  Future<List<PaymentHistoryEntry>> getMyPaymentHistory() async => const [];

  @override
  Future<PaymentIntent> createPaymentIntent(String billId, int amountCents, String idempotencyKey) async {
    if (createError != null) throw createError!;
    expect(idempotencyKey.length, greaterThanOrEqualTo(8));
    created.add(amountCents);
    return PaymentIntent(id: 'i1', amountCents: amountCents, status: 'pending', simulated: true);
  }

  @override
  Future<PaymentIntent> simulatePayment(String intentId, String outcome) async => outcome == 'succeeded'
      ? const PaymentIntent(id: 'i1', amountCents: 5000, status: 'succeeded', simulated: true, paymentId: 'p1')
      : const PaymentIntent(
          id: 'i1', amountCents: 5000, status: 'failed', simulated: true, failureReason: 'Declined by simulated bank');

  @override
  Future<void> cancelPaymentIntent(String intentId) async {}

  final emailed = <String>[];
  ApiException? emailError;

  @override
  Future<String> emailReceipt(String paymentId) async {
    if (emailError != null) throw emailError!;
    emailed.add(paymentId);
    return 'p***@example.com';
  }

  @override
  Future<PaymentReceipt> getReceipt(String paymentId) async => const PaymentReceipt(
        paymentId: 'p1',
        receiptNo: 'AB12CD34',
        facilityName: 'Hospital A',
        amountCents: 5000,
        method: 'online',
        billBalanceAfterCents: 0,
        billTotalCents: 5000,
        items: [BillLine(description: 'Consult', quantity: 1, amountCents: 5000)],
      );
}

Future<FakeApi> open(WidgetTester tester, [FakeApi? api]) async {
  final fake = api ?? FakeApi();
  await tester.pumpWidget(
    Provider<ApiClient>.value(
      value: fake,
      child: const MaterialApp(
        localizationsDelegates: [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        supportedLocales: AppLocalizations.supportedLocales,
        home: MyBillsScreen(),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return fake;
}

void main() {
  group('parseRmToCents', () {
    test('accepts whole and 1-2 decimal amounts without float error', () {
      expect(parseRmToCents('25'), 2500);
      expect(parseRmToCents('25.5'), 2550);
      expect(parseRmToCents(' 0.05 '), 5);
      expect(parseRmToCents('19.99'), 1999);
      expect(parseRmToCents('0.29'), 29);
    });
    test('rejects anything else', () {
      for (final bad in ['', '0', '0.00', '-5', '1.234', 'abc', '1,000', '5.', '.5', 'RM 5']) {
        expect(parseRmToCents(bad), isNull, reason: bad);
      }
    });
    test('formatRm', () {
      expect(formatRm(5000), 'RM 50.00');
      expect(formatRm(5), 'RM 0.05');
    });
  });

  group('MyBillsScreen', () {
    testWidgets('shows what is due and offers payment', (tester) async {
      await open(tester);
      expect(find.text('Hospital A'), findsOneWidget);
      expect(find.text('RM 50.00 to pay'), findsOneWidget);
      expect(find.text('Pay now'), findsOneWidget);
    });

    testWidgets('explains insurer-pending and paid bills, with no pay button', (tester) async {
      final api = FakeApi()..bills = [bill(due: 0, pending: 5000)];
      await open(tester, api);
      expect(find.text('Waiting on your insurer'), findsOneWidget);
      expect(find.text('Pay now'), findsNothing);
    });

    testWidgets('empty state', (tester) async {
      await open(tester, FakeApi()..bills = []);
      expect(find.text('You have no bills.'), findsOneWidget);
    });

    testWidgets('pays through the simulated gateway and shows the receipt', (tester) async {
      final api = await open(tester);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(TextField, '50.00'), findsOneWidget); // prefilled with the amount due
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(api.created, [5000]);
      expect(find.byKey(const Key('sim-notice')), findsOneWidget);
      await tester.tap(find.text('Approve payment'));
      await tester.pumpAndSettle();
      expect(find.text('Receipt AB12CD34'), findsOneWidget);
      expect(api.loads, 2); // list reloaded after paying
    });

    testWidgets('emails the receipt and says where it went', (tester) async {
      final api = await open(tester);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Approve payment'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Email receipt'));
      await tester.pumpAndSettle();
      expect(api.emailed, ['p1']);
      expect(find.text('Receipt sent to p***@example.com.'), findsOneWidget);
    });

    testWidgets('shows why the email failed', (tester) async {
      final api = FakeApi()..emailError = ApiException('This patient has no email address on file', statusCode: 400);
      await open(tester, api);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Approve payment'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Email receipt'));
      await tester.pumpAndSettle();
      expect(find.text('This patient has no email address on file'), findsOneWidget);
    });

    testWidgets('pays only part when the patient lowers the amount', (tester) async {
      final api = await open(tester);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('pay-amount')), '20');
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(api.created, [2000]);
    });

    testWidgets('rejects a bad or too-large amount without calling the server', (tester) async {
      final api = await open(tester);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('pay-amount')), 'abc');
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(find.text('Enter an amount in RM, for example 25.00.'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('pay-amount')), '50.01');
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(find.text('The most you can pay is RM 50.00.'), findsOneWidget);
      expect(api.created, isEmpty);
    });

    testWidgets('a declined payment says nothing was charged and returns to the amount step', (tester) async {
      await open(tester);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Decline payment'));
      await tester.pumpAndSettle();
      expect(find.textContaining('You have not been charged'), findsOneWidget);
      expect(find.byKey(const Key('pay-amount')), findsOneWidget);
      expect(find.text('Receipt AB12CD34'), findsNothing);
    });

    testWidgets('shows a server refusal when starting', (tester) async {
      final api = FakeApi()..createError = ApiException('A payment for this bill is already in progress', statusCode: 409);
      await open(tester, api);
      await tester.tap(find.text('Pay now'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continue'));
      await tester.pumpAndSettle();
      expect(find.text('A payment for this bill is already in progress'), findsOneWidget);
    });
  });
}
