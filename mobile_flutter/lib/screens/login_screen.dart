import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';
import 'emergency_scanner_screen.dart';
import 'forgot_password_screen.dart';
import 'self_register_screen.dart';
import 'settings_screen.dart';
import '../widgets/common.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  // Backend contract (see backend/app/routers/auth_router.py): the existing
  // `username` form field on `POST /auth/login` now accepts either an
  // email address or a patient's NRIC (Patient.national_id) — same field,
  // same endpoint, same response shape either way. Field/controller kept
  // generically named for that reason.
  final _identifierController = TextEditingController();
  final _passwordController = TextEditingController();
  final _codeController = TextEditingController();
  bool _obscure = true;

  /// Earliest moment another emailed code may be requested (the server also
  /// rate-limits; this just stops pointless taps and shows why).
  static const _resendCooldown = Duration(seconds: 30);
  DateTime? _resendAt;
  Timer? _ticker;
  bool _fieldsMissing = false;

  int get _resendSeconds {
    final at = _resendAt;
    if (at == null) return 0;
    final left = at.difference(DateTime.now()).inSeconds + 1;
    return left > 0 ? left : 0;
  }

  void _startResendCooldown() {
    _resendAt = DateTime.now().add(_resendCooldown);
    _ticker?.cancel();
    _ticker = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || _resendSeconds == 0) t.cancel();
      if (mounted) setState(() {});
    });
  }

  @override
  void initState() {
    super.initState();
    // If we landed here because ApiClient.onUnauthorized fired
    // (AuthProvider.forceLogout — see its doc comment) rather than a
    // deliberate Sign Out, `auth.sessionExpired` will be true exactly once.
    // Show a one-time explanatory snackbar instead of silently dumping the
    // user back on the login form. Scheduled for after the first frame
    // since ScaffoldMessenger.of(context) needs a built Scaffold, and
    // reading/mutating AuthProvider during initState's own build is unsafe.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final auth = context.read<AuthProvider>();
      if (auth.sessionExpired) {
        auth.acknowledgeSessionExpired();
        context.snack(AppLocalizations.of(context).sessionExpiredSnackbar);
      }
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _identifierController.dispose();
    _passwordController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  Future<void> _handleLogin() async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final id = _identifierController.text.trim();
    if (id.isEmpty || _passwordController.text.isEmpty) {
      setState(() => _fieldsMissing = true);
      return;
    }
    setState(() => _fieldsMissing = false);
    TextInput.finishAutofillContext(shouldSave: false);
    final ok = await auth.login(id, _passwordController.text);
    // A password that was right but needs a second factor is not a failure:
    // the code step simply appears.
    if (!ok && !auth.awaitingMfa && mounted) {
      context.snack(auth.error ?? l10n.loginFailedGeneric);
    }
  }

  /// Authenticator apps show "123 456"; recovery codes look like "abcde-fghij".
  String _normalisedCode() {
    final raw = _codeController.text.trim();
    return raw.contains('-') ? raw.toLowerCase() : raw.replaceAll(RegExp(r'\D'), '');
  }

  Future<void> _handleVerify() async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final ok = await auth.verifyMfa(_normalisedCode());
    if (ok) {
      _codeController.clear();
    } else if (mounted) {
      _codeController.clear();
      context.snack(auth.codeRejected ? l10n.mfaWrongCodeHint : (auth.error ?? l10n.loginFailedGeneric));
    }
  }

  Future<void> _handleSendEmail() async {
    final auth = context.read<AuthProvider>();
    final ok = await auth.sendMfaEmail();
    if (ok && mounted) setState(_startResendCooldown);
    if (!ok && mounted && auth.error != null) context.snack(auth.error!);
  }

  List<Widget> _buildMfaStep(AppLocalizations l10n, AuthProvider auth) {
    final emailMode = auth.mfaEmailSent;
    final prompt = emailMode
        ? l10n.mfaEmailSent(auth.mfaEmailHint ?? '')
        : (auth.mfaAuthenticatorOk ? l10n.mfaPrompt : l10n.mfaEmailPrompt);
    return [
      Text(l10n.mfaTitle, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      Text(prompt, textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
      const SizedBox(height: 16),
      if (auth.mfaAuthenticatorOk || emailMode)
        TextField(
          controller: _codeController,
          autofocus: true,
          autocorrect: false,
          keyboardType: TextInputType.visiblePassword,
          maxLength: 14,
          textAlign: TextAlign.center,
          style: const TextStyle(fontSize: 20, letterSpacing: 4),
          decoration: InputDecoration(
            labelText: emailMode ? l10n.mfaEmailCodeLabel : l10n.mfaCodeLabel,
            counterText: '',
          ),
          onSubmitted: (_) => auth.isBusy ? null : _handleVerify(),
        ),
      const SizedBox(height: 12),
      if (auth.mfaAuthenticatorOk || emailMode)
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: auth.isBusy ? null : _handleVerify,
            child: auth.isBusy
                ? const ButtonSpinner()
                : Text(l10n.mfaVerifyButton),
          ),
        ),
      if (auth.mfaEmailAvailable && !emailMode)
        SizedBox(
          width: double.infinity,
          child: auth.mfaAuthenticatorOk
              ? TextButton(
                  onPressed: auth.isBusy ? null : _handleSendEmail,
                  child: Text(l10n.mfaEmailButton),
                )
              : ElevatedButton(
                  onPressed: auth.isBusy ? null : _handleSendEmail,
                  child: Text(l10n.mfaEmailButton),
                ),
        ),
      if (emailMode)
        TextButton(
          onPressed: auth.isBusy || _resendSeconds > 0 ? null : _handleSendEmail,
          child: Text(_resendSeconds > 0 ? l10n.mfaResendIn(_resendSeconds) : l10n.mfaResendButton),
        ),
      if (emailMode && auth.mfaAuthenticatorOk)
        TextButton(
          onPressed: auth.isBusy ? null : () {
            _codeController.clear();
            auth.useAuthenticator();
          },
          child: Text(l10n.mfaUseAuthenticatorButton),
        ),
      TextButton(
        onPressed: () {
          _codeController.clear();
          auth.cancelMfa();
        },
        child: Text(l10n.mfaCancelButton),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();

    return Scaffold(
      backgroundColor: context.palette.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        foregroundColor: context.palette.textMuted,
        elevation: 0,
        actions: [
          IconButton(
            tooltip: l10n.apiSettingsTooltip,
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => context.pushScreen(const SettingsScreen()),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Image.asset(
                  'assets/images/clarion_logo_full.png',
                  width: 200,
                ),
                const SizedBox(height: 24),
                if (auth.awaitingMfa) ..._buildMfaStep(l10n, auth) else ...[
                  AutofillGroup(
                    child: Column(
                      children: [
                        TextField(
                          controller: _identifierController,
                          keyboardType: TextInputType.emailAddress,
                          textInputAction: TextInputAction.next,
                          autofillHints: const [AutofillHints.username],
                          autocorrect: false,
                          enableSuggestions: false,
                          textCapitalization: TextCapitalization.none,
                          decoration: InputDecoration(
                            labelText: l10n.emailOrNricLabel,
                            hintText: l10n.emailOrNricHint,
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: _passwordController,
                          obscureText: _obscure,
                          textInputAction: TextInputAction.done,
                          autofillHints: const [AutofillHints.password],
                          onSubmitted: (_) => auth.isBusy ? null : _handleLogin(),
                          decoration: InputDecoration(
                            labelText: l10n.passwordLabel,
                            suffixIcon: IconButton(
                              tooltip: l10n.passwordLabel,
                              icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                              onPressed: () => setState(() => _obscure = !_obscure),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (_fieldsMissing) ...[
                    const SizedBox(height: 8),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        l10n.loginFieldRequired,
                        style: TextStyle(fontSize: 13, color: context.palette.emergency),
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(50)),
                      onPressed: auth.isBusy ? null : _handleLogin,
                      child: auth.isBusy ? const ButtonSpinner() : Text(l10n.signIn),
                    ),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () => context.pushScreen(const ForgotPasswordScreen()),
                      child: Text(l10n.forgotPasswordButton, style: const TextStyle(fontSize: 13)),
                    ),
                  ),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(l10n.selfRegisterLinkPrompt,
                          style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
                      TextButton(
                        onPressed: () => context.pushScreen(const SelfRegisterScreen()),
                        child: Text(l10n.selfRegisterLinkAction, style: const TextStyle(fontSize: 13)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  const Divider(),
                  const SizedBox(height: 12),
                  // Responders need no account: /emergency/scan and /emergency/nfc/scan
                  // are public (backend/app/routers/emergency.py). Kept one tap away but
                  // secondary, since most people opening this screen are signing in.
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      style: OutlinedButton.styleFrom(
                        foregroundColor: context.palette.emergency,
                        side: BorderSide(color: context.palette.emergency),
                        minimumSize: const Size.fromHeight(50),
                      ),
                      onPressed: () => context.pushScreen(const EmergencyScannerScreen()),
                      icon: const Icon(Icons.qr_code_scanner),
                      label: Text(l10n.scanEmergencyCardButton),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    l10n.scanEmergencyCardSubtitle,
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 12, color: context.palette.textMuted),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
