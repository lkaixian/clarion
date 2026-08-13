// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'MediBridge';

  @override
  String get apiSettingsTooltip => 'API Settings';

  @override
  String get back => 'Back';

  @override
  String get loginSubtitle => 'Your health record, wherever you go';

  @override
  String get emailLabel => 'Email';

  @override
  String get emailOrNricLabel => 'Email or NRIC';

  @override
  String get passwordLabel => 'Password';

  @override
  String get signIn => 'Sign In';

  @override
  String get signingIn => 'Signing in…';

  @override
  String get demoLoginHint =>
      'Demo login: patient@medibridge.demo / patient123 (or NRIC 520314-01-1234 / patient123)';

  @override
  String get loginFailedGeneric =>
      'Login failed. Check your credentials or the API base URL in Settings.';

  @override
  String get seniorPrompt => 'Older adult or first-time user?';

  @override
  String get enableSeniorMode => 'Enable Senior Citizen Mode →';

  @override
  String get seniorModeWillOpen => 'Senior Mode will open after you sign in';

  @override
  String get undo => 'Undo';

  @override
  String get scanEmergencyCardButton => '🚨 Scan Emergency QR / NFC Card';

  @override
  String get scanEmergencyCardSubtitle =>
      'For first responders — no sign-in needed';

  @override
  String get orSignInDivider => 'or sign in to manage your own record';

  @override
  String get forgotPasswordButton => 'Forgot password?';

  @override
  String get forgotPasswordTitle => 'Reset Password';

  @override
  String get forgotPasswordDesc =>
      'For patients only. Enter your NRIC and date of birth exactly as they appear on your health record, then choose a new password.';

  @override
  String get forgotPasswordStep1Desc =>
      'For patients only. Enter your NRIC and, if there\'s an email on file for your account, we\'ll send it a verification code.';

  @override
  String get sendCodeButton => 'Send code';

  @override
  String get otpRequestedGenericSnack =>
      'If this NRIC has an email on file, a verification code has been sent to it.';

  @override
  String get otpCodeLabel => 'Verification code';

  @override
  String get forgotPasswordStep2Desc =>
      'Enter the 6-digit code we sent, then choose a new password.';

  @override
  String get resendCodeButton => 'Didn\'t get a code? Resend';

  @override
  String get resendCodeSentSnack =>
      'If this NRIC has an email on file, a new verification code has been sent.';

  @override
  String get useDifferentNricButton => 'Use a different NRIC';

  @override
  String get requestOtpFailedGeneric =>
      'Could not request a verification code. Check your NRIC or the API base URL in Settings.';

  @override
  String get nricLabel => 'NRIC';

  @override
  String get dateOfBirthLabel => 'Date of birth';

  @override
  String get newPasswordLabel => 'New password';

  @override
  String get confirmNewPasswordLabel => 'Confirm new password';

  @override
  String get allFieldsRequired => 'Please fill in all fields.';

  @override
  String get passwordsDoNotMatch => 'Passwords do not match.';

  @override
  String get resetPasswordButton => 'Reset Password';

  @override
  String get passwordResetSuccessSnack =>
      'Your password has been reset. Please sign in with your new password.';

  @override
  String get forgotPasswordFailedGeneric =>
      'Could not reset your password. Check your details or the API base URL in Settings.';

  @override
  String get changePasswordTitle => 'Change Password';

  @override
  String get changePasswordRequiredNotice =>
      'Your account was set up with a temporary password. For security, you must set your own password before continuing.';

  @override
  String get temporaryPasswordLabel => 'Temporary password';

  @override
  String get changePasswordButton => 'Change Password';

  @override
  String get passwordChangedSnack => 'Password changed successfully.';

  @override
  String get homeTitle => 'My Health Record';

  @override
  String get scanSomeoneElsesCardTooltip =>
      'Scan someone else\'s emergency card';

  @override
  String get noPatientRecord =>
      'No linked patient record found for this account.';

  @override
  String bloodTypeLabel(String type) {
    return 'Blood type $type';
  }

  @override
  String get signOut => 'Sign out';

  @override
  String get emergencyButton => '🚨 View / Issue Emergency QR Card';

  @override
  String get healthSummaryTitle => 'Your Health Summary';

  @override
  String get activeConditionsTitle => 'Active Conditions';

  @override
  String get noConditions => 'No conditions on record.';

  @override
  String get chronicSuffix => '(chronic)';

  @override
  String diagnosedOnLabel(String date) {
    return 'Diagnosed $date';
  }

  @override
  String get currentMedicationsTitle => 'Current Medications';

  @override
  String get noActiveMedications => 'No active medications.';

  @override
  String get unknownFacility => 'unknown facility';

  @override
  String get allergiesTitle => 'Allergies';

  @override
  String get noAllergies => 'No known allergies on record.';

  @override
  String get recentEncountersTitle => 'Recent Encounters';

  @override
  String get noEncounters => 'No encounters on record.';

  @override
  String encounterReasonLabel(String reason) {
    return 'Reason: $reason';
  }

  @override
  String encounterNotesLabel(String notes) {
    return 'Notes: $notes';
  }

  @override
  String get documentsTitle => 'Documents';

  @override
  String get noDocuments => 'No documents on record.';

  @override
  String get docTypePrescription => 'Prescription';

  @override
  String get docTypeDischargeSummary => 'Discharge Summary';

  @override
  String get docTypeLabReport => 'Lab Report';

  @override
  String get docTypeImaging => 'Imaging';

  @override
  String get docTypeOther => 'Document';

  @override
  String documentUploadedLine(String facility, String date) {
    return 'Uploaded by $facility on $date';
  }

  @override
  String get remindersButton => 'Medication & Appointment Reminders';

  @override
  String get whoViewedRecord => 'Who\'s viewed my record?';

  @override
  String get retry => 'Retry';

  @override
  String get emergencyCardTitle => 'Emergency Card';

  @override
  String get emergencyAccessCardTitle => 'Emergency Access Card';

  @override
  String get emergencyDesc =>
      'Choose what a first responder can see in an emergency. Nothing else on your record is ever exposed by this QR code — each scan is logged and you can revoke access at any time.';

  @override
  String get fieldsToShare => 'Fields to share in an emergency:';

  @override
  String get scopeAllergies => 'Allergies';

  @override
  String get scopeMedications => 'Current Medications';

  @override
  String get scopeConditions => 'Chronic Conditions';

  @override
  String get scopeBloodType => 'Blood Type';

  @override
  String get generateButton => 'Generate QR / Card';

  @override
  String get issuing => 'Issuing…';

  @override
  String get printNote =>
      'Print this card for offline / senior-citizen use. It should also show your blood type and top allergy in large text as a fallback.';

  @override
  String referenceLabel(String ref) {
    return 'Reference: $ref';
  }

  @override
  String validUntilLabel(String date) {
    return 'Valid until: $date';
  }

  @override
  String get revokeCard => 'Revoke this card';

  @override
  String get revokedBadge => 'REVOKED';

  @override
  String get couldNotRenderQr => 'Could not render QR image';

  @override
  String get cardRevokedSnack => 'Card revoked.';

  @override
  String get cardRevokeFailedSnack => 'Failed to revoke card.';

  @override
  String get cardIssueFailedSnack => 'Failed to issue card.';

  @override
  String get cardIssuedSnack => 'New emergency card issued.';

  @override
  String cardIssuedWithRevokeSnack(int count) {
    return 'New card issued. $count previous card(s) automatically revoked.';
  }

  @override
  String get onlyOneLiveCardNote =>
      'You can only have one live QR card at a time — generating a new one automatically revokes any previous one.';

  @override
  String get regenerateConfirmTitle => 'Replace your current card?';

  @override
  String regenerateConfirmBody(String ref) {
    return 'You already have an active card (ref: $ref). Generating a new one will automatically revoke it — the old QR code will stop working immediately.';
  }

  @override
  String get regenerateConfirmAction => 'Revoke old, generate new';

  @override
  String get remindersTitle => 'Reminders';

  @override
  String get medicationsSection => 'Medications';

  @override
  String get noActiveMedsRecord => 'No active medications on record.';

  @override
  String get suggestedReminder => 'Suggested reminder: twice daily, 8am / 8pm';

  @override
  String prescribedBy(String facility) {
    return 'Prescribed by $facility';
  }

  @override
  String get upcomingAppointments => 'Upcoming Appointments';

  @override
  String get noAppointments =>
      'No upcoming appointments scheduled. Your clinic will add these after each visit.';

  @override
  String get notificationsDisabledNote =>
      'Notifications are off, so reminders won\'t alert you.';

  @override
  String get notificationsPermanentlyDeniedNote =>
      'Notifications were denied before, so Android won\'t show that prompt again — open Settings to turn them on.';

  @override
  String get enableAction => 'Enable';

  @override
  String get sendTestNotification => 'Send a test notification now';

  @override
  String get testNotificationTitle => 'Test notification';

  @override
  String get testNotificationBody =>
      'If you can see this, medication and appointment reminders will work the same way.';

  @override
  String get testNotificationSentSnack =>
      'Test notification sent — check your notification shade.';

  @override
  String get testNotificationFailedSnack =>
      'Could not send a test notification. Check that notifications are enabled for this app.';

  @override
  String get addAppointmentAction => 'Add';

  @override
  String get addAppointmentTitle => 'Add appointment reminder';

  @override
  String get appointmentLabelField => 'What is this appointment for?';

  @override
  String get pickDateTime => 'Pick date & time';

  @override
  String get bookViaMySejahtera => '📅 Book an Appointment via MySejahtera';

  @override
  String get mySejahteraNote =>
      'Opens the MySejahtera app if installed, otherwise its Play Store listing.';

  @override
  String get mySejahteraLaunchFailed =>
      'Could not open MySejahtera or a fallback. Is a browser installed?';

  @override
  String get apiSettingsTitle => 'API Settings';

  @override
  String get backendUrlLabel => 'Backend API base URL';

  @override
  String get backendUrlDesc =>
      'Point the app at your backend. Handy once you start a Cloudflare tunnel (the trycloudflare.com URL changes every time the tunnel restarts) — paste the new URL here instead of rebuilding the app.';

  @override
  String get apiBaseUrlFieldLabel => 'API base URL';

  @override
  String get save => 'Save';

  @override
  String get resetToDefault => 'Reset to default';

  @override
  String currentlyActive(String url) {
    return 'Currently active: $url';
  }

  @override
  String compileTimeDefault(String url) {
    return 'Compile-time default: $url';
  }

  @override
  String get usingOverride => 'Using a runtime override.';

  @override
  String get usingDefault => 'Using the compile-time default.';

  @override
  String get emulatorNote =>
      '10.0.2.2 is the special alias the Android emulator uses to reach your host machine\'s localhost. On a physical phone, use your computer\'s LAN IP (e.g. http://192.168.1.42:8000) or a tunnel URL instead — the phone and the backend must be reachable from each other.';

  @override
  String savedSnack(String url) {
    return 'API base URL set to $url';
  }

  @override
  String get resetSnack => 'Reset to compile-time default.';

  @override
  String get seniorModeToggleLabel => 'Senior Citizen Mode';

  @override
  String get seniorModeToggleDesc =>
      'Simplified view with larger text and fewer choices';

  @override
  String get languageLabel => 'Language';

  @override
  String get auditLogTitle => 'Who\'s Viewed My Record';

  @override
  String get noAccessLogged => 'No access has been logged for your record yet.';

  @override
  String fieldsLabel(String fields) {
    return 'Fields: $fields';
  }

  @override
  String get responderScanTitle => 'Scan Emergency Card';

  @override
  String get responderScanDesc =>
      'Scan a patient\'s emergency QR code, tap their physical NFC card, or type in a printed card reference / NFC UID. No login is required — the backend enforces this by design.';

  @override
  String get cardReferenceLabel => 'Card reference';

  @override
  String get cardReferenceHint => 'e.g. from the Emergency tab';

  @override
  String get responderNameLabel => 'Responder name (optional)';

  @override
  String get responderOrgLabel => 'Responder organisation (optional)';

  @override
  String get scanButton => 'Look Up';

  @override
  String get scanning => 'Looking up…';

  @override
  String get scanModeQr => 'Scan QR';

  @override
  String get scanModeNfc => 'Tap NFC';

  @override
  String get scanModeManual => 'Type Manually';

  @override
  String get nfcUidLabel => 'NFC card UID';

  @override
  String get cameraPermissionDenied =>
      'Camera permission was denied, so the QR scanner can\'t start. Grant camera access in system settings to use it.';

  @override
  String get openAppSettings => 'Open Settings';

  @override
  String get nfcUnsupportedPlatform =>
      'NFC scanning is only supported on Android in this app.';

  @override
  String get nfcUnsupportedDevice => 'This device doesn\'t have NFC hardware.';

  @override
  String get nfcDisabled =>
      'NFC is turned off on this device. Turn it on in system settings, then come back to this screen.';

  @override
  String get nfcReadyToTap =>
      'Ready — hold the card against the back of the phone';

  @override
  String get nfcStarting => 'Starting NFC…';

  @override
  String seniorBloodType(String type) {
    return 'BLOOD TYPE: $type';
  }

  @override
  String seniorAllergicTo(String allergy) {
    return 'ALLERGIC TO: $allergy';
  }

  @override
  String get seniorEmergencyTile => '🚨\nEMERGENCY\nCARD';

  @override
  String get seniorMedsTile => '💊\nMY\nMEDICATIONS';

  @override
  String get switchToStandard => 'Switch to Standard View';

  @override
  String get signOutSenior => 'Sign Out';

  @override
  String get seniorLanguageTitle => 'Change Language';

  @override
  String get seniorEmergencyTitle => 'EMERGENCY CARD';

  @override
  String get preparingCard => 'Preparing your card…';

  @override
  String get showToResponder => 'SHOW THIS TO A\nMEDICAL RESPONDER';

  @override
  String refLabel(String ref) {
    return 'Ref: $ref';
  }

  @override
  String get getNewCard => 'Get a New Card';

  @override
  String get tryAgain => 'Try Again';

  @override
  String get seniorMedsTitle => 'MY MEDICATIONS';

  @override
  String get noMedsRecord => 'No medications on record.';

  @override
  String get takeTwiceDaily => 'Take twice daily: 8 AM and 8 PM';

  @override
  String fromFacility(String facility) {
    return 'From $facility';
  }

  @override
  String get yourClinic => 'your clinic';

  @override
  String get nfcCardSectionTitle => 'Physical NFC Card';

  @override
  String nfcCardActiveLine(String uid) {
    return 'Card $uid — active';
  }

  @override
  String nfcCardRevokedLine(String uid) {
    return 'Card $uid — revoked';
  }

  @override
  String get editProfileTitle => 'Edit Profile';

  @override
  String get readOnlyFieldsNote =>
      'Your name, date of birth, and NRIC can\'t be changed here. Contact your clinic to correct them.';

  @override
  String get fullNameLabel => 'Full name';

  @override
  String get editableProfileSectionTitle => 'Contact Details';

  @override
  String get profileEmailLabel => 'Email';

  @override
  String get profilePhoneLabel => 'Phone';

  @override
  String get emergencyContactSectionTitle => 'Emergency Contact';

  @override
  String get emergencyContactNameLabel => 'Emergency contact name';

  @override
  String get emergencyContactPhoneLabel => 'Emergency contact phone';

  @override
  String get emergencyContactRelationshipLabel => 'Relationship to you';

  @override
  String get saveProfileButton => 'Save Changes';

  @override
  String get profileUpdatedSnack => 'Your profile has been updated.';

  @override
  String get profileUpdateFailedGeneric =>
      'Could not update your profile. Please try again.';

  @override
  String get missingProfileBannerText =>
      'Your profile is missing some details — tap to complete it.';

  @override
  String get dismiss => 'Dismiss';

  @override
  String get unexpectedErrorGeneric =>
      'Something went wrong. Please try again.';
}
