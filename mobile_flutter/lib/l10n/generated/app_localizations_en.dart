// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'CLARION';

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
      'Demo login: patient@clarion.demo / patient123 (or NRIC 520314-01-1234 / patient123)';

  @override
  String get loginFailedGeneric =>
      'Login failed. Check your credentials or the API base URL in Settings.';

  @override
  String get sessionExpiredSnackbar =>
      'You were signed out — please log in again.';

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
  String get selfRegisterLinkPrompt => 'First time here?';

  @override
  String get selfRegisterLinkAction => 'Register';

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
  String get selfRegisterTitle => 'Create Your Account';

  @override
  String get selfRegisterDetailsStepDesc =>
      'For patients who don\'t yet have a CLARION login. Enter your details exactly as they appear on your NRIC — we\'ll verify them against your hospital record.';

  @override
  String get selfRegisterContinueButton => 'Continue';

  @override
  String get selfRegisterStartFailedGeneric =>
      'Could not verify your details. Check what you entered or the API base URL in Settings.';

  @override
  String get selfRegisterOtpStepDesc =>
      'Enter the 6-digit verification code we emailed you.';

  @override
  String get selfRegisterVerifyOtpButton => 'Verify Code';

  @override
  String get selfRegisterVerifyOtpFailedGeneric =>
      'Could not verify that code. Check the code or the API base URL in Settings.';

  @override
  String get selfRegisterPhotosStepTitle => 'Verify Your Identity';

  @override
  String get selfRegisterPhotosStepDesc =>
      'Now take clear photos of the front and back of your physical NRIC card. These are used only to confirm your identity against your hospital record — a member of our staff, not this app, checks the match.';

  @override
  String get selfRegisterFrontPhotoLabel => 'Front of NRIC';

  @override
  String get selfRegisterBackPhotoLabel => 'Back of NRIC';

  @override
  String get selfRegisterTakePhotoButton => 'Take Photo';

  @override
  String get selfRegisterRetakePhotoButton => 'Retake';

  @override
  String selfRegisterAttemptsRemaining(int count) {
    return '$count of 5 attempts remaining';
  }

  @override
  String get selfRegisterSubmitPhotosButton => 'Submit Photos';

  @override
  String get selfRegisterPhotosRequiredNote =>
      'Please take both photos before submitting.';

  @override
  String get selfRegisterPhotosFailedGeneric =>
      'Could not verify your photos. Check the API base URL in Settings and try again.';

  @override
  String get selfRegisterCameraFailed =>
      'Could not open the camera. Check camera permission in system settings and try again.';

  @override
  String get selfRegisterPasswordStepDesc =>
      'Almost done. Choose a password for your new account (at least 8 characters).';

  @override
  String get selfRegisterCompleteButton => 'Create Account';

  @override
  String get selfRegisterCompleteFailedGeneric =>
      'Could not create your account. Check the API base URL in Settings and try again.';

  @override
  String get selfRegisterSuccessSnack =>
      'Account created — welcome to CLARION!';

  @override
  String get selfRegisterManualRequiredTitle => 'Visit a Registration Counter';

  @override
  String get selfRegisterManualRequiredBody =>
      'We couldn\'t verify your NRIC photos after several attempts. For your security, please visit a registration counter in person, bringing your physical NRIC — our staff will help set up your account there.';

  @override
  String get selfRegisterManualRequiredBackButton => 'Back to Sign In';

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
  String get quickActionsSectionTitle => 'Quick Actions';

  @override
  String get healthRecordSectionTitle => 'Your Medical Record';

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
  String encounterDepartmentLabel(String department) {
    return 'Department: $department';
  }

  @override
  String encounterVitalsLabel(String vitals) {
    return 'Vitals: $vitals';
  }

  @override
  String get downloadVisitSummary => 'Download / share visit summary (PDF)';

  @override
  String get visitSummaryUnavailable =>
      'Visit summary isn\'t available for this visit yet.';

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
  String get bookAppointmentButton => 'Book Appointment';

  @override
  String get whoViewedRecord => 'Who\'s viewed my record?';

  @override
  String get retry => 'Retry';

  @override
  String showMoreAction(int count) {
    return 'Show $count more';
  }

  @override
  String get showLessAction => 'Show less';

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
  String get announcementsSectionTitle => 'Announcements';

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
  String get clinicAppointmentsSection => 'From Your Clinic';

  @override
  String get noClinicAppointments =>
      'No upcoming appointments from your clinic on file yet.';

  @override
  String get clinicAppointmentBadge => 'Set by your clinic';

  @override
  String fastingRequiredNote(int hours) {
    return '⚠ Fasting required: ${hours}h before your appointment';
  }

  @override
  String get fastingRequiredNoteUnspecified =>
      '⚠ Fasting is required before your appointment — check with your clinic for how long.';

  @override
  String appointmentReasonLabel(String reason) {
    return 'Reason: $reason';
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
  String get themeLabel => 'Theme';

  @override
  String get themeModeLight => 'Light';

  @override
  String get themeModeDark => 'Dark';

  @override
  String get themeModeSystem => 'System default';

  @override
  String get auditLogTitle => 'Who\'s Viewed My Record';

  @override
  String get noAccessLogged => 'No access has been logged for your record yet.';

  @override
  String fieldsLabel(String fields) {
    return 'Fields: $fields';
  }

  @override
  String get auditActorSystemFallback => 'system';

  @override
  String get auditActorEmergencyResponderUnverified =>
      'emergency responder — self-reported, unverified';

  @override
  String get auditLogLegendIntro =>
      'Color and icon show how sensitive each access looks:';

  @override
  String get auditSeverityRoutine => 'Routine';

  @override
  String get auditSeverityAttention => 'Emergency access';

  @override
  String get auditSeverityCritical => 'Failed attempt';

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
  String get scanResultFoundTitle => 'Patient Found';

  @override
  String scanResultAgeValue(String age) {
    return 'Age: $age';
  }

  @override
  String get scanResultBloodTypeUnknown => 'Not on file';

  @override
  String scanResultOmittedMedications(int count) {
    return '+$count more medications on file, not shown here — not flagged as emergency-critical.';
  }

  @override
  String scanResultOmittedConditions(int count) {
    return '+$count more conditions on file, not shown here — not flagged as emergency-critical.';
  }

  @override
  String scanResultOmittedAllergies(int count) {
    return '+$count more allergies on file, not shown here — not flagged as emergency-critical.';
  }

  @override
  String get scanResultOfflineBanner =>
      'OFFLINE — read directly from the card, no network. May be outdated; name and age aren\'t stored on the card.';

  @override
  String get scanResultOfflinePlaceholderName => 'Card holder (offline read)';

  @override
  String get nfcBasicTagWarning =>
      'This tag type (NTAG213/215/216) works, but has no tamper-proof read counter: offline reads of it can\'t be checked for missing entries. Use an NTAG 424 DNA where accountability matters.';

  @override
  String get scanResultOfflineSignIn =>
      'No connection, and this tag is protected. Sign in with a CLARION staff or responder account to read it offline, or use the QR code / online lookup.';

  @override
  String get scanResultOfflineKeyMissing =>
      'No connection, and this device doesn\'t have the key for this tag. Connect once while signed in to download it, or use the QR code / online lookup.';

  @override
  String get scanResultOfflineExpired =>
      'This tag\'s validity has lapsed and it can\'t be read offline. Use the QR code or online lookup, and have the card re-issued.';

  @override
  String get scanResultOfflineDamaged =>
      'This tag could not be verified (damaged, altered, or not a genuine CLARION tag). Do not rely on it - use the QR code or online lookup.';

  @override
  String get writeOfflineTagTooltip => 'Write Offline Tag (staff only)';

  @override
  String get writeOfflineTagTitle => 'Write Offline Tag';

  @override
  String get writeOfflineTagDesc =>
      'Paste the text shown after registering an NFC card on the web console, then tap the SAME physical card to write it directly onto the tag. Once written, that card\'s critical info can be read with zero network — by this app or any standard NFC reader.';

  @override
  String get writeOfflineTagTextLabel => 'Offline tag text';

  @override
  String get writeOfflineTagButton => 'Tap card to write';

  @override
  String get writeOfflineTagWriting =>
      'Hold the card against the back of the phone…';

  @override
  String get writeOfflineTagSuccess =>
      'Written. This card now carries its critical info offline.';

  @override
  String get writeOfflineTagNotNdef =>
      'This tag doesn\'t support NDEF — try a different physical card.';

  @override
  String get writeOfflineTagNotWritable =>
      'This tag is read-only (locked) and can\'t be written to.';

  @override
  String get writeOfflineTagTooLarge =>
      'This text is too large for this tag\'s memory. Re-register with fewer fields selected, or use a higher-capacity tag.';

  @override
  String get writeOfflineTagWriteFailed =>
      'Writing to the tag failed. Try tapping again, holding the card steady.';

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

  @override
  String get queueStatusButton => 'Queue Status';

  @override
  String get queueStatusTitle => 'Your Queue Status';

  @override
  String yourNumberLabel(String number) {
    return 'Your number: $number';
  }

  @override
  String nowServingLabel(String number) {
    return 'Now serving: $number';
  }

  @override
  String get nowServingNoneYet => 'No number called yet';

  @override
  String peopleAheadLabel(String count) {
    return '$count people ahead of you';
  }

  @override
  String get queueTicketDetailsTitle => 'Ticket Details';

  @override
  String get queueStatusLabel => 'Status';

  @override
  String get queueFacilityLabel => 'Facility';

  @override
  String get queueDepartmentLabel => 'Department';

  @override
  String get queueReasonLabel => 'Reason';

  @override
  String get queueStatusWaiting => 'Waiting';

  @override
  String get queueStatusCalled => 'Called';

  @override
  String get queueStatusDone => 'Done';

  @override
  String get queueStatusCancelled => 'Cancelled';

  @override
  String get noActiveQueueTicketTitle => 'No active queue ticket';

  @override
  String get noActiveQueueTicketDesc =>
      'Check in at reception to get a queue number.';

  @override
  String get bookAppointmentTitle => 'Book Appointment';

  @override
  String get bookAppointmentFacilityLabel => 'Facility';

  @override
  String get bookAppointmentOtherFacility => 'Other (type manually)';

  @override
  String get bookAppointmentFacilityManualHint => 'Facility name';

  @override
  String get bookAppointmentUseFacility => 'Use this facility';

  @override
  String get bookAppointmentDepartmentLabel => 'Department';

  @override
  String get bookAppointmentAnyDepartment => 'Any department';

  @override
  String get bookAppointmentClinicianLabel => 'Doctor';

  @override
  String get bookAppointmentAnyClinician => 'Any doctor';

  @override
  String get bookAppointmentPickDate => 'Pick a date';

  @override
  String get bookAppointmentNoSlots =>
      'No open slots on this date — try another day.';

  @override
  String get bookAppointmentSuccess => 'Appointment booked.';

  @override
  String get bookAppointmentSlotTaken =>
      'That slot was just taken — pick another.';

  @override
  String get bookAppointmentGenericError =>
      'Could not complete the booking. Please try again.';

  @override
  String get scanCheckinButton => 'Scan to Check In';

  @override
  String get scanCheckinTitle => 'Scan to Check In';

  @override
  String get scanCheckinDesc =>
      'Scan the QR code at the reception self-check-in station, or type in its code below. No staff assistance needed — you\'ll get a queue number right away.';

  @override
  String get checkinReasonLabel => 'Reason for visit (optional)';

  @override
  String get checkinReasonHint => 'e.g. follow-up, blood test';

  @override
  String get stationCodeLabel => 'Station code';

  @override
  String get stationCodeHint =>
      'e.g. from the reception counter\'s printed code';

  @override
  String get checkinSubmitButton => 'Check In';

  @override
  String get checkinSubmitting => 'Checking in…';

  @override
  String get requestRescheduleButton => 'Request Reschedule';

  @override
  String get rescheduleDialogTitle => 'Request a Reschedule';

  @override
  String get rescheduleDialogDesc =>
      'Let your clinic know you can\'t make this appointment. They\'ll review your request and follow up with you.';

  @override
  String get rescheduleReasonScheduleConflict => 'Schedule conflict';

  @override
  String get rescheduleReasonUnwell => 'Unwell / can\'t travel';

  @override
  String get rescheduleReasonTransport => 'Transport issue';

  @override
  String get rescheduleReasonOther => 'Other';

  @override
  String get rescheduleOtherReasonLabel => 'Please describe your reason';

  @override
  String get rescheduleOtherReasonRequired => 'Please describe your reason.';

  @override
  String get rescheduleSubmitButton => 'Submit Request';

  @override
  String get rescheduleSubmitting => 'Submitting…';

  @override
  String get reschedulePendingNote =>
      'Reschedule requested — waiting for the clinic to respond';

  @override
  String get rescheduleAcceptedNote => 'Your reschedule request was accepted.';

  @override
  String get rescheduleRejectedNote => 'Your reschedule request was declined.';

  @override
  String rescheduleClinicianNoteLabel(String note) {
    return 'Clinic note: $note';
  }

  @override
  String previouslyScheduledLabel(String date) {
    return 'Previously: $date';
  }

  @override
  String get seniorMenuTooltip => 'Menu';

  @override
  String get seniorMenuTitle => 'Menu';

  @override
  String get seniorThemeToggleTooltip => 'Switch colour theme';

  @override
  String get confirmSwitchToStandardTitle => 'Switch to Standard View?';

  @override
  String get confirmSwitchToStandardBody =>
      'You\'ll leave Senior Mode and see the regular app. You can turn Senior Mode back on anytime from Settings.';

  @override
  String get confirmSwitchToStandardAction => 'Yes, Switch';

  @override
  String get confirmSignOutTitle => 'Sign Out?';

  @override
  String get confirmSignOutBody =>
      'You will need to sign in again to see your health record.';

  @override
  String get confirmSignOutAction => 'Yes, Sign Out';
}
