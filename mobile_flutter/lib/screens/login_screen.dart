import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';
import 'emergency_scanner_screen.dart';
import 'settings_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _emailController = TextEditingController(text: 'patient@medibridge.demo');
  final _passwordController = TextEditingController(text: 'patient123');
  bool _obscure = true;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _handleLogin() async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final ok = await auth.login(_emailController.text.trim(), _passwordController.text);
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(auth.error ?? l10n.loginFailedGeneric)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final auth = context.watch<AuthProvider>();

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        foregroundColor: AppColors.textMuted,
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
                Text(
                  l10n.appTitle,
                  style: const TextStyle(fontSize: 32, fontWeight: FontWeight.bold, color: AppColors.primary),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 6),
                Text(
                  l10n.loginSubtitle,
                  style: const TextStyle(fontSize: 14, color: AppColors.textMuted),
                  textAlign: TextAlign.center,
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
                      backgroundColor: AppColors.emergency,
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
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    l10n.scanEmergencyCardSubtitle,
                    style: const TextStyle(fontSize: 11, color: AppColors.textFaint),
                    textAlign: TextAlign.center,
                  ),
                ),
                const SizedBox(height: 24),
                Row(
                  children: [
                    const Expanded(child: Divider()),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      child: Text(l10n.orSignInDivider, style: const TextStyle(fontSize: 12, color: AppColors.textFaint)),
                    ),
                    const Expanded(child: Divider()),
                  ],
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _emailController,
                  keyboardType: TextInputType.emailAddress,
                  autocorrect: false,
                  textCapitalization: TextCapitalization.none,
                  decoration: InputDecoration(labelText: l10n.emailLabel, hintText: l10n.emailLabel),
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
                const SizedBox(height: 16),
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
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.chipBg,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    l10n.demoLoginHint,
                    style: const TextStyle(fontSize: 12, color: AppColors.primary),
                    textAlign: TextAlign.center,
                  ),
                ),
                const SizedBox(height: 24),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Flexible(
                      child: Text(l10n.seniorPrompt,
                          style: const TextStyle(fontSize: 13, color: AppColors.textMuted)),
                    ),
                    TextButton(
                      onPressed: () => auth.setPrefersSeniorMode(true),
                      child: Text(l10n.enableSeniorMode, style: const TextStyle(fontSize: 13)),
                    ),
                  ],
                ),
                if (auth.prefersSeniorMode)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.check_circle, size: 16, color: AppColors.primaryLight),
                        const SizedBox(width: 6),
                        Flexible(
                          child: Text(l10n.seniorModeWillOpen,
                              style: const TextStyle(fontSize: 12, color: AppColors.primaryLight)),
                        ),
                        TextButton(
                          onPressed: () => auth.setPrefersSeniorMode(false),
                          child: Text(l10n.undo, style: const TextStyle(fontSize: 12)),
                        ),
                      ],
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
