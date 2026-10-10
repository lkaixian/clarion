import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/password_rules.dart';

enum _Step { requestOtp, verifyAndReset }

/// Patient-only, OTP-based password reset — reachable with no auth at all
/// from a "Forgot password?" link on LoginScreen (same
/// no-auth-required-action pattern as the emergency QR scanner button
/// already on that screen). Two steps, driven by an internal state machine
/// on a single screen rather than two separate routes:
///
/// 1. NRIC only -> `POST /auth/request-password-reset-otp`. The response is
///    always the same generic shape regardless of whether the NRIC/email
///    actually exists (anti-enumeration by design) — this screen advances
///    to step 2 on any success, and never implies more than "if this
///    account has an email on file, a code was sent".
/// 2. 6-digit OTP + new password -> `POST /auth/reset-password-with-otp`.
///
/// Calls [ApiClient] directly (not through AuthProvider — there is no
/// session yet), same as the DOB-based flow this replaces used to.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _nricController = TextEditingController();
  final _otpController = TextEditingController();
  final _newPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  _Step _step = _Step.requestOtp;
  bool _obscureNew = true;
  bool _obscureConfirm = true;
  bool _loading = false;

  @override
  void dispose() {
    _nricController.dispose();
    _otpController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  Future<void> _requestOtp({bool isResend = false}) async {
    final l10n = AppLocalizations.of(context);
    final nric = _nricController.text.trim();
    if (nric.isEmpty) {
      context.snack(l10n.allFieldsRequired);
      return;
    }

    setState(() => _loading = true);
    try {
      final api = context.read<ApiClient>();
      await api.requestPasswordResetOtp(nationalId: nric);
      if (!mounted) return;
      context.snack(isResend ? l10n.resendCodeSentSnack : l10n.otpRequestedGenericSnack);
      setState(() => _step = _Step.verifyAndReset);
    } on ApiException catch (e) {
      if (!mounted) return;
      context.snack(e.message);
    } catch (e) {
      if (!mounted) return;
      context.snack(l10n.requestOtpFailedGeneric);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _resetPassword() async {
    final l10n = AppLocalizations.of(context);
    final nric = _nricController.text.trim();
    final otpCode = _otpController.text.trim();
    final newPassword = _newPasswordController.text;
    final confirmPassword = _confirmPasswordController.text;

    if (otpCode.isEmpty || newPassword.isEmpty || confirmPassword.isEmpty) {
      context.snack(l10n.allFieldsRequired);
      return;
    }
    if (newPassword != confirmPassword) {
      context.snack(l10n.passwordsDoNotMatch);
      return;
    }
    if (!passwordMeetsRules(newPassword)) {
      context.snack(l10n.passwordRulesNotMet);
      return;
    }

    setState(() => _loading = true);
    try {
      final api = context.read<ApiClient>();
      await api.resetPasswordWithOtp(nationalId: nric, otpCode: otpCode, newPassword: newPassword);
      if (!mounted) return;
      context.snack(l10n.passwordResetSuccessSnack);
      Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (!mounted) return;
      context.snack(e.message);
    } catch (e) {
      if (!mounted) return;
      context.snack(l10n.forgotPasswordFailedGeneric);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      backgroundColor: context.palette.background,
      appBar: AppBar(title: Text(l10n.forgotPasswordTitle)),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: _step == _Step.requestOtp ? _buildRequestStep(l10n) : _buildResetStep(l10n),
        ),
      ),
    );
  }

  Widget _buildRequestStep(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.forgotPasswordStep1Desc,
          style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
        ),
        const SizedBox(height: 24),
        TextField(
          controller: _nricController,
          keyboardType: TextInputType.text,
          autocorrect: false,
          textCapitalization: TextCapitalization.none,
          decoration: InputDecoration(labelText: l10n.nricLabel, hintText: l10n.nricLabel),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _loading ? null : () => _requestOtp(),
            child: _loading
                ? const ButtonSpinner()
                : Text(l10n.sendCodeButton),
          ),
        ),
      ],
    );
  }

  Widget _buildResetStep(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.forgotPasswordStep2Desc,
          style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
        ),
        const SizedBox(height: 24),
        TextField(
          controller: _otpController,
          keyboardType: TextInputType.number,
          inputFormatters: [
            FilteringTextInputFormatter.digitsOnly,
            LengthLimitingTextInputFormatter(6),
          ],
          decoration: InputDecoration(labelText: l10n.otpCodeLabel, hintText: l10n.otpCodeLabel),
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
        PasswordRules(controller: _newPasswordController),
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
            onPressed: _loading ? null : _resetPassword,
            child: _loading
                ? const ButtonSpinner()
                : Text(l10n.resetPasswordButton),
          ),
        ),
        const SizedBox(height: 8),
        Center(
          child: TextButton(
            onPressed: _loading ? null : () => _requestOtp(isResend: true),
            child: Text(l10n.resendCodeButton, style: const TextStyle(fontSize: 13)),
          ),
        ),
        Center(
          child: TextButton(
            onPressed: _loading ? null : () => setState(() => _step = _Step.requestOtp),
            child: Text(l10n.useDifferentNricButton,
                style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
          ),
        ),
      ],
    );
  }
}
