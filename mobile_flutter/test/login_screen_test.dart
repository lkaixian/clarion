import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/screens/login_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class _Api extends ApiClient {
  _Api() : super(config: AppConfig(), tokenStorage: TokenStorage());
  int logins = 0;

  @override
  Future<Map<String, dynamic>> login(String email, String password) async {
    logins++;
    return {
      'mfa_required': true,
      'mfa_token': 't',
      'email_available': true,
      'email_hint': 'p***@x.test',
    };
  }

  @override
  Future<Map<String, dynamic>> sendMfaEmailCode(String t) async => {'status': 'ok', 'email_hint': 'p***@x.test'};
}

Future<_Api> _open(WidgetTester tester) async {
  final api = _Api();
  final auth = AuthProvider(api: api, tokenStorage: TokenStorage());
  await tester.pumpWidget(
    ChangeNotifierProvider.value(
      value: auth,
      child: const MaterialApp(
        locale: Locale('en'),
        supportedLocales: [Locale('en')],
        localizationsDelegates: [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: LoginScreen(),
      ),
    ),
  );
  await tester.pump();
  return api;
}

void main() {
  testWidgets('starts empty, with no demo account text', (tester) async {
    await _open(tester);
    final fields = tester.widgetList<TextField>(find.byType(TextField)).toList();
    expect(fields.length, 2);
    for (final f in fields) {
      expect(f.controller!.text, isEmpty);
    }
    expect(find.textContaining('demo', findRichText: true), findsNothing);
    expect(find.textContaining('patient123'), findsNothing);
  });

  testWidgets('empty submit shows the inline message and does not call the server', (tester) async {
    final api = await _open(tester);
    await tester.tap(find.text('Sign In'));
    await tester.pump();
    expect(find.text('Enter your email or NRIC and your password.'), findsOneWidget);
    expect(api.logins, 0);
  });

  testWidgets('emergency scan is a secondary action below Sign In', (tester) async {
    await _open(tester);
    final signIn = tester.getTopLeft(find.text('Sign In')).dy;
    final scan = tester.getTopLeft(find.text('Scan an emergency card (QR or NFC)')).dy;
    expect(scan, greaterThan(signIn));
  });

  testWidgets('code step: email resend is on a cooldown after sending', (tester) async {
    await _open(tester);
    await tester.enterText(find.byType(TextField).first, 'p@x.test');
    await tester.enterText(find.byType(TextField).last, 'pw');
    await tester.tap(find.text('Sign In'));
    await tester.pumpAndSettle();
    expect(find.text('Two-step verification'), findsOneWidget);
    await tester.tap(find.text('Email me a code instead'));
    await tester.pump();
    await tester.pump();
    expect(find.textContaining('Send a new code in'), findsOneWidget);
    await tester.pumpWidget(const SizedBox()); // dispose the screen and its ticker
  });
}
