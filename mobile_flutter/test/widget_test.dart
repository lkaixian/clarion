// Minimal smoke test: renders LoginScreen (with real providers, but
// without triggering any storage/network I/O — LoginScreen's build method
// only reads plain in-memory fields off AuthProvider) and checks the
// expected English strings appear.
//
// NOTE: this is the one thing in this project we *could* actually execute
// in this sandboxed environment (no Android emulator/device available) —
// see mobile_flutter/README.md for exactly what was and wasn't verified.

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

void main() {
  testWidgets('LoginScreen renders title, fields and sign-in button', (
    WidgetTester tester,
  ) async {
    final appConfig = AppConfig();
    final tokenStorage = TokenStorage();
    final apiClient = ApiClient(config: appConfig, tokenStorage: tokenStorage);
    final authProvider = AuthProvider(
      api: apiClient,
      tokenStorage: tokenStorage,
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: authProvider),
          Provider.value(value: apiClient),
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
          home: LoginScreen(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // The login screen shows the CLARION logo image (not a text title) and
    // pre-fills demo credentials in the two fields; the old demo-hint text
    // line no longer exists.
    expect(find.byType(Image), findsOneWidget);
    expect(find.byType(TextField), findsNWidgets(2));
    expect(find.text('Sign In'), findsOneWidget);
  });
}
