import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';
import 'nric_scan_screen.dart';
import 'self_register_manual_required_screen.dart';
import '../widgets/common.dart';
import '../widgets/password_rules.dart';

enum _Step { details, otp, pending }

/// Self-service registration for a patient who doesn't yet have a
/// CLARION login — today, only staff can create one, in person, via
/// the web console; this is the self-service alternative. A single
/// screen with internal step state (mirrors `ForgotPasswordScreen`'s
/// pattern exactly, rather than four separate routes):
///
/// 1. **Details** — NRIC, full name, email ->
///    `POST /auth/self-register/start`.
/// 2. **OTP** — the 6-digit code emailed in step 1 ->
///    `POST /auth/self-register/verify-otp`.
/// 3. **Photos** — front + back photos of the physical NRIC, captured
///    with `image_picker`'s camera source (no live preview needed, unlike
///    the QR scanner) -> `POST /auth/self-register/verify-photos`. **All
///    OCR/identity cross-checking happens server-side** — this app is
///    purely capture-and-upload for these two photos, never a
///    client-reported "verified" flag, since identity proofing can't
///    trust the client. Up to 5 attempts; the 5th failure is terminal
///    (see [SelfRegisterManualRequiredScreen]) and this screen does not
///    offer a 6th retry even though the button would otherwise look
///    identical.
/// 4. **Password** — sets the new account's password ->
///    `POST /auth/self-register/complete`, which returns the SAME shape
///    as `POST /auth/login`. On success this is treated exactly like a
///    successful login (`AuthProvider.completeWithLoginResponse`): the
///    user is routed straight into the app, not bounced back to
///    LoginScreen to sign in again with the password they just chose.
class SelfRegisterScreen extends StatefulWidget {
  const SelfRegisterScreen({super.key});

  @override
  State<SelfRegisterScreen> createState() => _SelfRegisterScreenState();
}

class _SelfRegisterScreenState extends State<SelfRegisterScreen> {
  final _nricController = TextEditingController();
  final _fullNameController = TextEditingController();
  final _emailController = TextEditingController();
  final _otpController = TextEditingController();
  final _newPasswordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  _Step _step = _Step.details;
  XFile? _frontImage;
  XFile? _backImage;
  int? _photoAttemptsRemaining;
  bool _obscureNew = true;
  bool _obscureConfirm = true;
  bool _loading = false;
  bool _photoCheck = false;

