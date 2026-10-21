import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/family.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../providers/queue_provider.dart';
import '../providers/reminders_provider.dart';
import '../screens/family_screen.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import 'common.dart';

/// Drops everything cached for the previous profile.
void clearCachedPatientData(BuildContext context) {
  context.read<PatientProvider>().clear();
  context.read<QueueProvider>().clear();
  context.read<RemindersProvider>().clearServerAppointments();
}

/// Switches the active profile, clears cached data and returns to the patient
/// home. Shows the server message on failure. Returns true on success.
Future<bool> switchToProfile(BuildContext context, String patientId) async {
  final auth = context.read<AuthProvider>();
  final navigator = Navigator.of(context);
  final messenger = context;
  final error = await auth.switchProfile(patientId);
  if (error != null) {
    if (messenger.mounted) messenger.snack(error);
    return false;
  }
  if (!messenger.mounted) return true;
  clearCachedPatientData(messenger);
  navigator.popUntil((r) => r.isFirst);
  // The shell is rebuilt (keyed by patient id) and reloads on its own.
  return true;
}

/// App bar action: shows the active profile name, opens the profile sheet.
/// Patient role only.
class ProfileSwitcherAction extends StatelessWidget {
  const ProfileSwitcherAction({super.key});

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    if (user == null || user.role != 'patient') return const SizedBox.shrink();
    return TextButton.icon(
      key: const Key('profile-switcher'),
      onPressed: () => showProfileSheet(context),
      icon: const Icon(Icons.swap_horiz),
      label: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 140),
        child: Text(user.fullName, overflow: TextOverflow.ellipsis, maxLines: 1),
      ),
    );
  }
}

/// "Acting for NAME" banner with a back button; empty when not acting.
class ActingBanner extends StatelessWidget {
  const ActingBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthProvider>().user;
    final home = user?.homePatientId;
    if (user == null || !user.actingFor || home == null) return const SizedBox.shrink();
    final l10n = AppLocalizations.of(context);
    return Material(
      color: context.palette.chipBg,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        child: Row(children: [
          Expanded(
            child: Text(l10n.familyActingFor(user.fullName),
                style: TextStyle(fontWeight: FontWeight.w700, color: context.palette.primary)),
          ),
          TextButton(
            key: const Key('acting-back'),
            onPressed: () => switchToProfile(context, home),
            child: Text(l10n.familyBackToMine),
          ),
        ]),
      ),
    );
  }
}

Future<void> showProfileSheet(BuildContext context) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _ProfileSheet(),
    );

class _ProfileSheet extends StatefulWidget {
  const _ProfileSheet();

  @override
  State<_ProfileSheet> createState() => _ProfileSheetState();
}

class _ProfileSheetState extends State<_ProfileSheet> {
  List<FamilyProfile>? _profiles;
  String? _error;

  @override
  void initState() {
    super.initState();
    context.read<ApiClient>().getProfiles().then((p) {
      if (mounted) setState(() => _profiles = p);
    }).catchError((Object e) {
      if (mounted) setState(() => _error = e is ApiException ? e.message : '$e');
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final user = context.watch<AuthProvider>().user;
    return SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const ActingBanner(),
        if (_error != null) Padding(padding: const EdgeInsets.all(16), child: Text(_error!)),
        if (_profiles == null && _error == null)
          const Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator()),
        for (final p in _profiles ?? const <FamilyProfile>[])
          ListTile(
            key: Key('profile-${p.patientId}'),
            leading: Icon(p.patientId == user?.patientId ? Icons.check_circle : Icons.person_outline),
            title: Text(p.fullName),
            subtitle: p.isSelf ? Text(l10n.familyYou) : null,
            onTap: p.patientId == user?.patientId ? null : () => switchToProfile(context, p.patientId),
          ),
        ListTile(
          key: const Key('profile-add'),
          leading: const Icon(Icons.person_add_alt),
          title: Text(l10n.familyAdd),
          onTap: () {
            final nav = Navigator.of(context);
            nav.pop();
            nav.push(MaterialPageRoute<void>(builder: (_) => const AddFamilyMemberScreen()));
          },
        ),
      ]),
    );
  }
}
