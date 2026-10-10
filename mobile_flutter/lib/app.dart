import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';
import 'l10n/generated/app_localizations.dart';
import 'providers/auth_provider.dart';
import 'providers/locale_provider.dart';
import 'providers/patient_provider.dart';
import 'providers/queue_provider.dart';
import 'providers/reminders_provider.dart';
import 'providers/theme_provider.dart';
import 'screens/change_password_screen.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/senior/senior_home_screen.dart';
import 'services/api_client.dart';
import 'services/notification_service.dart';
import 'theme/app_theme.dart';
import 'widgets/update_banner.dart';

class ClarionApp extends StatefulWidget {
  const ClarionApp({
    super.key,
    required this.appConfig,
    required this.apiClient,
    required this.authProvider,
    required this.patientProvider,
    required this.queueProvider,
    required this.localeProvider,
    required this.remindersProvider,
    required this.themeProvider,
  });

  final AppConfig appConfig;
  final ApiClient apiClient;
  final AuthProvider authProvider;
  final PatientProvider patientProvider;
  final QueueProvider queueProvider;
  final LocaleProvider localeProvider;
  final RemindersProvider remindersProvider;
  final ThemeProvider themeProvider;

  @override
  State<ClarionApp> createState() => _ClarionAppState();
}

class _ClarionAppState extends State<ClarionApp> {
  late final Future<void> _bootstrap;

  // FIX for "no way to log out after 'session expired' during backend
  // downtime": `_AuthGate` below swaps HomeScreen/SeniorHomeScreen for
  // LoginScreen the instant `AuthProvider.status` flips to
  // `unauthenticated` (either via a deliberate Sign Out or the involuntary
  // `forceLogout()` fired from a 401) — but that swap only replaces the
  // *root* route's content. If the user had navigated deeper (e.g. into
  // Reminders, Settings, the Emergency screen) via `Navigator.push`, that
  // pushed route stays on top of the stack and visually hides the
  // now-swapped-to LoginScreen underneath, so the user appears "stuck" on
  // whatever screen they were on — often one showing a stale "session
  // expired" error with only a Retry button that re-fails the same way,
  // looking exactly like an infinite loop with no way out. A global
  // `navigatorKey` lets this widget reach into the root Navigator and pop
  // every pushed route back to the first one whenever auth stops being
  // `authenticated`, so LoginScreen actually becomes visible again no
  // matter how deep the user had navigated.
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  AuthStatus? _lastAuthStatus;

  @override
  void initState() {
    super.initState();
    _bootstrap = _init();
    widget.authProvider.addListener(_onAuthChanged);
  }

  @override
  void dispose() {
    widget.authProvider.removeListener(_onAuthChanged);
    super.dispose();
  }

  void _onAuthChanged() {
    final status = widget.authProvider.status;
    final previousStatus = _lastAuthStatus;
    final wasAuthenticated = previousStatus == AuthStatus.authenticated;
    _lastAuthStatus = status;
    if (wasAuthenticated && status == AuthStatus.unauthenticated) {
      // Defer to the next frame: this listener can fire mid-build (e.g.
      // from the async `forceLogout()` continuation), and `Navigator`
      // state must not be mutated during a build.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _navigatorKey.currentState?.popUntil((route) => route.isFirst);
      });
    } else if (previousStatus != AuthStatus.authenticated && status == AuthStatus.authenticated) {
      // The mirror-image case, for the same underlying reason: the
      // self-service registration screen (SelfRegisterScreen) is pushed
      // *on top of* LoginScreen, and its final step
      // (`AuthProvider.completeWithLoginResponse`) flips `status` straight
      // to `authenticated` without ever popping itself first. Without
      // this, `_AuthGate` below swaps its *root* content to Home/
      // SeniorHome, but the still-pushed SelfRegisterScreen route stays on
      // top and hides it — same class of "stuck on the wrong screen" bug
      // as the unauthenticated case above, just in the opposite direction.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _navigatorKey.currentState?.popUntil((route) => route.isFirst);
      });
    }
  }

  Future<void> _init() async {
    await widget.appConfig.load();
    await widget.localeProvider.load();
    await widget.themeProvider.load();
    await widget.authProvider.bootstrap();
    _lastAuthStatus = widget.authProvider.status;
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
        ChangeNotifierProvider.value(value: widget.queueProvider),
        ChangeNotifierProvider.value(value: widget.localeProvider),
        ChangeNotifierProvider.value(value: widget.remindersProvider),
        ChangeNotifierProvider.value(value: widget.themeProvider),
        Provider.value(value: widget.apiClient),
      ],
      child: Consumer2<LocaleProvider, ThemeProvider>(
        builder: (context, localeProvider, themeProvider, _) {
          return MaterialApp(
            navigatorKey: _navigatorKey,
            title: 'CLARION',
            debugShowCheckedModeBanner: false,
            theme: buildAppLightTheme(),
            darkTheme: buildAppDarkTheme(),
            themeMode: themeProvider.themeMode,
            locale: localeProvider.locale,
            supportedLocales: kSupportedLocales,
            localizationsDelegates: const [
              AppLocalizations.delegate,
              GlobalMaterialLocalizations.delegate,
              GlobalWidgetsLocalizations.delegate,
              GlobalCupertinoLocalizations.delegate,
            ],
            builder: (context, child) => UpdateBanner(
              api: widget.apiClient,
              config: widget.appConfig,
              child: child ?? const SizedBox.shrink(),
            ),
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
    return Scaffold(
      backgroundColor: context.palette.background,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Image(
              image: AssetImage('assets/images/clarion_logo_full.png'),
              width: 180,
            ),
            const SizedBox(height: 16),
            CircularProgressIndicator(color: context.palette.primary),
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
            // A staff-issued temp password (`must_change_password` on the
            // login response) blocks entry to Home/SeniorHome until
            // changed — see ChangePasswordScreen. This check must come
            // before the Senior Mode branch: forced password change is not
            // part of the simplified senior hub, it always uses standard
            // styling regardless of that preference.
            if (auth.mustChangePassword) return const ChangePasswordScreen();
            return auth.prefersSeniorMode
                ? const SeniorHomeScreen()
                : const HomeScreen();
        }
      },
    );
  }
}