  @override
  void initState() {
    super.initState();
    // A failed lookup keeps the simpler no-photo flow; the server enforces the real rule.
    context.read<ApiClient>().selfRegisterPhotoCheck().then((on) {
      if (mounted) setState(() => _photoCheck = on);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _nricController.dispose();
    _fullNameController.dispose();
    _emailController.dispose();
    _otpController.dispose();
    _newPasswordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  void _showSnack(String message) {
    if (!mounted) return;
    context.snack(message);
  }

  Future<void> _startRegistration() async {
    final l10n = AppLocalizations.of(context);
    final nric = _nricController.text.trim();
    final fullName = _fullNameController.text.trim();
    final email = _emailController.text.trim();

    if (nric.isEmpty || fullName.isEmpty || email.isEmpty) {
      _showSnack(l10n.allFieldsRequired);
      return;
    }

    setState(() => _loading = true);
    try {
      final api = context.read<ApiClient>();
      await api.claimStart(nationalId: nric, fullName: fullName, email: email);
      if (!mounted) return;
      setState(() => _step = _Step.otp);
    } on ApiException catch (e) {
      _showSnack(e.message);
    } catch (_) {
      _showSnack(l10n.selfRegisterStartFailedGeneric);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// An approved result is already a login; a pending one waits for verification.
  Future<void> _handleClaimResult(Map<String, dynamic> data) async {
    if (data['status'] == 'approved') {
      final done = AppLocalizations.of(context).selfRegisterSuccessSnack;
      await context.read<AuthProvider>().completeWithLoginResponse(data['session'] as Map<String, dynamic>);
      _showSnack(done);
      return;
    }
    setState(() => _step = _Step.pending);
  }

  Future<void> _verifyOtp() async {
    final l10n = AppLocalizations.of(context);
    final otpCode = _otpController.text.trim();
    final newPassword = _newPasswordController.text;
    if (otpCode.isEmpty || newPassword.isEmpty || _confirmPasswordController.text.isEmpty) {
      _showSnack(l10n.allFieldsRequired);
      return;
    }
    if (newPassword != _confirmPasswordController.text) {
      _showSnack(l10n.passwordsDoNotMatch);
      return;
    }
    if (!passwordMeetsRules(newPassword)) {
      _showSnack(l10n.passwordRulesNotMet);
      return;
    }

    setState(() => _loading = true);
    try {
      final data = await context.read<ApiClient>().claimVerifyOtp(
            nationalId: _nricController.text.trim(),
            email: _emailController.text.trim(),
            otpCode: otpCode,
            password: newPassword,
          );
      if (!mounted) return;
      await _handleClaimResult(data);
    } on ApiException catch (e) {
      _showSnack(e.message);
    } catch (_) {
      _showSnack(l10n.selfRegisterVerifyOtpFailedGeneric);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// Live on-device NRIC check (nothing is uploaded): the scan screen returns
  /// the details the user confirmed, which only pre-fill the fields. The
  /// server still verifies everything.
  Future<void> _scanCard() async {
    final found = await Navigator.of(context).push<Map<String, String>>(
      MaterialPageRoute(builder: (_) => const NricScanScreen()),
    );
    if (found == null || !mounted) return;
    if (found['nric']!.isNotEmpty) _nricController.text = found['nric']!;
    if (found['name']!.isNotEmpty) _fullNameController.text = found['name']!;
  }

  Future<void> _takePhoto({required bool isFront}) async {
    final l10n = AppLocalizations.of(context);
    try {
      final file = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 85);
      if (file == null || !mounted) return;
      setState(() {
        if (isFront) {
          _frontImage = file;
        } else {
          _backImage = file;
        }
      });
    } catch (_) {
      _showSnack(l10n.selfRegisterCameraFailed);
    }
  }

  Future<void> _submitPhotos() async {
    final l10n = AppLocalizations.of(context);
    final front = _frontImage;
    final back = _backImage;
    if (front == null || back == null) {
      _showSnack(l10n.selfRegisterPhotosRequiredNote);
      return;
    }

    setState(() => _loading = true);
    try {
      final api = context.read<ApiClient>();
      final data = await api.claimVerifyPhotos(
        nationalId: _nricController.text.trim(),
        email: _emailController.text.trim(),
        frontImagePath: front.path,
        backImagePath: back.path,
      );
      if (!mounted) return;
      await _handleClaimResult(data);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 403) {
        // Terminal: the backend has flagged the 5th failed attempt. Do
        // NOT offer a further retry — replace this whole flow with the
        // dedicated full-screen message, keeping LoginScreen underneath.
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const SelfRegisterManualRequiredScreen()),
        );
        return;
      }
      // 400 with attempts remaining: surface the detail, update the
      // remaining-attempts count, and require both photos to be retaken
      // rather than silently resubmitting the same (rejected) images.
      final remaining = e.data?['photo_attempts_remaining'];
      setState(() {
        if (remaining is int) _photoAttemptsRemaining = remaining;
        _frontImage = null;
        _backImage = null;
      });
      _showSnack(e.message);
    } catch (_) {
      _showSnack(l10n.selfRegisterPhotosFailedGeneric);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      backgroundColor: context.palette.background,
      appBar: AppBar(title: Text(l10n.selfRegisterTitle)),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: switch (_step) {
            _Step.details => _buildDetailsStep(l10n),
            _Step.otp => _buildOtpStep(l10n),
            _Step.pending => _buildPendingStep(l10n),
          },
        ),
      ),
    );
  }

  Widget _buildDetailsStep(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.selfRegisterDetailsStepDesc,
          style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          onPressed: _loading ? null : _scanCard,
          icon: const Icon(Icons.document_scanner_outlined),
          label: Text(l10n.selfRegisterScanButton),
          style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
        ),
        const SizedBox(height: 4),
        Text(
          l10n.selfRegisterScanPrivacy,
          style: TextStyle(fontSize: 12, color: context.palette.textMuted),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _nricController,
          keyboardType: TextInputType.text,
          autocorrect: false,
          textCapitalization: TextCapitalization.characters,
          // dashes and spaces are dropped as the NRIC is typed
          inputFormatters: [
            FilteringTextInputFormatter.allow(RegExp('[0-9A-Za-z]')),
            TextInputFormatter.withFunction((o, n) => n.copyWith(text: n.text.toUpperCase())),
          ],
          decoration: InputDecoration(labelText: l10n.nricLabel, hintText: l10n.nricLabel),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _fullNameController,
          textCapitalization: TextCapitalization.characters,
          inputFormatters: [TextInputFormatter.withFunction((o, n) => n.copyWith(text: n.text.toUpperCase()))],
          decoration: InputDecoration(labelText: l10n.fullNameLabel, hintText: l10n.fullNameLabel),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _emailController,
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          decoration: InputDecoration(labelText: l10n.emailLabel, hintText: l10n.emailLabel),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _loading ? null : _startRegistration,
            child: _loading
                ? const ButtonSpinner()
                : Text(l10n.selfRegisterContinueButton),
          ),
        ),
      ],
    );
  }

  Widget _buildOtpStep(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.selfRegisterOtpStepDesc,
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
        Text(l10n.selfRegisterPasswordStepDesc, style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4)),
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
            onPressed: _loading ? null : _verifyOtp,
            child: _loading
                ? const ButtonSpinner()
                : Text(l10n.selfRegisterVerifyOtpButton),
          ),
        ),
      ],
    );
  }

  Widget _buildPendingStep(AppLocalizations l10n) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(l10n.selfRegisterPendingDesc, style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4)),
        if (_photoCheck) ...[
          const SizedBox(height: 20),
          _buildPhotosStep(l10n),
        ],
      ],
    );
  }

  Widget _buildPhotosStep(AppLocalizations l10n) {
    final remaining = _photoAttemptsRemaining;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          l10n.selfRegisterPhotosStepTitle,
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: context.palette.textPrimary),
        ),
        const SizedBox(height: 8),
        Text(
          l10n.selfRegisterPhotosStepDesc,
          style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
        ),
        if (remaining != null) ...[
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: context.palette.attentionBg,
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text(
              l10n.selfRegisterAttemptsRemaining(remaining),
              style: TextStyle(fontSize: 12, color: context.palette.attention, fontWeight: FontWeight.w600),
            ),
          ),
        ],
        const SizedBox(height: 20),
        _PhotoCaptureTile(
          label: l10n.selfRegisterFrontPhotoLabel,
          image: _frontImage,
          takeLabel: l10n.selfRegisterTakePhotoButton,
          retakeLabel: l10n.selfRegisterRetakePhotoButton,
          onCapture: () => _takePhoto(isFront: true),
        ),
        const SizedBox(height: 16),
        _PhotoCaptureTile(
          label: l10n.selfRegisterBackPhotoLabel,
          image: _backImage,
          takeLabel: l10n.selfRegisterTakePhotoButton,
          retakeLabel: l10n.selfRegisterRetakePhotoButton,
          onCapture: () => _takePhoto(isFront: false),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _loading ? null : _submitPhotos,
            child: _loading
                ? const ButtonSpinner()
                : Text(l10n.selfRegisterSubmitPhotosButton),
          ),
        ),
      ],
    );
  }
}

/// One "take a photo of the front/back of your NRIC" tile: shows a
/// thumbnail preview once captured (with a Retake option) or an empty
/// placeholder with a Take Photo button before that.
class _PhotoCaptureTile extends StatelessWidget {
  const _PhotoCaptureTile({
    required this.label,
    required this.image,
    required this.takeLabel,
    required this.retakeLabel,
    required this.onCapture,
  });

  final String label;
  final XFile? image;
  final String takeLabel;
  final String retakeLabel;
  final VoidCallback onCapture;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: context.palette.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: context.palette.border),
      ),
      child: Row(
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: image == null
                ? Container(
                    width: 64,
                    height: 64,
                    color: context.palette.chipBg,
                    child: Icon(Icons.badge_outlined, color: context.palette.textFaint),
                  )
                : Image.file(File(image!.path), width: 64, height: 64, fit: BoxFit.cover),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              label,
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: context.palette.textPrimary),
            ),
          ),
          OutlinedButton(
            onPressed: onCapture,
            child: Text(image == null ? takeLabel : retakeLabel),
          ),
        ],
      ),
    );
  }
}
