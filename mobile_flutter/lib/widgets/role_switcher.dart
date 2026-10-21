import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../theme/app_theme.dart';
import 'common.dart';
import 'profile_switcher.dart';

String roleLabel(AppLocalizations l10n, String role) {
  switch (role) {
    case 'admin':
      return l10n.roleAdmin;
    case 'clinician':
      return l10n.roleClinician;
    case 'records_officer':
      return l10n.roleRecordsOfficer;
    case 'receptionist':
      return l10n.roleReceptionist;
    case 'pharmacist':
      return l10n.rolePharmacist;
    case 'emergency_responder':
      return l10n.roleEmergencyResponder;
    case 'patient':
      return l10n.rolePatient;
    default:
      return role;
  }
}

/// App bar action for logins that hold several roles: shows the active role,
/// opens a sheet to switch. Renders nothing for a single-role account.
class RoleSwitcherAction extends StatelessWidget {
  const RoleSwitcherAction({super.key});

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    if (user == null || user.roles.length < 2) return const SizedBox.shrink();
    final l10n = AppLocalizations.of(context);
    final label = l10n.roleSwitchCurrent(roleLabel(l10n, user.role));
    return Semantics(
      button: true,
      label: '${l10n.roleSwitchTitle}. $label',
      excludeSemantics: true,
      child: TextButton.icon(
        key: const Key('role-switcher'),
        style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
        onPressed: () => showModalBottomSheet<void>(context: context, builder: (_) => const _RoleSheet()),
        icon: const Icon(Icons.badge_outlined),
        label: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 140),
          child: Text(roleLabel(l10n, user.role), overflow: TextOverflow.ellipsis, maxLines: 1),
        ),
      ),
    );
  }
}

class _RoleSheet extends StatelessWidget {
  const _RoleSheet();

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final user = context.watch<AuthProvider>().user;
    return SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text(l10n.roleSwitchTitle, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
        ),
        for (final r in user?.roles ?? const <String>[])
          ListTile(
            key: Key('role-$r'),
            minTileHeight: 48,
            leading: Icon(r == user?.role ? Icons.check_circle : Icons.circle_outlined),
            title: Text(roleLabel(l10n, r)),
            selected: r == user?.role,
            onTap: r == user?.role ? null : () => switchToRole(context, r),
          ),
      ]),
    );
  }
}

/// Switches the signed-in login to [role], asking for the password (and
/// authenticator code) when moving up to a staff role. Shared by the role
/// sheet and the home role chips.
Future<void> switchToRole(BuildContext context, String role) async {
  final auth = context.read<AuthProvider>();
  final navigator = Navigator.of(context);
  final host = context;
  var result = await auth.switchRole(role);
  if (!host.mounted) return;
  if (result.reauth) {
    final done = await showDialog<bool>(
      context: host,
      builder: (_) => _ReauthDialog(
        needsCode: result.needsCode,
        submit: (pw, code) => auth.switchRole(role, password: pw, code: code),
      ),
    );
    if (done != true || !host.mounted) return;
    result = const RoleSwitchResult();
  }
  if (result.error != null) {
    host.snack(result.error!);
    return;
  }
  clearCachedPatientData(host);
  navigator.popUntil((r) => r.isFirst); // the shell is rebuilt, keyed by role
}

/// Colour family + icon for one role. [accent] is the outline/text colour on
/// the surface AND the solid fill of the active chip; [onSolid] is the text on
/// that fill. Every pair is >= 4.5:1 in its theme (checked in role_switcher_test).
class RoleStyle {
  const RoleStyle(this.accent, this.onSolid, this.icon);
  final Color accent;
  final Color onSolid;
  final IconData icon;
}

const _lightOn = Colors.white;
const _darkOn = Color(0xFF0F172A);

/// [tier] is the login's responder tier: a paramedic gets a deeper orange.
RoleStyle roleStyleFor(Brightness b, String role, {String? tier}) {
  final dark = b == Brightness.dark;
  final on = dark ? _darkOn : _lightOn;
  Color c(int light, int darkC) => Color(dark ? darkC : light);
  switch (role) {
    case 'patient':
      return RoleStyle(c(0xFF0F766E, 0xFF2DD4BF), on, Icons.person_outline);
    case 'clinician':
      return RoleStyle(c(0xFF15803D, 0xFF4ADE80), on, Icons.medical_services_outlined);
    case 'emergency_responder':
      return tier == 'paramedic'
          ? RoleStyle(c(0xFF9A3412, 0xFFF97316), on, Icons.local_hospital_outlined)
          : RoleStyle(c(0xFFC2410C, 0xFFFB923C), on, Icons.emergency_outlined);
    case 'pharmacist':
      return RoleStyle(c(0xFF7E22CE, 0xFFC084FC), on, Icons.medication_outlined);
    case 'receptionist':
      return RoleStyle(c(0xFF4338CA, 0xFF818CF8), on, Icons.support_agent_outlined);
    case 'records_officer':
      return RoleStyle(c(0xFF92400E, 0xFFF59E0B), on, Icons.folder_open_outlined);
    case 'admin':
      return RoleStyle(c(0xFF475569, 0xFF94A3B8), on, Icons.admin_panel_settings_outlined);
    default:
      return RoleStyle(c(0xFF475569, 0xFF94A3B8), on, Icons.badge_outlined);
  }
}

