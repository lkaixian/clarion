import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';
import 'l10n/generated/app_localizations.dart';
import 'providers/auth_provider.dart';
import 'providers/locale_provider.dart';
import 'providers/patient_provider.dart';
import 'providers/reminders_provider.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/senior/senior_home_screen.dart';
import 'services/api_client.dart';
import 'services/notification_service.dart';
import 'theme/app_theme.dart';

class MediBridgeApp extends StatefulWidget {
  const MediBridgeApp({
    super.key,
    required this.appConfig,
    required this.apiClient,
    required this.authProvider,
    required this.patientProvider,
    required this.localeProvider,
    required this.remindersProvider,
  });

  final AppConfig appConfig;
  final ApiClient apiClient;
  final AuthProvider authProvider;
  final PatientProvider patientProvider;
  final LocaleProvider localeProvider;
  final RemindersProvider remindersProvider;

  @override
  State<MediBridgeApp> createState() => _MediBridgeAppState();
}

class _MediBridgeAppState extends State<MediBridgeApp> {
  late final Future<void> _bootstrap;

  @override
  void initState() {
    super.initState();
    _bootstrap = _init();
  }

  Future<void> _init() async {
    await widget.appConfig.load();
    await widget.localeProvider.load();
    await widget.authProvider.bootstrap();
    // Local-notification plumbing (timezone data, plugin init) — cheap and
    // side-effect-free if reminders end up unused this session.
    await NotificationService.instance.init();
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: widget.appConfig),
        ChangeNotifierProvider.value(value: widget.authProvider),
        ChangeNotifierProvider.value(value: widget.patientProvider),
        ChangeNotifierProvider.value(value: widget.localeProvider),
        ChangeNotifierProvider.value(value: widget.remindersProvider),
        Provider.value(value: widget.apiClient),
      ],
      child: Consumer<LocaleProvider>(
        builder: (context, localeProvider, _) {
          return MaterialApp(
            title: 'MediBridge',
            debugShowCheckedModeBanner: false,
            theme: buildAppTheme(),
            locale: localeProvider.locale,
            supportedLocales: kSupportedLocales,
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            home: FutureBuilder<void>(
              future: _bootstrap,
              builder: (context, snapshot) {
                if (snapshot.connectionState != ConnectionState.done) {
                  return const _SplashScreen();
                }
                return const _AuthGate();
              },
            ),
          );
        },
      ),
    );
  }
}

class _SplashScreen extends StatelessWidget {
  const _SplashScreen();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppColors.background,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              'MediBridge',
              style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: AppColors.primary),
            ),
            SizedBox(height: 16),
            CircularProgressIndicator(color: AppColors.primary),
          ],
        ),
      ),
    );
  }
}

class _AuthGate extends StatelessWidget {
  const _AuthGate();

  @override
  Widget build(BuildContext context) {
    return Consumer<AuthProvider>(
      builder: (context, auth, _) {
        switch (auth.status) {
          case AuthStatus.unknown:
            return const _SplashScreen();
          case AuthStatus.unauthenticated:
            return const LoginScreen();
          case AuthStatus.authenticated:
            return auth.prefersSeniorMode ? const SeniorHomeScreen() : const HomeScreen();
        }
      },
    );
  }
}
