import 'package:flutter/material.dart';

import 'app.dart';
import 'config/app_config.dart';
import 'providers/auth_provider.dart';
import 'providers/locale_provider.dart';
import 'providers/patient_provider.dart';
import 'providers/queue_provider.dart';
import 'providers/reminders_provider.dart';
import 'providers/theme_provider.dart';
import 'services/api_client.dart';
import 'services/token_storage.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  final appConfig = AppConfig();
  final tokenStorage = TokenStorage();
  final apiClient = ApiClient(config: appConfig, tokenStorage: tokenStorage);
  final authProvider = AuthProvider(api: apiClient, tokenStorage: tokenStorage);
  // ApiClient is constructed before AuthProvider above, so it can't take one
  // in its own constructor (circular dependency) — instead it exposes a
  // settable callback that we wire up here, once both objects exist. See
  // ApiClient.onUnauthorized / AuthProvider.forceLogout doc comments. This
  // is a plain object reference, not `context`/`Provider.of`, so it's safe
  // to do here before runApp. `forceLogout` is async, but there's nothing
  // useful to await from inside a Dio error interceptor (see ApiClient's
  // onError), so this is a deliberate fire-and-forget: it only ever clears
  // local secure storage and flips in-memory state, nothing that can
  // meaningfully fail or that any caller is waiting on.
  apiClient.onUnauthorized = () => authProvider.forceLogout();
  final patientProvider = PatientProvider(api: apiClient);
  final queueProvider = QueueProvider(api: apiClient);
  final localeProvider = LocaleProvider();
  final remindersProvider = RemindersProvider();
  final themeProvider = ThemeProvider();

  runApp(ClarionApp(
    appConfig: appConfig,
    apiClient: apiClient,
    authProvider: authProvider,
    patientProvider: patientProvider,
    queueProvider: queueProvider,
    localeProvider: localeProvider,
    remindersProvider: remindersProvider,
    themeProvider: themeProvider,
  ));
}
