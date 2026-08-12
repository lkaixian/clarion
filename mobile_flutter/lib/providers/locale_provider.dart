import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Supported app languages: English, Malay, Chinese (Simplified), Tamil.
const List<Locale> kSupportedLocales = [
  Locale('en'),
  Locale('ms'),
  Locale('zh'),
  Locale('ta'),
];

const Map<String, String> kLocaleDisplayNames = {
  'en': 'English',
  'ms': 'Bahasa Melayu',
  'zh': '简体中文',
  'ta': 'தமிழ்',
};

/// Persists the user's chosen app language across launches. Defaults to
/// English until the user picks something else in Settings — Senior
/// Citizen Mode screens read this same provider so the simplified UI is
/// available in every supported language too.
class LocaleProvider extends ChangeNotifier {
  static const _prefsKey = 'mb_locale';

  Locale _locale = const Locale('en');
  Locale get locale => _locale;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final code = prefs.getString(_prefsKey);
    if (code != null && kSupportedLocales.any((l) => l.languageCode == code)) {
      _locale = Locale(code);
    }
    notifyListeners();
  }

  Future<void> setLocale(Locale locale) async {
    _locale = locale;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefsKey, locale.languageCode);
    notifyListeners();
  }
}
