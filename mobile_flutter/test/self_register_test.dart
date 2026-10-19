import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/screens/self_register_screen.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class _Api extends ApiClient {
  _Api(this.photoCheck) : super(config: AppConfig(), tokenStorage: TokenStorage());
  final bool photoCheck;
  Map<String, dynamic>? started;
  Map<String, dynamic>? verified;

  @override
  Future<bool> selfRegisterPhotoCheck() async => photoCheck;

  @override
  Future<Map<String, dynamic>> claimStart({
    required String nationalId,
    required String fullName,
    required String email,
  }) async {
    started = {'nric': nationalId, 'name': fullName, 'email': email};
    return {'status': 'ok'};
  }

  @override
  Future<Map<String, dynamic>> claimVerifyOtp({
    required String nationalId,
    required String email,
    required String otpCode,
    required String password,
  }) async {
    verified = {'email': email, 'code': otpCode, 'password': password};
    return {'status': 'pending', 'photo_check': photoCheck};
  }
}

Future<_Api> _open(WidgetTester tester, {required bool photoCheck}) async {
  final api = _Api(photoCheck);
  await tester.pumpWidget(
    Provider<ApiClient>.value(
      value: api,
      child: const MaterialApp(
        locale: Locale('en'),
        supportedLocales: [Locale('en')],
        localizationsDelegates: [
          AppLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: SelfRegisterScreen(),
      ),
    ),
  );
  await tester.pump();
  await tester.pump();
  return api;
}

void main() {
  testWidgets('details: NRIC loses dashes, name is capitals; then code + password; then waits', (tester) async {
    final api = await _open(tester, photoCheck: false);
    expect(find.byType(TextField), findsNWidgets(3)); // NRIC, name, email

    await tester.enterText(find.byType(TextField).at(0), '900101-01-1234');
    await tester.enterText(find.byType(TextField).at(1), 'Aminah Binti Test');
    await tester.enterText(find.byType(TextField).at(2), 'a@example.com');
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(api.started!['nric'], '900101011234');
    expect(api.started!['name'], 'AMINAH BINTI TEST');

    // code + new password + confirm
    expect(find.byType(TextField), findsNWidgets(3));
    await tester.enterText(find.byType(TextField).at(0), '123456');
    await tester.enterText(find.byType(TextField).at(1), 'Str0ng!Passw0rd#1');
    await tester.enterText(find.byType(TextField).at(2), 'Str0ng!Passw0rd#1');
    await tester.tap(find.text('Verify Code'));
    await tester.pumpAndSettle();
    expect(api.verified!['code'], '123456');
    expect(find.textContaining('waiting for verification', findRichText: true), findsOneWidget);
  });
}
