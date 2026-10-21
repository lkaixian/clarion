import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/family.dart';
import '../providers/auth_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/profile_switcher.dart';

String relationLabel(AppLocalizations l, String? code) => switch (code) {
      '1' => l.relChild,
      '3' => l.relMother,
      '4' => l.relFather,
      '9' => l.relGrandmother,
      '10' => l.relGrandfather,
      '12' => l.relGuardian,
      '99' => l.relOthers,
      _ => '',
    };

/// Profiles I can act for, plus who can act for me.
class FamilyScreen extends StatefulWidget {
  const FamilyScreen({super.key});

  @override
  State<FamilyScreen> createState() => _FamilyScreenState();
}

class _FamilyScreenState extends State<FamilyScreen> {
  List<FamilyProfile> _profiles = const [];
  List<Guardian> _guardians = const [];
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    try {
      final p = await api.getProfiles();
      final g = await api.getGuardians();
      if (!mounted) return;
      setState(() {
        _profiles = p;
        _guardians = g;
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _remove(Guardian g) async {
    final l10n = AppLocalizations.of(context);
    try {
      await context.read<ApiClient>().removeGuardian(g.linkId);
      await _load();
    } on ApiException catch (e) {
      if (mounted) context.snack(e.statusCode == 403 ? l10n.familyRemoveMinor : e.message);
    }
  }

  Future<void> _approve(Guardian g) async {
    try {
      await context.read<AuthProvider>().approveGuardian(g.linkId);
      await _load();
    } on ApiException catch (e) {
      if (mounted) context.snack(e.message);
    }
  }

  Future<void> _add() async {
    final added = await context.pushScreen<bool>(const AddFamilyMemberScreen());
    if (added == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    final activeId = context.watch<AuthProvider>().user?.patientId;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.familyTitle)),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const ActingBanner(),
        if (_error != null) Text(_error!, style: TextStyle(color: p.emergency)),
        for (final g in _guardians.where((g) => g.pending))
          Card(
            key: Key('guardian-pending-${g.linkId}'),
            color: p.chipBg,
            child: ListTile(
              title: Text(l10n.familyWantsToManage(g.fullName),
                  style: TextStyle(fontWeight: FontWeight.w700, color: p.primary)),
              subtitle: Row(children: [
                FilledButton(
                  key: Key('guardian-approve-${g.linkId}'),
                  onPressed: () => _approve(g),
                  child: Text(l10n.familyApprove),
                ),
                const SizedBox(width: 8),
                TextButton(
                  key: Key('guardian-decline-${g.linkId}'),
                  onPressed: () => _remove(g),
                  child: Text(l10n.familyRemove),
                ),
              ]),
            ),
          ),
        for (final f in _profiles)
          Card(
            child: ListTile(
              key: Key('family-${f.patientId}'),
              title: Text(f.fullName),
              subtitle: Text([
                if (f.pendingApproval) l10n.familyPendingApproval,
                if (f.isSelf) l10n.familyYou else relationLabel(l10n, f.relationCode),
                if (f.age != null) l10n.familyAge(f.age!),
              ].where((e) => e.isNotEmpty).join(' · ')),
              trailing: f.patientId == activeId
                  ? Icon(Icons.check_circle, color: p.primary)
                  : TextButton(
                      onPressed: f.pendingApproval ? null : () => switchToProfile(context, f.patientId),
                      child: Text(l10n.familySwitch),
                    ),
            ),
          ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          key: const Key('family-add'),
          onPressed: _add,
          icon: const Icon(Icons.person_add_alt),
          label: Text(l10n.familyAddTitle),
        ),
        const SizedBox(height: 24),
        Text(l10n.familyGuardiansTitle,
            style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16, color: p.primary)),
        const SizedBox(height: 8),
        if (_guardians.where((g) => !g.pending).isEmpty) EmptyText(l10n.familyNoGuardians),
        for (final g in _guardians.where((g) => !g.pending))
          Card(
            child: ListTile(
              title: Text(g.fullName),
              subtitle: Text(relationLabel(l10n, g.relationCode)),
              trailing: TextButton(
                key: Key('guardian-remove-${g.linkId}'),
                onPressed: () => _remove(g),
                child: Text(l10n.familyRemove),
              ),
            ),
          ),
      ]),
    );
  }
}

/// "Add a child or parent" form. Pops `true` after a successful add.
class AddFamilyMemberScreen extends StatefulWidget {
  const AddFamilyMemberScreen({super.key});

  @override
  State<AddFamilyMemberScreen> createState() => _AddFamilyMemberScreenState();
}

class _AddFamilyMemberScreenState extends State<AddFamilyMemberScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  DateTime? _dob;
  String? _relation;
  bool _busy = false;
  bool _dobMissing = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _pickDob() async {
    final now = DateTime.now();
    final d = await showDatePicker(
      context: context,
      initialDate: _dob ?? DateTime(now.year - 10),
      firstDate: DateTime(1900),
      lastDate: now,
    );
    if (d != null) {
      setState(() {
        _dob = d;
        _dobMissing = false;
      });
    }
  }

  Future<void> _submit() async {
    final api = context.read<ApiClient>();
    final okForm = _form.currentState!.validate();
    setState(() => _dobMissing = _dob == null);
    if (!okForm || _dob == null || _busy) return;
    setState(() => _busy = true);
    try {
      await api.addProfile(
        fullName: _name.text.trim(),
        dateOfBirth: DateFormat('yyyy-MM-dd').format(_dob!),
        relationCode: _relation!,
      );
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      if (mounted) context.snack(e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.familyAddTitle)),
      body: Form(
        key: _form,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          TextFormField(
            key: const Key('add-name'),
            controller: _name,
            decoration: InputDecoration(labelText: l10n.familyName),
            validator: (v) => (v == null || v.trim().isEmpty) ? l10n.familyNameRequired : null,
          ),
          const SizedBox(height: 12),
          ListTile(
            key: const Key('add-dob'),
            contentPadding: EdgeInsets.zero,
            title: Text(l10n.familyDob),
            subtitle: Text(
              _dob == null ? (_dobMissing ? l10n.familyDobRequired : '') : DateFormat('d MMM yyyy').format(_dob!),
              style: _dobMissing ? TextStyle(color: context.palette.emergency) : null,
            ),
            trailing: const Icon(Icons.calendar_today),
            onTap: _pickDob,
          ),
          DropdownButtonFormField<String>(
            key: const Key('add-relation'),
            initialValue: _relation,
            decoration: InputDecoration(labelText: l10n.familyRelation),
            items: [
              for (final c in kRelationCodes) DropdownMenuItem(value: c, child: Text(relationLabel(l10n, c))),
            ],
            onChanged: (v) => setState(() => _relation = v),
            validator: (v) => v == null ? l10n.familyRelationRequired : null,
          ),
          const SizedBox(height: 12),
          Text(l10n.familyIcHint, style: TextStyle(fontSize: 13, color: context.palette.textMuted)),
          const SizedBox(height: 20),
          FilledButton(
            key: const Key('add-submit'),
            onPressed: _busy ? null : _submit,
            child: Text(l10n.familyAddAction),
          ),
        ]),
      ),
    );
  }
}
