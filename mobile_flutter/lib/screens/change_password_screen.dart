import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';

/// Forced interstitial shown by `_AuthGate` (see app.dart) instead of
/// Home/SeniorHome whenever the signed-in account still has
/// `AuthProvider.mustChangePassword == true` (staff issued a temporary
/// password). Deliberately has no way to bypass to Home while the flag is
/// still set — no back button, no dismiss — but keeps a working "Sign out"
/// escape hatch for a user who genuinely can't get past this (e.g. they've
/// forgotten the temp password staff gave them), returning them to
/// LoginScreen rather than leaving them stuck.
class ChangePasswordScreen extends StatefulWidget {
  const ChangePasswordScreen({super.key});

  @override
  State<ChangePasswordScreen> createState() => _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends State<ChangePasswordScreen> {
  final _currentPasswordController = TextEditingController();
  final _newPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  bool _obscureCurrent = true;
  bool _obscureNew = true;
  bool _obscureConfirm = true;

  @override
  void dispose() {
    _currentPasswordController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _handleSubmit() async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final newPassword = _newPasswordController.text;
    final confirmPassword = _confirmPasswordController.text;

    if (_currentPasswordController.text.isEmpty || newPassword.isEmpty || confirmPassword.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l10n.allFieldsRequired)));
      return;
    }
    if (newPassword != confirmPassword) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l10n.passwordsDoNotMatch)));
      return;
    }

    final ok = await auth.changePassword(_currentPasswordController.text, newPassword);
    if (!mounted) return;
    if (ok) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l10n.passwordChangedSnack)));
      // No further navigation needed here: `_AuthGate` is a
      // Consumer<AuthProvider> and `auth.mustChangePassword` is now false,
      // so it will swap this screen out for Home/SeniorHome on its own.
    } else {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(auth.error ?? l10n.loginFailedGeneric)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();

    return PopScope(
      // Hard block on back/dismiss while a password change is still
      // required — this screen must not be escapable except via Sign out.
      canPop: false,
      child: Scaffold(
        backgroundColor: AppColors.background,
        appBar: AppBar(
          title: Text(l10n.changePasswordTitle),
          automaticallyImplyLeading: false,
        ),
        body: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: AppColors.chipBg,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    l10n.changePasswordRequiredNotice,
                    style: const TextStyle(fontSize: 13, color: AppColors.primary, height: 1.4),
                  ),
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _currentPasswordController,
                  obscureText: _obscureCurrent,
                  decoration: InputDecoration(
                    labelText: l10n.temporaryPasswordLabel,
                    hintText: l10n.temporaryPasswordLabel,
                    suffixIcon: IconButton(
                      icon: Icon(_obscureCurrent ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                      onPressed: () => setState(() => _obscureCurrent = !_obscureCurrent),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _newPasswordController,
                  obscureText: _obscureNew,
                  decoration: InputDecoration(
                    labelText: l10n.newPasswordLabel,
                    hintText: l10n.newPasswordLabel,
                    suffixIcon: IconButton(
                      icon: Icon(_obscureNew ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                      onPressed: () => setState(() => _obscureNew = !_obscureNew),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _confirmPasswordController,
                  obscureText: _obscureConfirm,
                  decoration: InputDecoration(
                    labelText: l10n.confirmNewPasswordLabel,
                    hintText: l10n.confirmNewPasswordLabel,
                    suffixIcon: IconButton(
                      icon: Icon(_obscureConfirm ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                      onPressed: () => setState(() => _obscureConfirm = !_obscureConfirm),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: auth.isBusy ? null : _handleSubmit,
                    child: auth.isBusy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : Text(l10n.changePasswordButton),
                  ),
                ),
                const SizedBox(height: 16),
                Center(
                  child: TextButton(
                    onPressed: auth.isBusy ? null : () => auth.logout(),
                    child: Text(l10n.signOut, style: const TextStyle(color: AppColors.textMuted)),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
