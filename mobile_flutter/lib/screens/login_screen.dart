import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';
import 'emergency_scanner_screen.dart';
import 'forgot_password_screen.dart';
import 'self_register_screen.dart';
import 'settings_screen.dart';

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
  final _identifierController = TextEditingController(text: 'patient@clarion.demo');
  final _passwordController = TextEditingController(text: 'patient123');
  final _codeController = TextEditingController();
  bool _obscure = true;

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
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(AppLocalizations.of(context).sessionExpiredSnackbar)),
        );
      }
    });
  }

  @override
  void dispose() {
    _identifierController.dispose();
    _passwordController.dispose();
    _codeController.dispose();
    super.dispose();
  }

  Future<void> _handleLogin() async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final ok = await auth.login(_identifierController.text.trim(), _passwordController.text);
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(auth.error ?? l10n.loginFailedGeneric)),
      );
    }
  }

  Future<void> _handleVerify() async {
    final auth = context.read<AuthProvider>();
    final ok = await auth.verifyMfa(_codeController.text.trim());
    if (ok) {
      _codeController.clear();
    } else if (mounted && auth.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(auth.error!)));
    }
  }

  List<Widget> _buildMfaStep(AppLocalizations l10n, AuthProvider auth) {
    return [
      Text(l10n.mfaTitle, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      Text(l10n.mfaPrompt, textAlign: TextAlign.center,
          style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
      const SizedBox(height: 16),
      TextField(
        controller: _codeController,
        autofocus: true,
        autocorrect: false,
        maxLength: 11,
        textAlign: TextAlign.center,
        style: const TextStyle(fontSize: 20, letterSpacing: 4),
        decoration: InputDecoration(labelText: l10n.mfaCodeLabel, counterText: ''),
        onSubmitted: (_) => auth.isBusy ? null : _handleVerify(),
      ),
      const SizedBox(height: 12),
      SizedBox(
        width: double.infinity,
        child: ElevatedButton(
          onPressed: auth.isBusy ? null : _handleVerify,
          child: auth.isBusy
              ? const SizedBox(
                  height: 20, width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : Text(l10n.mfaVerifyButton),
        ),
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
            onPressed: () => Navigator.of(context)
                .push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
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
                // Reachable without signing in at all — this is for
                // *responders*, not the patient. Matches the backend's
                // design: /emergency/scan and /emergency/nfc/scan require
                // no auth (see backend/app/routers/emergency.py).
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: context.palette.emergency,
                      padding: const EdgeInsets.symmetric(vertical: 18),
                    ),
                    onPressed: () => Navigator.of(context)
                        .push(MaterialPageRoute(builder: (_) => const EmergencyScannerScreen())),
                    icon: const Icon(Icons.qr_code_scanner, color: Colors.white),
                    label: Text(
                      l10n.scanEmergencyCardButton,
                      style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                if (auth.awaitingMfa) ..._buildMfaStep(l10n, auth) else ...[
                TextField(
                  controller: _identifierController,
                  keyboardType: TextInputType.text,
                  autocorrect: false,
                  textCapitalization: TextCapitalization.none,
                  decoration: InputDecoration(labelText: l10n.emailOrNricLabel, hintText: l10n.emailOrNricLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _passwordController,
                  obscureText: _obscure,
                  decoration: InputDecoration(
                    labelText: l10n.passwordLabel,
                    hintText: l10n.passwordLabel,
                    suffixIcon: IconButton(
                      icon: Icon(_obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined),
                      onPressed: () => setState(() => _obscure = !_obscure),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: auth.isBusy ? null : _handleLogin,
                    child: auth.isBusy
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : Text(l10n.signIn),
                  ),
                ),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: () => Navigator.of(context)
                        .push(MaterialPageRoute(builder: (_) => const ForgotPasswordScreen())),
                    child: Text(l10n.forgotPasswordButton, style: const TextStyle(fontSize: 13)),
                  ),
                ),
                // Self-service registration entry point — near, not
                // replacing, the Forgot password link above. Today only
                // staff can create a patient login in person via the web
                // console; this is the self-service alternative (NRIC-OCR
                // identity verification, see SelfRegisterScreen).
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(l10n.selfRegisterLinkPrompt,
                        style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
                    TextButton(
                      onPressed: () => Navigator.of(context)
                          .push(MaterialPageRoute(builder: (_) => const SelfRegisterScreen())),
                      child: Text(l10n.selfRegisterLinkAction, style: const TextStyle(fontSize: 13)),
                    ),
                  ],
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
