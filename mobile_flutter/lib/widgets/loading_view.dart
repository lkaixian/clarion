import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';

class LoadingView extends StatelessWidget {
  const LoadingView({super.key});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: CircularProgressIndicator(color: context.palette.primary),
    );
  }
}

/// FIX for "no way to log out after 'session expired' during backend
/// downtime": every full-screen error state that can plausibly be caused
/// by a dead/expired session (a 401 surfaces here as a plain string, same
/// as any other API error) now offers a working, explicit way back to the
/// login screen — not just a Retry button that can re-fail the same way
/// forever. [showLogout] is opt-in per call site (screens whose errors are
/// never auth-related, if any, can leave it off), but every current call
/// site that can render an auth-flavoured error passes it. Signing out
/// here goes through the same deliberate [AuthProvider.logout] the Home
/// screen's "Sign out" button uses; combined with the auth-status listener
/// in `app.dart` that pops back to the root route on any transition to
/// `unauthenticated`, this guarantees a route back to a real, visible
/// LoginScreen even if the user had navigated several screens deep.
class ErrorRetryView extends StatelessWidget {
  const ErrorRetryView({
    super.key,
    required this.message,
    this.onRetry,
    this.showLogout = false,
  });

  final String message;
  final VoidCallback? onRetry;
  final bool showLogout;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.error_outline,
              color: context.palette.emergency,
              size: 40,
            ),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(color: context.palette.textBody),
            ),
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              ElevatedButton(onPressed: onRetry, child: Text(l10n.retry)),
            ],
            if (showLogout) ...[
              const SizedBox(height: 8),
              TextButton(
                onPressed: () => context.read<AuthProvider>().logout(),
                child: Text(
                  l10n.signOut,
                  style: TextStyle(color: context.palette.textMuted),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
