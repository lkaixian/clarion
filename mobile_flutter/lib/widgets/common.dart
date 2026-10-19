import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../l10n/generated/app_localizations.dart';
import '../theme/app_theme.dart';

/// 20dp white spinner shown inside a primary button while its action runs.
class ButtonSpinner extends StatelessWidget {
  const ButtonSpinner({super.key});

  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 20,
        width: 20,
        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
      );
}

/// Muted one-line "nothing here yet" text used inside cards.
class EmptyText extends StatelessWidget {
  const EmptyText(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) =>
      Text(text, style: TextStyle(fontSize: 13, color: context.palette.textFaint));
}

extension ContextX on BuildContext {
  /// Shows a plain-text snackbar on the nearest [ScaffoldMessenger].
  void snack(String message) =>
      ScaffoldMessenger.of(this).showSnackBar(SnackBar(content: Text(message)));

  /// Pushes [screen] on the nearest [Navigator] with a standard Material route.
  Future<T?> pushScreen<T>(Widget screen) =>
      Navigator.of(this).push<T>(MaterialPageRoute<T>(builder: (_) => screen));
}

/// "Today", "Yesterday", "N days ago" (up to [maxDaysAgo]), else "d MMM yyyy".
String relativeDay(AppLocalizations l10n, DateTime t, DateTime now, String locale, {int maxDaysAgo = 30}) {
  final days = DateTime(now.year, now.month, now.day).difference(DateTime(t.year, t.month, t.day)).inDays;
  if (days == 0) return l10n.dayToday;
  if (days == 1) return l10n.dayYesterday;
  if (days > 1 && days <= maxDaysAgo) return l10n.daysAgo(days);
  return DateFormat('d MMM yyyy', locale).format(t);
}
