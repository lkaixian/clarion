import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../theme/app_theme.dart';

/// Mirrors backend `schemas.password_rule_failures` -- keep the two in step.
const kPasswordSpecials = '!@#\$*.?';

bool _hasSpecial(String v) => v.split('').any(kPasswordSpecials.contains);

/// One entry per rule, in display order.
List<bool> passwordRuleResults(String v) => [
      v.length >= 8,
      RegExp(r'\d').hasMatch(v),
      RegExp(r'[A-Z]').hasMatch(v),
      _hasSpecial(v),
    ];

bool passwordMeetsRules(String v) => passwordRuleResults(v).every((ok) => ok);

/// Live checklist under a "new password" field: each rule turns green with a
/// tick once met. Rebuilds on every keystroke from [controller].
class PasswordRules extends StatelessWidget {
  const PasswordRules({super.key, required this.controller});

  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final labels = [
      l10n.passwordRuleLength,
      l10n.passwordRuleNumber,
      l10n.passwordRuleUpper,
      l10n.passwordRuleSpecial,
    ];
    return ValueListenableBuilder<TextEditingValue>(
      valueListenable: controller,
      builder: (context, value, _) {
        final results = passwordRuleResults(value.text);
        return Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(l10n.passwordRulesTitle,
                  style: TextStyle(fontSize: 12, color: context.palette.textMuted)),
              const SizedBox(height: 4),
              for (var i = 0; i < labels.length; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(children: [
                    Icon(
                      results[i] ? Icons.check_circle : Icons.radio_button_unchecked,
                      size: 16,
                      color: results[i] ? Colors.green.shade700 : context.palette.textFaint,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        labels[i],
                        style: TextStyle(
                          fontSize: 13,
                          color: results[i] ? Colors.green.shade800 : context.palette.textMuted,
                        ),
                      ),
                    ),
                  ]),
                ),
            ],
          ),
        );
      },
    );
  }
}
