import 'package:flutter/material.dart';

import 'app.dart';
import 'config/app_config.dart';
import 'providers/auth_provider.dart';
import 'providers/locale_provider.dart';
import 'providers/patient_provider.dart';
import 'providers/reminders_provider.dart';
import 'services/api_client.dart';
import 'services/token_storage.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  final appConfig = AppConfig();
  final tokenStorage = TokenStorage();
  final apiClient = ApiClient(config: appConfig, tokenStorage: tokenStorage);
  final authProvider = AuthProvider(api: apiClient, tokenStorage: tokenStorage);
  final patientProvider = PatientProvider(api: apiClient);
  final localeProvider = LocaleProvider();
  final remindersProvider = RemindersProvider();

  runApp(MediBridgeApp(
    appConfig: appConfig,
    apiClient: apiClient,
    authProvider: authProvider,
    patientProvider: patientProvider,
    localeProvider: localeProvider,
    remindersProvider: remindersProvider,
  ));
}