/// Role name for a chip: a paramedic responder says so.
String roleChipLabel(AppLocalizations l10n, String role, String? tier) =>
    role == 'emergency_responder' && tier == 'paramedic'
        ? '${l10n.roleEmergencyResponder} · ${l10n.scanTierParamedic}'
        : roleLabel(l10n, role);

/// One chip per role the login holds, shown under the user's name. The active
/// role is solid with a check; the others are outlined and switch on tap.
/// Renders nothing for a single-role account.
class RoleChips extends StatelessWidget {
  const RoleChips({super.key});

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    if (user == null || user.roles.length < 2) return const SizedBox.shrink();
    final l10n = AppLocalizations.of(context);
    final brightness = Theme.of(context).brightness;
    final surface = context.palette.surface;
    return Semantics(
      container: true,
      label: l10n.roleChipsGroupLabel,
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final r in user.roles)
            _RoleChip(
              role: r,
              label: roleChipLabel(l10n, r, user.responderTier),
              style: roleStyleFor(brightness, r, tier: user.responderTier),
              surface: surface,
              active: r == user.role,
            ),
        ],
      ),
    );
  }
}

class _RoleChip extends StatelessWidget {
  const _RoleChip({
    required this.role,
    required this.label,
    required this.style,
    required this.surface,
    required this.active,
  });
  final String role;
  final String label;
  final RoleStyle style;
  final Color surface;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final fg = active ? style.onSolid : style.accent;
    return Semantics(
      button: !active,
      selected: active,
      label: active ? l10n.roleSwitchCurrent(label) : l10n.roleChipSwitchTo(label),
      excludeSemantics: true,
      child: Material(
        color: active ? style.accent : surface,
        shape: StadiumBorder(side: BorderSide(color: style.accent, width: 2)),
        child: InkWell(
          key: Key('role-chip-$role'),
          customBorder: const StadiumBorder(),
          onTap: active ? null : () => switchToRole(context, role),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(style.icon, size: 20, color: fg),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(label, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: fg)),
                  ),
                  if (active) ...[
                    const SizedBox(width: 6),
                    Icon(Icons.check, size: 20, color: fg),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Asks for the password (and authenticator code if needed) to move up to a
/// staff role. Stays open with the server's message on a wrong answer; pops
/// true once the switch succeeded. The password lives only in the controller.
class _ReauthDialog extends StatefulWidget {
  const _ReauthDialog({required this.needsCode, required this.submit});
  final bool needsCode;
  final Future<RoleSwitchResult> Function(String password, String? code) submit;

  @override
  State<_ReauthDialog> createState() => _ReauthDialogState();
}

class _ReauthDialogState extends State<_ReauthDialog> {
  final _pw = TextEditingController();
  final _code = TextEditingController();
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _pw.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _go() async {
    if (_pw.text.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final r = await widget.submit(_pw.text, widget.needsCode ? _code.text.trim() : null);
    if (!mounted) return;
    if (r.ok) {
      Navigator.of(context).pop(true);
    } else {
      setState(() {
        _busy = false;
        _error = r.error ?? AppLocalizations.of(context).roleReauthRetry;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.roleReauthTitle),
      content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(l10n.roleReauthBody),
        const SizedBox(height: 12),
        TextField(
          key: const Key('reauth-password'),
          controller: _pw,
          obscureText: true,
          autofocus: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(labelText: l10n.rolePasswordLabel),
          onSubmitted: (_) => widget.needsCode ? null : _go(),
        ),
        if (widget.needsCode)
          TextField(
            key: const Key('reauth-code'),
            controller: _code,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: l10n.roleCodeLabel),
            onSubmitted: (_) => _go(),
          ),
        Semantics(
          liveRegion: true,
          child: _error == null
              ? const SizedBox.shrink()
              : Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
        ),
      ]),
      actions: [
        TextButton(
          style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(l10n.cancel),
        ),
        FilledButton(
          key: const Key('reauth-confirm'),
          style: FilledButton.styleFrom(minimumSize: const Size(48, 48)),
          onPressed: _busy ? null : _go,
          child: Text(l10n.roleReauthConfirm),
        ),
      ],
    );
  }
}
