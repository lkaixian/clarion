import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../theme/app_theme.dart';

/// Terminal, dead-end screen reached after the 5th (final) failed
/// NRIC-photo-verification attempt during self-service registration (see
/// `SelfRegisterScreen`). The backend has already flagged the attempt at
/// this point (`403` with `next_step: "manual_registration_required"` on
/// `ApiClient.selfRegisterVerifyPhotos`) — this is not just another error
/// snackbar layered on the same flow, it's a dedicated full-screen
/// replacement with calm, clear copy and, deliberately, **no retry
/// button**: offering a 6th attempt client-side would invite a request the
/// backend will reject anyway, which is exactly the confusing dead-end
/// this screen exists to avoid.
///
/// Reached via `Navigator.pushReplacement` from `SelfRegisterScreen`, so
/// it sits directly on top of `LoginScreen` in the stack — "Back to Sign
/// In" is therefore a plain `pop()`.
class SelfRegisterManualRequiredScreen extends StatelessWidget {
  const SelfRegisterManualRequiredScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return PopScope(
      // A plain back-gesture/back-button press has the same effect as the
      // explicit button below (return to Sign In) — there's nothing this
      // screen's own step state to protect, unlike ChangePasswordScreen's
      // hard block.
      canPop: true,
      child: Scaffold(
        backgroundColor: context.palette.background,
        appBar: AppBar(title: Text(l10n.selfRegisterManualRequiredTitle)),
        body: SafeArea(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.badge_outlined, size: 56, color: context.palette.primary),
                  const SizedBox(height: 20),
                  Text(
                    l10n.selfRegisterManualRequiredTitle,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: context.palette.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    l10n.selfRegisterManualRequiredBody,
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 14, color: context.palette.textBody, height: 1.5),
                  ),
                  const SizedBox(height: 28),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: Text(l10n.selfRegisterManualRequiredBackButton),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
