import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/locale_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import 'audit_log_screen.dart';
import 'edit_profile_screen.dart';
import 'settings_screen.dart';
import 'write_offline_tag_screen.dart';

/// Same role set backend/app/routers/emergency.py::register_nfc_card
/// requires for POST /emergency/nfc/register -- writing the offline tag
/// text is a companion step to that same staff-only action.
const _kNfcRegistrationRoles = {'admin', 'records_officer', 'clinician'};

/// Profile tab: account, profile/settings/audit entries, language, the
/// staff-only tag writer, and sign out.
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  Future<void> _confirmSignOut(BuildContext context) async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(l10n.confirmSignOutTitle),
        content: Text(l10n.confirmSignOutBody),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(l10n.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(l10n.confirmSignOutAction)),
        ],
      ),
    );
    if (ok == true) await auth.logout();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    final auth = context.watch<AuthProvider>();
    final locales = context.watch<LocaleProvider>();
    final user = auth.user;
    final hasPatient = user?.patientId != null;
    final noRecord = hasPatient ? null : Text(l10n.noPatientRecord);

    Widget tile(IconData icon, String title, VoidCallback? onTap, {Widget? subtitle, Color? color}) => ListTile(
          minTileHeight: 56,
          leading: Icon(icon, color: onTap == null ? p.textFaint : (color ?? p.primary)),
          title: Text(title, style: TextStyle(color: onTap == null ? p.textMuted : (color ?? p.textPrimary))),
          subtitle: subtitle,
          trailing: color == null ? Icon(Icons.chevron_right, color: p.textMuted) : null,
          enabled: onTap != null,
          onTap: onTap,
        );

    return Scaffold(
      appBar: AppBar(title: Text(l10n.navProfile)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (user != null) ...[
            Text(
              user.fullName,
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: p.textPrimary),
            ),
            Text(user.email, style: TextStyle(fontSize: 13, color: p.textMuted)),
            const SizedBox(height: 16),
          ],
          Card(
            child: Column(
              children: [
                tile(
                  Icons.person_outline,
                  l10n.editProfileTitle,
                  hasPatient ? () => context.pushScreen(const EditProfileScreen()) : null,
                  subtitle: noRecord,
                ),
                tile(
                  Icons.visibility_outlined,
                  l10n.whoViewedRecord,
                  hasPatient ? () => context.pushScreen(const AuditLogScreen()) : null,
                  subtitle: noRecord,
                ),
                tile(Icons.settings_outlined, l10n.settingsTitle, () => context.pushScreen(const SettingsScreen())),
                if (_kNfcRegistrationRoles.contains(user?.role))
                  tile(Icons.nfc, l10n.writeOfflineTagTitle, () => context.pushScreen(const WriteOfflineTagScreen())),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(l10n.languageLabel, style: TextStyle(fontWeight: FontWeight.w700, color: p.primary)),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: kSupportedLocales.map((locale) {
                      final selected = locale.languageCode == locales.locale.languageCode;
                      return ChoiceChip(
                        label: Text(kLocaleDisplayNames[locale.languageCode] ?? locale.languageCode),
                        selected: selected,
                        onSelected: (_) => locales.setLocale(locale),
                        selectedColor: p.primary,
                        labelStyle: TextStyle(color: selected ? context.onFill : p.textBody),
                      );
                    }).toList(),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: tile(Icons.logout, l10n.signOut, () => _confirmSignOut(context), color: p.emergency),
          ),
        ],
      ),
    );
  }
}
