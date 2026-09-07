import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../theme/app_theme.dart';

/// Dismissible, purely-informational nudge shown on HomeScreen when
/// `AuthProvider.missingProfileFields` is non-empty (see MBUser). Tapping
/// it navigates to EditProfileScreen; the (x) dismisses it for the rest of
/// this session only — no persistence, matching the "session-only dismiss
/// is fine" spec. Never blocks navigation on its own.
class MissingProfileBanner extends StatelessWidget {
  const MissingProfileBanner({super.key, required this.onTap, required this.onDismiss});

  final VoidCallback onTap;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Material(
      color: context.palette.chipBg,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: [
              Icon(Icons.info_outline, color: context.palette.primary, size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  l10n.missingProfileBannerText,
                  style: TextStyle(fontSize: 13, color: context.palette.primary, fontWeight: FontWeight.w500, height: 1.3),
                ),
              ),
              IconButton(
                tooltip: l10n.dismiss,
                icon: Icon(Icons.close, size: 18, color: context.palette.primary),
                onPressed: onDismiss,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
