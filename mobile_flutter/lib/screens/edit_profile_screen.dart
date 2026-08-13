import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/patient.dart';
import '../providers/auth_provider.dart';
import '../providers/patient_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

/// Self-service contact/profile editor for a patient's own record —
/// reachable from HomeScreen's app bar and from SettingsScreen. Only
/// meaningful for patient-role accounts (staff/clinician accounts don't
/// have a Patient record of their own); entry points are gated on
/// `auth.user?.role == 'patient'` by the caller.
///
/// Full name, date of birth, and NRIC are shown read-only — those are
/// immutable via self-service (`PATCH /patients/{id}/profile` doesn't
/// accept them; contact your clinic to correct them). Email, phone, and
/// emergency contact details are editable and saved via
/// PatientProvider.updateProfile.
class EditProfileScreen extends StatefulWidget {
  const EditProfileScreen({super.key});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  final _emailController = TextEditingController();
  final _phoneController = TextEditingController();
  final _emergencyNameController = TextEditingController();
  final _emergencyPhoneController = TextEditingController();
  final _emergencyRelationshipController = TextEditingController();
  bool _prefilled = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  void _load() {
    final auth = context.read<AuthProvider>();
    final patientState = context.read<PatientProvider>();
    final patientId = auth.user?.patientId;
    if (patientId != null && patientState.patient == null) {
      patientState.loadRecord(patientId);
    } else {
      _prefill(patientState.patient);
    }
  }

  void _prefill(Patient? patient) {
    if (_prefilled || patient == null) return;
    _prefilled = true;
    _emailController.text = patient.email ?? '';
    _phoneController.text = patient.phone ?? '';
    _emergencyNameController.text = patient.emergencyContactName ?? '';
    _emergencyPhoneController.text = patient.emergencyContactPhone ?? '';
    _emergencyRelationshipController.text = patient.emergencyContactRelationship ?? '';
  }

  @override
  void dispose() {
    _emailController.dispose();
    _phoneController.dispose();
    _emergencyNameController.dispose();
    _emergencyPhoneController.dispose();
    _emergencyRelationshipController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final l10n = AppLocalizations.of(context);
    final auth = context.read<AuthProvider>();
    final patientState = context.read<PatientProvider>();
    final patientId = auth.user?.patientId;
    if (patientId == null) return;

    final ok = await patientState.updateProfile(
      patientId: patientId,
      email: _emailController.text.trim(),
      phone: _phoneController.text.trim(),
      emergencyContactName: _emergencyNameController.text.trim(),
      emergencyContactPhone: _emergencyPhoneController.text.trim(),
      emergencyContactRelationship: _emergencyRelationshipController.text.trim(),
    );
    if (!mounted) return;
    if (ok) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(l10n.profileUpdatedSnack)));
      // Best-effort refresh so AuthProvider.missingProfileFields (and the
      // dismissible Home/SeniorHome banner it drives) reflects the edit
      // without requiring a fresh login.
      await auth.refreshUser();
      if (!mounted) return;
      Navigator.of(context).pop();
    } else {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(patientState.profileUpdateError ?? l10n.profileUpdateFailedGeneric)));
    }
  }

  String _formatDob(String iso) {
    final parsed = DateTime.tryParse(iso);
    if (parsed == null) return iso.isEmpty ? '—' : iso;
    return DateFormat('d MMM yyyy').format(parsed);
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final patientState = context.watch<PatientProvider>();
    final patient = patientState.patient;
    _prefill(patient);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(title: Text(l10n.editProfileTitle)),
      body: SafeArea(
        child: Builder(builder: (context) {
          if (patient == null) {
            if (patientState.isLoadingRecord) return const LoadingView();
            return Padding(
              padding: const EdgeInsets.all(24),
              child: Center(child: Text(l10n.noPatientRecord)),
            );
          }
          return SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l10n.readOnlyFieldsNote,
                  style: const TextStyle(fontSize: 12, color: AppColors.textMuted, height: 1.4),
                ),
                const SizedBox(height: 16),
                _ReadOnlyField(label: l10n.fullNameLabel, value: patient.fullName),
                const SizedBox(height: 12),
                _ReadOnlyField(label: l10n.dateOfBirthLabel, value: _formatDob(patient.dateOfBirth)),
                const SizedBox(height: 12),
                _ReadOnlyField(label: l10n.nricLabel, value: patient.nationalId ?? '—'),
                const SizedBox(height: 24),
                Text(l10n.editableProfileSectionTitle,
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
                const SizedBox(height: 12),
                TextField(
                  controller: _emailController,
                  keyboardType: TextInputType.emailAddress,
                  autocorrect: false,
                  decoration: InputDecoration(labelText: l10n.profileEmailLabel, hintText: l10n.profileEmailLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _phoneController,
                  keyboardType: TextInputType.phone,
                  decoration: InputDecoration(labelText: l10n.profilePhoneLabel, hintText: l10n.profilePhoneLabel),
                ),
                const SizedBox(height: 20),
                Text(l10n.emergencyContactSectionTitle,
                    style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: AppColors.textPrimary)),
                const SizedBox(height: 12),
                TextField(
                  controller: _emergencyNameController,
                  decoration: InputDecoration(
                      labelText: l10n.emergencyContactNameLabel, hintText: l10n.emergencyContactNameLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _emergencyPhoneController,
                  keyboardType: TextInputType.phone,
                  decoration: InputDecoration(
                      labelText: l10n.emergencyContactPhoneLabel, hintText: l10n.emergencyContactPhoneLabel),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _emergencyRelationshipController,
                  decoration: InputDecoration(
                      labelText: l10n.emergencyContactRelationshipLabel,
                      hintText: l10n.emergencyContactRelationshipLabel),
                ),
                const SizedBox(height: 24),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: patientState.isUpdatingProfile ? null : _save,
                    child: patientState.isUpdatingProfile
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                          )
                        : Text(l10n.saveProfileButton),
                  ),
                ),
              ],
            ),
          );
        }),
      ),
    );
  }
}

class _ReadOnlyField extends StatelessWidget {
  const _ReadOnlyField({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      decoration: BoxDecoration(
        color: AppColors.chipBg,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(fontSize: 11, color: AppColors.textMuted)),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 15, color: AppColors.textFaint, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
