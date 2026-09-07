import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_ms.dart';
import 'app_localizations_ta.dart';
import 'app_localizations_zh.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('ms'),
    Locale('ta'),
    Locale('zh'),
  ];

  /// App name, shown on the login screen and app title.
  ///
  /// In en, this message translates to:
  /// **'CLARION'**
  String get appTitle;

  /// No description provided for @apiSettingsTooltip.
  ///
  /// In en, this message translates to:
  /// **'API Settings'**
  String get apiSettingsTooltip;

  /// No description provided for @back.
  ///
  /// In en, this message translates to:
  /// **'Back'**
  String get back;

  /// No description provided for @loginSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Your health record, wherever you go'**
  String get loginSubtitle;

  /// No description provided for @emailLabel.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get emailLabel;

  /// No description provided for @emailOrNricLabel.
  ///
  /// In en, this message translates to:
  /// **'Email or NRIC'**
  String get emailOrNricLabel;

  /// No description provided for @passwordLabel.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get passwordLabel;

  /// No description provided for @signIn.
  ///
  /// In en, this message translates to:
  /// **'Sign In'**
  String get signIn;

  /// No description provided for @signingIn.
  ///
  /// In en, this message translates to:
  /// **'Signing in…'**
  String get signingIn;

  /// No description provided for @demoLoginHint.
  ///
  /// In en, this message translates to:
  /// **'Demo login: patient@clarion.demo / patient123 (or NRIC 520314-01-1234 / patient123)'**
  String get demoLoginHint;

  /// No description provided for @loginFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Login failed. Check your credentials or the API base URL in Settings.'**
  String get loginFailedGeneric;

  /// Shown once on the login screen after an involuntary sign-out (e.g. a token revoked by a password change elsewhere), not after a deliberate Sign Out.
  ///
  /// In en, this message translates to:
  /// **'You were signed out — please log in again.'**
  String get sessionExpiredSnackbar;

  /// No description provided for @seniorPrompt.
  ///
  /// In en, this message translates to:
  /// **'Older adult or first-time user?'**
  String get seniorPrompt;

  /// No description provided for @enableSeniorMode.
  ///
  /// In en, this message translates to:
  /// **'Enable Senior Citizen Mode →'**
  String get enableSeniorMode;

  /// No description provided for @seniorModeWillOpen.
  ///
  /// In en, this message translates to:
  /// **'Senior Mode will open after you sign in'**
  String get seniorModeWillOpen;

  /// No description provided for @undo.
  ///
  /// In en, this message translates to:
  /// **'Undo'**
  String get undo;

  /// No description provided for @scanEmergencyCardButton.
  ///
  /// In en, this message translates to:
  /// **'🚨 Scan Emergency QR / NFC Card'**
  String get scanEmergencyCardButton;

  /// No description provided for @scanEmergencyCardSubtitle.
  ///
  /// In en, this message translates to:
  /// **'For first responders — no sign-in needed'**
  String get scanEmergencyCardSubtitle;

  /// No description provided for @orSignInDivider.
  ///
  /// In en, this message translates to:
  /// **'or sign in to manage your own record'**
  String get orSignInDivider;

  /// No description provided for @forgotPasswordButton.
  ///
  /// In en, this message translates to:
  /// **'Forgot password?'**
  String get forgotPasswordButton;

  /// Precedes the Register link on the Login screen, for patients who don't yet have an account.
  ///
  /// In en, this message translates to:
  /// **'First time here?'**
  String get selfRegisterLinkPrompt;

  /// No description provided for @selfRegisterLinkAction.
  ///
  /// In en, this message translates to:
  /// **'Register'**
  String get selfRegisterLinkAction;

  /// No description provided for @forgotPasswordTitle.
  ///
  /// In en, this message translates to:
  /// **'Reset Password'**
  String get forgotPasswordTitle;

  /// No description provided for @forgotPasswordDesc.
  ///
  /// In en, this message translates to:
  /// **'For patients only. Enter your NRIC and date of birth exactly as they appear on your health record, then choose a new password.'**
  String get forgotPasswordDesc;

  /// No description provided for @forgotPasswordStep1Desc.
  ///
  /// In en, this message translates to:
  /// **'For patients only. Enter your NRIC and, if there\'s an email on file for your account, we\'ll send it a verification code.'**
  String get forgotPasswordStep1Desc;

  /// No description provided for @sendCodeButton.
  ///
  /// In en, this message translates to:
  /// **'Send code'**
  String get sendCodeButton;

  /// No description provided for @otpRequestedGenericSnack.
  ///
  /// In en, this message translates to:
  /// **'If this NRIC has an email on file, a verification code has been sent to it.'**
  String get otpRequestedGenericSnack;

  /// No description provided for @otpCodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Verification code'**
  String get otpCodeLabel;

  /// No description provided for @forgotPasswordStep2Desc.
  ///
  /// In en, this message translates to:
  /// **'Enter the 6-digit code we sent, then choose a new password.'**
  String get forgotPasswordStep2Desc;

  /// No description provided for @resendCodeButton.
  ///
  /// In en, this message translates to:
  /// **'Didn\'t get a code? Resend'**
  String get resendCodeButton;

  /// No description provided for @resendCodeSentSnack.
  ///
  /// In en, this message translates to:
  /// **'If this NRIC has an email on file, a new verification code has been sent.'**
  String get resendCodeSentSnack;

  /// No description provided for @useDifferentNricButton.
  ///
  /// In en, this message translates to:
  /// **'Use a different NRIC'**
  String get useDifferentNricButton;

  /// No description provided for @requestOtpFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not request a verification code. Check your NRIC or the API base URL in Settings.'**
  String get requestOtpFailedGeneric;

  /// No description provided for @nricLabel.
  ///
  /// In en, this message translates to:
  /// **'NRIC'**
  String get nricLabel;

  /// No description provided for @dateOfBirthLabel.
  ///
  /// In en, this message translates to:
  /// **'Date of birth'**
  String get dateOfBirthLabel;

  /// No description provided for @newPasswordLabel.
  ///
  /// In en, this message translates to:
  /// **'New password'**
  String get newPasswordLabel;

  /// No description provided for @confirmNewPasswordLabel.
  ///
  /// In en, this message translates to:
  /// **'Confirm new password'**
  String get confirmNewPasswordLabel;

  /// No description provided for @allFieldsRequired.
  ///
  /// In en, this message translates to:
  /// **'Please fill in all fields.'**
  String get allFieldsRequired;

  /// No description provided for @passwordsDoNotMatch.
  ///
  /// In en, this message translates to:
  /// **'Passwords do not match.'**
  String get passwordsDoNotMatch;

  /// No description provided for @resetPasswordButton.
  ///
  /// In en, this message translates to:
  /// **'Reset Password'**
  String get resetPasswordButton;

  /// No description provided for @passwordResetSuccessSnack.
  ///
  /// In en, this message translates to:
  /// **'Your password has been reset. Please sign in with your new password.'**
  String get passwordResetSuccessSnack;

  /// No description provided for @forgotPasswordFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not reset your password. Check your details or the API base URL in Settings.'**
  String get forgotPasswordFailedGeneric;

  /// No description provided for @selfRegisterTitle.
  ///
  /// In en, this message translates to:
  /// **'Create Your Account'**
  String get selfRegisterTitle;

  /// No description provided for @selfRegisterDetailsStepDesc.
  ///
  /// In en, this message translates to:
  /// **'For patients who don\'t yet have a CLARION login. Enter your details exactly as they appear on your NRIC — we\'ll verify them against your hospital record.'**
  String get selfRegisterDetailsStepDesc;

  /// No description provided for @selfRegisterContinueButton.
  ///
  /// In en, this message translates to:
  /// **'Continue'**
  String get selfRegisterContinueButton;

  /// No description provided for @selfRegisterStartFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not verify your details. Check what you entered or the API base URL in Settings.'**
  String get selfRegisterStartFailedGeneric;

  /// No description provided for @selfRegisterOtpStepDesc.
  ///
  /// In en, this message translates to:
  /// **'Enter the 6-digit verification code we emailed you.'**
  String get selfRegisterOtpStepDesc;

  /// No description provided for @selfRegisterVerifyOtpButton.
  ///
  /// In en, this message translates to:
  /// **'Verify Code'**
  String get selfRegisterVerifyOtpButton;

  /// No description provided for @selfRegisterVerifyOtpFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not verify that code. Check the code or the API base URL in Settings.'**
  String get selfRegisterVerifyOtpFailedGeneric;

  /// No description provided for @selfRegisterPhotosStepTitle.
  ///
  /// In en, this message translates to:
  /// **'Verify Your Identity'**
  String get selfRegisterPhotosStepTitle;

  /// No description provided for @selfRegisterPhotosStepDesc.
  ///
  /// In en, this message translates to:
  /// **'Now take clear photos of the front and back of your physical NRIC card. These are used only to confirm your identity against your hospital record — a member of our staff, not this app, checks the match.'**
  String get selfRegisterPhotosStepDesc;

  /// No description provided for @selfRegisterFrontPhotoLabel.
  ///
  /// In en, this message translates to:
  /// **'Front of NRIC'**
  String get selfRegisterFrontPhotoLabel;

  /// No description provided for @selfRegisterBackPhotoLabel.
  ///
  /// In en, this message translates to:
  /// **'Back of NRIC'**
  String get selfRegisterBackPhotoLabel;

  /// No description provided for @selfRegisterTakePhotoButton.
  ///
  /// In en, this message translates to:
  /// **'Take Photo'**
  String get selfRegisterTakePhotoButton;

  /// No description provided for @selfRegisterRetakePhotoButton.
  ///
  /// In en, this message translates to:
  /// **'Retake'**
  String get selfRegisterRetakePhotoButton;

  /// Shown once the backend has reported a photo-verification attempt count, so the user knows how many tries remain before the terminal manual-registration state.
  ///
  /// In en, this message translates to:
  /// **'{count} of 5 attempts remaining'**
  String selfRegisterAttemptsRemaining(int count);

  /// No description provided for @selfRegisterSubmitPhotosButton.
  ///
  /// In en, this message translates to:
  /// **'Submit Photos'**
  String get selfRegisterSubmitPhotosButton;

  /// No description provided for @selfRegisterPhotosRequiredNote.
  ///
  /// In en, this message translates to:
  /// **'Please take both photos before submitting.'**
  String get selfRegisterPhotosRequiredNote;

  /// No description provided for @selfRegisterPhotosFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not verify your photos. Check the API base URL in Settings and try again.'**
  String get selfRegisterPhotosFailedGeneric;

  /// No description provided for @selfRegisterCameraFailed.
  ///
  /// In en, this message translates to:
  /// **'Could not open the camera. Check camera permission in system settings and try again.'**
  String get selfRegisterCameraFailed;

  /// No description provided for @selfRegisterPasswordStepDesc.
  ///
  /// In en, this message translates to:
  /// **'Almost done. Choose a password for your new account (at least 8 characters).'**
  String get selfRegisterPasswordStepDesc;

  /// No description provided for @selfRegisterCompleteButton.
  ///
  /// In en, this message translates to:
  /// **'Create Account'**
  String get selfRegisterCompleteButton;

  /// No description provided for @selfRegisterCompleteFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not create your account. Check the API base URL in Settings and try again.'**
  String get selfRegisterCompleteFailedGeneric;

  /// No description provided for @selfRegisterSuccessSnack.
  ///
  /// In en, this message translates to:
  /// **'Account created — welcome to CLARION!'**
  String get selfRegisterSuccessSnack;

  /// No description provided for @selfRegisterManualRequiredTitle.
  ///
  /// In en, this message translates to:
  /// **'Visit a Registration Counter'**
  String get selfRegisterManualRequiredTitle;

  /// No description provided for @selfRegisterManualRequiredBody.
  ///
  /// In en, this message translates to:
  /// **'We couldn\'t verify your NRIC photos after several attempts. For your security, please visit a registration counter in person, bringing your physical NRIC — our staff will help set up your account there.'**
  String get selfRegisterManualRequiredBody;

  /// No description provided for @selfRegisterManualRequiredBackButton.
  ///
  /// In en, this message translates to:
  /// **'Back to Sign In'**
  String get selfRegisterManualRequiredBackButton;

  /// No description provided for @changePasswordTitle.
  ///
  /// In en, this message translates to:
  /// **'Change Password'**
  String get changePasswordTitle;

  /// No description provided for @changePasswordRequiredNotice.
  ///
  /// In en, this message translates to:
  /// **'Your account was set up with a temporary password. For security, you must set your own password before continuing.'**
  String get changePasswordRequiredNotice;

  /// No description provided for @temporaryPasswordLabel.
  ///
  /// In en, this message translates to:
  /// **'Temporary password'**
  String get temporaryPasswordLabel;

  /// No description provided for @changePasswordButton.
  ///
  /// In en, this message translates to:
  /// **'Change Password'**
  String get changePasswordButton;

  /// No description provided for @passwordChangedSnack.
  ///
  /// In en, this message translates to:
  /// **'Password changed successfully.'**
  String get passwordChangedSnack;

  /// No description provided for @homeTitle.
  ///
  /// In en, this message translates to:
  /// **'My Health Record'**
  String get homeTitle;

  /// No description provided for @quickActionsSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Quick Actions'**
  String get quickActionsSectionTitle;

  /// No description provided for @healthRecordSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Your Medical Record'**
  String get healthRecordSectionTitle;

  /// No description provided for @scanSomeoneElsesCardTooltip.
  ///
  /// In en, this message translates to:
  /// **'Scan someone else\'s emergency card'**
  String get scanSomeoneElsesCardTooltip;

  /// No description provided for @noPatientRecord.
  ///
  /// In en, this message translates to:
  /// **'No linked patient record found for this account.'**
  String get noPatientRecord;

  /// No description provided for @bloodTypeLabel.
  ///
  /// In en, this message translates to:
  /// **'Blood type {type}'**
  String bloodTypeLabel(String type);

  /// No description provided for @signOut.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get signOut;

  /// No description provided for @emergencyButton.
  ///
  /// In en, this message translates to:
  /// **'🚨 View / Issue Emergency QR Card'**
  String get emergencyButton;

  /// No description provided for @healthSummaryTitle.
  ///
  /// In en, this message translates to:
  /// **'Your Health Summary'**
  String get healthSummaryTitle;

  /// No description provided for @activeConditionsTitle.
  ///
  /// In en, this message translates to:
  /// **'Active Conditions'**
  String get activeConditionsTitle;

  /// No description provided for @noConditions.
  ///
  /// In en, this message translates to:
  /// **'No conditions on record.'**
  String get noConditions;

  /// No description provided for @chronicSuffix.
  ///
  /// In en, this message translates to:
  /// **'(chronic)'**
  String get chronicSuffix;

  /// No description provided for @diagnosedOnLabel.
  ///
  /// In en, this message translates to:
  /// **'Diagnosed {date}'**
  String diagnosedOnLabel(String date);

  /// No description provided for @currentMedicationsTitle.
  ///
  /// In en, this message translates to:
  /// **'Current Medications'**
  String get currentMedicationsTitle;

  /// No description provided for @noActiveMedications.
  ///
  /// In en, this message translates to:
  /// **'No active medications.'**
  String get noActiveMedications;

  /// No description provided for @unknownFacility.
  ///
  /// In en, this message translates to:
  /// **'unknown facility'**
  String get unknownFacility;

  /// No description provided for @allergiesTitle.
  ///
  /// In en, this message translates to:
  /// **'Allergies'**
  String get allergiesTitle;

  /// No description provided for @noAllergies.
  ///
  /// In en, this message translates to:
  /// **'No known allergies on record.'**
  String get noAllergies;

  /// No description provided for @recentEncountersTitle.
  ///
  /// In en, this message translates to:
  /// **'Recent Encounters'**
  String get recentEncountersTitle;

  /// No description provided for @noEncounters.
  ///
  /// In en, this message translates to:
  /// **'No encounters on record.'**
  String get noEncounters;

  /// No description provided for @encounterReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'Reason: {reason}'**
  String encounterReasonLabel(String reason);

  /// No description provided for @encounterNotesLabel.
  ///
  /// In en, this message translates to:
  /// **'Notes: {notes}'**
  String encounterNotesLabel(String notes);

  /// No description provided for @documentsTitle.
  ///
  /// In en, this message translates to:
  /// **'Documents'**
  String get documentsTitle;

  /// No description provided for @noDocuments.
  ///
  /// In en, this message translates to:
  /// **'No documents on record.'**
  String get noDocuments;

  /// No description provided for @docTypePrescription.
  ///
  /// In en, this message translates to:
  /// **'Prescription'**
  String get docTypePrescription;

  /// No description provided for @docTypeDischargeSummary.
  ///
  /// In en, this message translates to:
  /// **'Discharge Summary'**
  String get docTypeDischargeSummary;

  /// No description provided for @docTypeLabReport.
  ///
  /// In en, this message translates to:
  /// **'Lab Report'**
  String get docTypeLabReport;

  /// No description provided for @docTypeImaging.
  ///
  /// In en, this message translates to:
  /// **'Imaging'**
  String get docTypeImaging;

  /// No description provided for @docTypeOther.
  ///
  /// In en, this message translates to:
  /// **'Document'**
  String get docTypeOther;

  /// No description provided for @documentUploadedLine.
  ///
  /// In en, this message translates to:
  /// **'Uploaded by {facility} on {date}'**
  String documentUploadedLine(String facility, String date);

  /// No description provided for @remindersButton.
  ///
  /// In en, this message translates to:
  /// **'Medication & Appointment Reminders'**
  String get remindersButton;

  /// No description provided for @whoViewedRecord.
  ///
  /// In en, this message translates to:
  /// **'Who\'s viewed my record?'**
  String get whoViewedRecord;

  /// No description provided for @retry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retry;

  /// Expands a truncated list section (conditions, medications, allergies, encounters, documents, appointments) to show every remaining item.
  ///
  /// In en, this message translates to:
  /// **'Show {count} more'**
  String showMoreAction(int count);

  /// Collapses a list section back to its default top-N view after showMoreAction was tapped.
  ///
  /// In en, this message translates to:
  /// **'Show less'**
  String get showLessAction;

  /// No description provided for @emergencyCardTitle.
  ///
  /// In en, this message translates to:
  /// **'Emergency Card'**
  String get emergencyCardTitle;

  /// No description provided for @emergencyAccessCardTitle.
  ///
  /// In en, this message translates to:
  /// **'Emergency Access Card'**
  String get emergencyAccessCardTitle;

  /// No description provided for @emergencyDesc.
  ///
  /// In en, this message translates to:
  /// **'Choose what a first responder can see in an emergency. Nothing else on your record is ever exposed by this QR code — each scan is logged and you can revoke access at any time.'**
  String get emergencyDesc;

  /// No description provided for @fieldsToShare.
  ///
  /// In en, this message translates to:
  /// **'Fields to share in an emergency:'**
  String get fieldsToShare;

  /// No description provided for @scopeAllergies.
  ///
  /// In en, this message translates to:
  /// **'Allergies'**
  String get scopeAllergies;

  /// No description provided for @scopeMedications.
  ///
  /// In en, this message translates to:
  /// **'Current Medications'**
  String get scopeMedications;

  /// No description provided for @scopeConditions.
  ///
  /// In en, this message translates to:
  /// **'Chronic Conditions'**
  String get scopeConditions;

  /// No description provided for @scopeBloodType.
  ///
  /// In en, this message translates to:
  /// **'Blood Type'**
  String get scopeBloodType;

  /// No description provided for @generateButton.
  ///
  /// In en, this message translates to:
  /// **'Generate QR / Card'**
  String get generateButton;

  /// No description provided for @issuing.
  ///
  /// In en, this message translates to:
  /// **'Issuing…'**
  String get issuing;

  /// No description provided for @printNote.
  ///
  /// In en, this message translates to:
  /// **'Print this card for offline / senior-citizen use. It should also show your blood type and top allergy in large text as a fallback.'**
  String get printNote;

  /// No description provided for @referenceLabel.
  ///
  /// In en, this message translates to:
  /// **'Reference: {ref}'**
  String referenceLabel(String ref);

  /// No description provided for @validUntilLabel.
  ///
  /// In en, this message translates to:
  /// **'Valid until: {date}'**
  String validUntilLabel(String date);

  /// No description provided for @revokeCard.
  ///
  /// In en, this message translates to:
  /// **'Revoke this card'**
  String get revokeCard;

  /// No description provided for @revokedBadge.
  ///
  /// In en, this message translates to:
  /// **'REVOKED'**
  String get revokedBadge;

  /// No description provided for @couldNotRenderQr.
  ///
  /// In en, this message translates to:
  /// **'Could not render QR image'**
  String get couldNotRenderQr;

  /// No description provided for @cardRevokedSnack.
  ///
  /// In en, this message translates to:
  /// **'Card revoked.'**
  String get cardRevokedSnack;

  /// No description provided for @cardRevokeFailedSnack.
  ///
  /// In en, this message translates to:
  /// **'Failed to revoke card.'**
  String get cardRevokeFailedSnack;

  /// No description provided for @cardIssueFailedSnack.
  ///
  /// In en, this message translates to:
  /// **'Failed to issue card.'**
  String get cardIssueFailedSnack;

  /// No description provided for @cardIssuedSnack.
  ///
  /// In en, this message translates to:
  /// **'New emergency card issued.'**
  String get cardIssuedSnack;

  /// No description provided for @cardIssuedWithRevokeSnack.
  ///
  /// In en, this message translates to:
  /// **'New card issued. {count} previous card(s) automatically revoked.'**
  String cardIssuedWithRevokeSnack(int count);

  /// No description provided for @onlyOneLiveCardNote.
  ///
  /// In en, this message translates to:
  /// **'You can only have one live QR card at a time — generating a new one automatically revokes any previous one.'**
  String get onlyOneLiveCardNote;

  /// No description provided for @regenerateConfirmTitle.
  ///
  /// In en, this message translates to:
  /// **'Replace your current card?'**
  String get regenerateConfirmTitle;

  /// No description provided for @regenerateConfirmBody.
  ///
  /// In en, this message translates to:
  /// **'You already have an active card (ref: {ref}). Generating a new one will automatically revoke it — the old QR code will stop working immediately.'**
  String regenerateConfirmBody(String ref);

  /// No description provided for @regenerateConfirmAction.
  ///
  /// In en, this message translates to:
  /// **'Revoke old, generate new'**
  String get regenerateConfirmAction;

  /// No description provided for @remindersTitle.
  ///
  /// In en, this message translates to:
  /// **'Reminders'**
  String get remindersTitle;

  /// No description provided for @medicationsSection.
  ///
  /// In en, this message translates to:
  /// **'Medications'**
  String get medicationsSection;

  /// No description provided for @noActiveMedsRecord.
  ///
  /// In en, this message translates to:
  /// **'No active medications on record.'**
  String get noActiveMedsRecord;

  /// No description provided for @suggestedReminder.
  ///
  /// In en, this message translates to:
  /// **'Suggested reminder: twice daily, 8am / 8pm'**
  String get suggestedReminder;

  /// No description provided for @prescribedBy.
  ///
  /// In en, this message translates to:
  /// **'Prescribed by {facility}'**
  String prescribedBy(String facility);

  /// No description provided for @clinicAppointmentsSection.
  ///
  /// In en, this message translates to:
  /// **'From Your Clinic'**
  String get clinicAppointmentsSection;

  /// No description provided for @noClinicAppointments.
  ///
  /// In en, this message translates to:
  /// **'No upcoming appointments from your clinic on file yet.'**
  String get noClinicAppointments;

  /// No description provided for @clinicAppointmentBadge.
  ///
  /// In en, this message translates to:
  /// **'Set by your clinic'**
  String get clinicAppointmentBadge;

  /// No description provided for @fastingRequiredNote.
  ///
  /// In en, this message translates to:
  /// **'⚠ Fasting required: {hours}h before your appointment'**
  String fastingRequiredNote(int hours);

  /// No description provided for @fastingRequiredNoteUnspecified.
  ///
  /// In en, this message translates to:
  /// **'⚠ Fasting is required before your appointment — check with your clinic for how long.'**
  String get fastingRequiredNoteUnspecified;

  /// No description provided for @appointmentReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'Reason: {reason}'**
  String appointmentReasonLabel(String reason);

  /// No description provided for @upcomingAppointments.
  ///
  /// In en, this message translates to:
  /// **'Upcoming Appointments'**
  String get upcomingAppointments;

  /// No description provided for @noAppointments.
  ///
  /// In en, this message translates to:
  /// **'No upcoming appointments scheduled. Your clinic will add these after each visit.'**
  String get noAppointments;

  /// No description provided for @notificationsDisabledNote.
  ///
  /// In en, this message translates to:
  /// **'Notifications are off, so reminders won\'t alert you.'**
  String get notificationsDisabledNote;

  /// No description provided for @notificationsPermanentlyDeniedNote.
  ///
  /// In en, this message translates to:
  /// **'Notifications were denied before, so Android won\'t show that prompt again — open Settings to turn them on.'**
  String get notificationsPermanentlyDeniedNote;

  /// No description provided for @enableAction.
  ///
  /// In en, this message translates to:
  /// **'Enable'**
  String get enableAction;

  /// No description provided for @sendTestNotification.
  ///
  /// In en, this message translates to:
  /// **'Send a test notification now'**
  String get sendTestNotification;

  /// No description provided for @testNotificationTitle.
  ///
  /// In en, this message translates to:
  /// **'Test notification'**
  String get testNotificationTitle;

  /// No description provided for @testNotificationBody.
  ///
  /// In en, this message translates to:
  /// **'If you can see this, medication and appointment reminders will work the same way.'**
  String get testNotificationBody;

  /// No description provided for @testNotificationSentSnack.
  ///
  /// In en, this message translates to:
  /// **'Test notification sent — check your notification shade.'**
  String get testNotificationSentSnack;

  /// No description provided for @testNotificationFailedSnack.
  ///
  /// In en, this message translates to:
  /// **'Could not send a test notification. Check that notifications are enabled for this app.'**
  String get testNotificationFailedSnack;

  /// No description provided for @addAppointmentAction.
  ///
  /// In en, this message translates to:
  /// **'Add'**
  String get addAppointmentAction;

  /// No description provided for @addAppointmentTitle.
  ///
  /// In en, this message translates to:
  /// **'Add appointment reminder'**
  String get addAppointmentTitle;

  /// No description provided for @appointmentLabelField.
  ///
  /// In en, this message translates to:
  /// **'What is this appointment for?'**
  String get appointmentLabelField;

  /// No description provided for @pickDateTime.
  ///
  /// In en, this message translates to:
  /// **'Pick date & time'**
  String get pickDateTime;

  /// No description provided for @bookViaMySejahtera.
  ///
  /// In en, this message translates to:
  /// **'📅 Book an Appointment via MySejahtera'**
  String get bookViaMySejahtera;

  /// No description provided for @mySejahteraNote.
  ///
  /// In en, this message translates to:
  /// **'Opens the MySejahtera app if installed, otherwise its Play Store listing.'**
  String get mySejahteraNote;

  /// No description provided for @mySejahteraLaunchFailed.
  ///
  /// In en, this message translates to:
  /// **'Could not open MySejahtera or a fallback. Is a browser installed?'**
  String get mySejahteraLaunchFailed;

  /// No description provided for @apiSettingsTitle.
  ///
  /// In en, this message translates to:
  /// **'API Settings'**
  String get apiSettingsTitle;

  /// No description provided for @backendUrlLabel.
  ///
  /// In en, this message translates to:
  /// **'Backend API base URL'**
  String get backendUrlLabel;

  /// No description provided for @backendUrlDesc.
  ///
  /// In en, this message translates to:
  /// **'Point the app at your backend. Handy once you start a Cloudflare tunnel (the trycloudflare.com URL changes every time the tunnel restarts) — paste the new URL here instead of rebuilding the app.'**
  String get backendUrlDesc;

  /// No description provided for @apiBaseUrlFieldLabel.
  ///
  /// In en, this message translates to:
  /// **'API base URL'**
  String get apiBaseUrlFieldLabel;

  /// No description provided for @save.
  ///
  /// In en, this message translates to:
  /// **'Save'**
  String get save;

  /// No description provided for @resetToDefault.
  ///
  /// In en, this message translates to:
  /// **'Reset to default'**
  String get resetToDefault;

  /// No description provided for @currentlyActive.
  ///
  /// In en, this message translates to:
  /// **'Currently active: {url}'**
  String currentlyActive(String url);

  /// No description provided for @compileTimeDefault.
  ///
  /// In en, this message translates to:
  /// **'Compile-time default: {url}'**
  String compileTimeDefault(String url);

  /// No description provided for @usingOverride.
  ///
  /// In en, this message translates to:
  /// **'Using a runtime override.'**
  String get usingOverride;

  /// No description provided for @usingDefault.
  ///
  /// In en, this message translates to:
  /// **'Using the compile-time default.'**
  String get usingDefault;

  /// No description provided for @emulatorNote.
  ///
  /// In en, this message translates to:
  /// **'10.0.2.2 is the special alias the Android emulator uses to reach your host machine\'s localhost. On a physical phone, use your computer\'s LAN IP (e.g. http://192.168.1.42:8000) or a tunnel URL instead — the phone and the backend must be reachable from each other.'**
  String get emulatorNote;

  /// No description provided for @savedSnack.
  ///
  /// In en, this message translates to:
  /// **'API base URL set to {url}'**
  String savedSnack(String url);

  /// No description provided for @resetSnack.
  ///
  /// In en, this message translates to:
  /// **'Reset to compile-time default.'**
  String get resetSnack;

  /// No description provided for @seniorModeToggleLabel.
  ///
  /// In en, this message translates to:
  /// **'Senior Citizen Mode'**
  String get seniorModeToggleLabel;

  /// No description provided for @seniorModeToggleDesc.
  ///
  /// In en, this message translates to:
  /// **'Simplified view with larger text and fewer choices'**
  String get seniorModeToggleDesc;

  /// No description provided for @languageLabel.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get languageLabel;

  /// No description provided for @themeLabel.
  ///
  /// In en, this message translates to:
  /// **'Theme'**
  String get themeLabel;

  /// No description provided for @themeModeLight.
  ///
  /// In en, this message translates to:
  /// **'Light'**
  String get themeModeLight;

  /// No description provided for @themeModeDark.
  ///
  /// In en, this message translates to:
  /// **'Dark'**
  String get themeModeDark;

  /// No description provided for @themeModeSystem.
  ///
  /// In en, this message translates to:
  /// **'System default'**
  String get themeModeSystem;

  /// No description provided for @auditLogTitle.
  ///
  /// In en, this message translates to:
  /// **'Who\'s Viewed My Record'**
  String get auditLogTitle;

  /// No description provided for @noAccessLogged.
  ///
  /// In en, this message translates to:
  /// **'No access has been logged for your record yet.'**
  String get noAccessLogged;

  /// No description provided for @fieldsLabel.
  ///
  /// In en, this message translates to:
  /// **'Fields: {fields}'**
  String fieldsLabel(String fields);

  /// No description provided for @auditActorSystemFallback.
  ///
  /// In en, this message translates to:
  /// **'system'**
  String get auditActorSystemFallback;

  /// No description provided for @auditActorEmergencyResponderUnverified.
  ///
  /// In en, this message translates to:
  /// **'emergency responder — self-reported, unverified'**
  String get auditActorEmergencyResponderUnverified;

  /// No description provided for @auditLogLegendIntro.
  ///
  /// In en, this message translates to:
  /// **'Color and icon show how sensitive each access looks:'**
  String get auditLogLegendIntro;

  /// No description provided for @auditSeverityRoutine.
  ///
  /// In en, this message translates to:
  /// **'Routine'**
  String get auditSeverityRoutine;

  /// No description provided for @auditSeverityAttention.
  ///
  /// In en, this message translates to:
  /// **'Emergency access'**
  String get auditSeverityAttention;

  /// No description provided for @auditSeverityCritical.
  ///
  /// In en, this message translates to:
  /// **'Failed attempt'**
  String get auditSeverityCritical;

  /// No description provided for @responderScanTitle.
  ///
  /// In en, this message translates to:
  /// **'Scan Emergency Card'**
  String get responderScanTitle;

  /// No description provided for @responderScanDesc.
  ///
  /// In en, this message translates to:
  /// **'Scan a patient\'s emergency QR code, tap their physical NFC card, or type in a printed card reference / NFC UID. No login is required — the backend enforces this by design.'**
  String get responderScanDesc;

  /// No description provided for @cardReferenceLabel.
  ///
  /// In en, this message translates to:
  /// **'Card reference'**
  String get cardReferenceLabel;

  /// No description provided for @cardReferenceHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. from the Emergency tab'**
  String get cardReferenceHint;

  /// No description provided for @responderNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Responder name (optional)'**
  String get responderNameLabel;

  /// No description provided for @responderOrgLabel.
  ///
  /// In en, this message translates to:
  /// **'Responder organisation (optional)'**
  String get responderOrgLabel;

  /// No description provided for @scanButton.
  ///
  /// In en, this message translates to:
  /// **'Look Up'**
  String get scanButton;

  /// No description provided for @scanning.
  ///
  /// In en, this message translates to:
  /// **'Looking up…'**
  String get scanning;

  /// No description provided for @scanModeQr.
  ///
  /// In en, this message translates to:
  /// **'Scan QR'**
  String get scanModeQr;

  /// No description provided for @scanModeNfc.
  ///
  /// In en, this message translates to:
  /// **'Tap NFC'**
  String get scanModeNfc;

  /// No description provided for @scanModeManual.
  ///
  /// In en, this message translates to:
  /// **'Type Manually'**
  String get scanModeManual;

  /// No description provided for @nfcUidLabel.
  ///
  /// In en, this message translates to:
  /// **'NFC card UID'**
  String get nfcUidLabel;

  /// No description provided for @cameraPermissionDenied.
  ///
  /// In en, this message translates to:
  /// **'Camera permission was denied, so the QR scanner can\'t start. Grant camera access in system settings to use it.'**
  String get cameraPermissionDenied;

  /// No description provided for @openAppSettings.
  ///
  /// In en, this message translates to:
  /// **'Open Settings'**
  String get openAppSettings;

  /// No description provided for @nfcUnsupportedPlatform.
  ///
  /// In en, this message translates to:
  /// **'NFC scanning is only supported on Android in this app.'**
  String get nfcUnsupportedPlatform;

  /// No description provided for @nfcUnsupportedDevice.
  ///
  /// In en, this message translates to:
  /// **'This device doesn\'t have NFC hardware.'**
  String get nfcUnsupportedDevice;

  /// No description provided for @nfcDisabled.
  ///
  /// In en, this message translates to:
  /// **'NFC is turned off on this device. Turn it on in system settings, then come back to this screen.'**
  String get nfcDisabled;

  /// No description provided for @nfcReadyToTap.
  ///
  /// In en, this message translates to:
  /// **'Ready — hold the card against the back of the phone'**
  String get nfcReadyToTap;

  /// No description provided for @nfcStarting.
  ///
  /// In en, this message translates to:
  /// **'Starting NFC…'**
  String get nfcStarting;

  /// No description provided for @scanResultFoundTitle.
  ///
  /// In en, this message translates to:
  /// **'Patient Found'**
  String get scanResultFoundTitle;

  /// No description provided for @scanResultAgeValue.
  ///
  /// In en, this message translates to:
  /// **'Age: {age}'**
  String scanResultAgeValue(String age);

  /// No description provided for @scanResultBloodTypeUnknown.
  ///
  /// In en, this message translates to:
  /// **'Not on file'**
  String get scanResultBloodTypeUnknown;

  /// No description provided for @scanResultOmittedMedications.
  ///
  /// In en, this message translates to:
  /// **'+{count} more medications on file, not shown here — not flagged as emergency-critical.'**
  String scanResultOmittedMedications(int count);

  /// No description provided for @scanResultOmittedConditions.
  ///
  /// In en, this message translates to:
  /// **'+{count} more conditions on file, not shown here — not flagged as emergency-critical.'**
  String scanResultOmittedConditions(int count);

  /// No description provided for @scanResultOmittedAllergies.
  ///
  /// In en, this message translates to:
  /// **'+{count} more allergies on file, not shown here — not flagged as emergency-critical.'**
  String scanResultOmittedAllergies(int count);

  /// No description provided for @seniorBloodType.
  ///
  /// In en, this message translates to:
  /// **'BLOOD TYPE: {type}'**
  String seniorBloodType(String type);

  /// No description provided for @seniorAllergicTo.
  ///
  /// In en, this message translates to:
  /// **'ALLERGIC TO: {allergy}'**
  String seniorAllergicTo(String allergy);

  /// No description provided for @seniorEmergencyTile.
  ///
  /// In en, this message translates to:
  /// **'🚨\nEMERGENCY\nCARD'**
  String get seniorEmergencyTile;

  /// No description provided for @seniorMedsTile.
  ///
  /// In en, this message translates to:
  /// **'💊\nMY\nMEDICATIONS'**
  String get seniorMedsTile;

  /// No description provided for @switchToStandard.
  ///
  /// In en, this message translates to:
  /// **'Switch to Standard View'**
  String get switchToStandard;

  /// No description provided for @signOutSenior.
  ///
  /// In en, this message translates to:
  /// **'Sign Out'**
  String get signOutSenior;

  /// No description provided for @seniorLanguageTitle.
  ///
  /// In en, this message translates to:
  /// **'Change Language'**
  String get seniorLanguageTitle;

  /// No description provided for @seniorEmergencyTitle.
  ///
  /// In en, this message translates to:
  /// **'EMERGENCY CARD'**
  String get seniorEmergencyTitle;

  /// No description provided for @preparingCard.
  ///
  /// In en, this message translates to:
  /// **'Preparing your card…'**
  String get preparingCard;

  /// No description provided for @showToResponder.
  ///
  /// In en, this message translates to:
  /// **'SHOW THIS TO A\nMEDICAL RESPONDER'**
  String get showToResponder;

  /// No description provided for @refLabel.
  ///
  /// In en, this message translates to:
  /// **'Ref: {ref}'**
  String refLabel(String ref);

  /// No description provided for @getNewCard.
  ///
  /// In en, this message translates to:
  /// **'Get a New Card'**
  String get getNewCard;

  /// No description provided for @tryAgain.
  ///
  /// In en, this message translates to:
  /// **'Try Again'**
  String get tryAgain;

  /// No description provided for @seniorMedsTitle.
  ///
  /// In en, this message translates to:
  /// **'MY MEDICATIONS'**
  String get seniorMedsTitle;

  /// No description provided for @noMedsRecord.
  ///
  /// In en, this message translates to:
  /// **'No medications on record.'**
  String get noMedsRecord;

  /// No description provided for @takeTwiceDaily.
  ///
  /// In en, this message translates to:
  /// **'Take twice daily: 8 AM and 8 PM'**
  String get takeTwiceDaily;

  /// No description provided for @fromFacility.
  ///
  /// In en, this message translates to:
  /// **'From {facility}'**
  String fromFacility(String facility);

  /// No description provided for @yourClinic.
  ///
  /// In en, this message translates to:
  /// **'your clinic'**
  String get yourClinic;

  /// No description provided for @nfcCardSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Physical NFC Card'**
  String get nfcCardSectionTitle;

  /// No description provided for @nfcCardActiveLine.
  ///
  /// In en, this message translates to:
  /// **'Card {uid} — active'**
  String nfcCardActiveLine(String uid);

  /// No description provided for @nfcCardRevokedLine.
  ///
  /// In en, this message translates to:
  /// **'Card {uid} — revoked'**
  String nfcCardRevokedLine(String uid);

  /// No description provided for @editProfileTitle.
  ///
  /// In en, this message translates to:
  /// **'Edit Profile'**
  String get editProfileTitle;

  /// No description provided for @readOnlyFieldsNote.
  ///
  /// In en, this message translates to:
  /// **'Your name, date of birth, and NRIC can\'t be changed here. Contact your clinic to correct them.'**
  String get readOnlyFieldsNote;

  /// No description provided for @fullNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Full name'**
  String get fullNameLabel;

  /// No description provided for @editableProfileSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Contact Details'**
  String get editableProfileSectionTitle;

  /// No description provided for @profileEmailLabel.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get profileEmailLabel;

  /// No description provided for @profilePhoneLabel.
  ///
  /// In en, this message translates to:
  /// **'Phone'**
  String get profilePhoneLabel;

  /// No description provided for @emergencyContactSectionTitle.
  ///
  /// In en, this message translates to:
  /// **'Emergency Contact'**
  String get emergencyContactSectionTitle;

  /// No description provided for @emergencyContactNameLabel.
  ///
  /// In en, this message translates to:
  /// **'Emergency contact name'**
  String get emergencyContactNameLabel;

  /// No description provided for @emergencyContactPhoneLabel.
  ///
  /// In en, this message translates to:
  /// **'Emergency contact phone'**
  String get emergencyContactPhoneLabel;

  /// No description provided for @emergencyContactRelationshipLabel.
  ///
  /// In en, this message translates to:
  /// **'Relationship to you'**
  String get emergencyContactRelationshipLabel;

  /// No description provided for @saveProfileButton.
  ///
  /// In en, this message translates to:
  /// **'Save Changes'**
  String get saveProfileButton;

  /// No description provided for @profileUpdatedSnack.
  ///
  /// In en, this message translates to:
  /// **'Your profile has been updated.'**
  String get profileUpdatedSnack;

  /// No description provided for @profileUpdateFailedGeneric.
  ///
  /// In en, this message translates to:
  /// **'Could not update your profile. Please try again.'**
  String get profileUpdateFailedGeneric;

  /// No description provided for @missingProfileBannerText.
  ///
  /// In en, this message translates to:
  /// **'Your profile is missing some details — tap to complete it.'**
  String get missingProfileBannerText;

  /// No description provided for @dismiss.
  ///
  /// In en, this message translates to:
  /// **'Dismiss'**
  String get dismiss;

  /// No description provided for @unexpectedErrorGeneric.
  ///
  /// In en, this message translates to:
  /// **'Something went wrong. Please try again.'**
  String get unexpectedErrorGeneric;

  /// No description provided for @queueStatusButton.
  ///
  /// In en, this message translates to:
  /// **'Queue Status'**
  String get queueStatusButton;

  /// No description provided for @queueStatusTitle.
  ///
  /// In en, this message translates to:
  /// **'Your Queue Status'**
  String get queueStatusTitle;

  /// No description provided for @yourNumberLabel.
  ///
  /// In en, this message translates to:
  /// **'Your number: {number}'**
  String yourNumberLabel(String number);

  /// No description provided for @nowServingLabel.
  ///
  /// In en, this message translates to:
  /// **'Now serving: {number}'**
  String nowServingLabel(String number);

  /// No description provided for @nowServingNoneYet.
  ///
  /// In en, this message translates to:
  /// **'No number called yet'**
  String get nowServingNoneYet;

  /// No description provided for @peopleAheadLabel.
  ///
  /// In en, this message translates to:
  /// **'{count} people ahead of you'**
  String peopleAheadLabel(String count);

  /// No description provided for @queueTicketDetailsTitle.
  ///
  /// In en, this message translates to:
  /// **'Ticket Details'**
  String get queueTicketDetailsTitle;

  /// No description provided for @queueStatusLabel.
  ///
  /// In en, this message translates to:
  /// **'Status'**
  String get queueStatusLabel;

  /// No description provided for @queueFacilityLabel.
  ///
  /// In en, this message translates to:
  /// **'Facility'**
  String get queueFacilityLabel;

  /// No description provided for @queueDepartmentLabel.
  ///
  /// In en, this message translates to:
  /// **'Department'**
  String get queueDepartmentLabel;

  /// No description provided for @queueReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'Reason'**
  String get queueReasonLabel;

  /// No description provided for @queueStatusWaiting.
  ///
  /// In en, this message translates to:
  /// **'Waiting'**
  String get queueStatusWaiting;

  /// No description provided for @queueStatusCalled.
  ///
  /// In en, this message translates to:
  /// **'Called'**
  String get queueStatusCalled;

  /// No description provided for @queueStatusDone.
  ///
  /// In en, this message translates to:
  /// **'Done'**
  String get queueStatusDone;

  /// No description provided for @queueStatusCancelled.
  ///
  /// In en, this message translates to:
  /// **'Cancelled'**
  String get queueStatusCancelled;

  /// No description provided for @noActiveQueueTicketTitle.
  ///
  /// In en, this message translates to:
  /// **'No active queue ticket'**
  String get noActiveQueueTicketTitle;

  /// No description provided for @noActiveQueueTicketDesc.
  ///
  /// In en, this message translates to:
  /// **'Check in at reception to get a queue number.'**
  String get noActiveQueueTicketDesc;

  /// No description provided for @scanCheckinButton.
  ///
  /// In en, this message translates to:
  /// **'Scan to Check In'**
  String get scanCheckinButton;

  /// No description provided for @scanCheckinTitle.
  ///
  /// In en, this message translates to:
  /// **'Scan to Check In'**
  String get scanCheckinTitle;

  /// No description provided for @scanCheckinDesc.
  ///
  /// In en, this message translates to:
  /// **'Scan the QR code at the reception self-check-in station, or type in its code below. No staff assistance needed — you\'ll get a queue number right away.'**
  String get scanCheckinDesc;

  /// No description provided for @checkinReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'Reason for visit (optional)'**
  String get checkinReasonLabel;

  /// No description provided for @checkinReasonHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. follow-up, blood test'**
  String get checkinReasonHint;

  /// No description provided for @stationCodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Station code'**
  String get stationCodeLabel;

  /// No description provided for @stationCodeHint.
  ///
  /// In en, this message translates to:
  /// **'e.g. from the reception counter\'s printed code'**
  String get stationCodeHint;

  /// No description provided for @checkinSubmitButton.
  ///
  /// In en, this message translates to:
  /// **'Check In'**
  String get checkinSubmitButton;

  /// No description provided for @checkinSubmitting.
  ///
  /// In en, this message translates to:
  /// **'Checking in…'**
  String get checkinSubmitting;

  /// No description provided for @requestRescheduleButton.
  ///
  /// In en, this message translates to:
  /// **'Request Reschedule'**
  String get requestRescheduleButton;

  /// No description provided for @rescheduleDialogTitle.
  ///
  /// In en, this message translates to:
  /// **'Request a Reschedule'**
  String get rescheduleDialogTitle;

  /// No description provided for @rescheduleDialogDesc.
  ///
  /// In en, this message translates to:
  /// **'Let your clinic know you can\'t make this appointment. They\'ll review your request and follow up with you.'**
  String get rescheduleDialogDesc;

  /// No description provided for @rescheduleReasonScheduleConflict.
  ///
  /// In en, this message translates to:
  /// **'Schedule conflict'**
  String get rescheduleReasonScheduleConflict;

  /// No description provided for @rescheduleReasonUnwell.
  ///
  /// In en, this message translates to:
  /// **'Unwell / can\'t travel'**
  String get rescheduleReasonUnwell;

  /// No description provided for @rescheduleReasonTransport.
  ///
  /// In en, this message translates to:
  /// **'Transport issue'**
  String get rescheduleReasonTransport;

  /// No description provided for @rescheduleReasonOther.
  ///
  /// In en, this message translates to:
  /// **'Other'**
  String get rescheduleReasonOther;

  /// No description provided for @rescheduleOtherReasonLabel.
  ///
  /// In en, this message translates to:
  /// **'Please describe your reason'**
  String get rescheduleOtherReasonLabel;

  /// No description provided for @rescheduleOtherReasonRequired.
  ///
  /// In en, this message translates to:
  /// **'Please describe your reason.'**
  String get rescheduleOtherReasonRequired;

  /// No description provided for @rescheduleSubmitButton.
  ///
  /// In en, this message translates to:
  /// **'Submit Request'**
  String get rescheduleSubmitButton;

  /// No description provided for @rescheduleSubmitting.
  ///
  /// In en, this message translates to:
  /// **'Submitting…'**
  String get rescheduleSubmitting;

  /// No description provided for @reschedulePendingNote.
  ///
  /// In en, this message translates to:
  /// **'Reschedule requested — waiting for the clinic to respond'**
  String get reschedulePendingNote;

  /// No description provided for @rescheduleAcceptedNote.
  ///
  /// In en, this message translates to:
  /// **'Your reschedule request was accepted.'**
  String get rescheduleAcceptedNote;

  /// No description provided for @rescheduleRejectedNote.
  ///
  /// In en, this message translates to:
  /// **'Your reschedule request was declined.'**
  String get rescheduleRejectedNote;

  /// No description provided for @rescheduleClinicianNoteLabel.
  ///
  /// In en, this message translates to:
  /// **'Clinic note: {note}'**
  String rescheduleClinicianNoteLabel(String note);

  /// No description provided for @previouslyScheduledLabel.
  ///
  /// In en, this message translates to:
  /// **'Previously: {date}'**
  String previouslyScheduledLabel(String date);

  /// No description provided for @seniorMenuTooltip.
  ///
  /// In en, this message translates to:
  /// **'Menu'**
  String get seniorMenuTooltip;

  /// No description provided for @seniorMenuTitle.
  ///
  /// In en, this message translates to:
  /// **'Menu'**
  String get seniorMenuTitle;

  /// No description provided for @seniorThemeToggleTooltip.
  ///
  /// In en, this message translates to:
  /// **'Switch colour theme'**
  String get seniorThemeToggleTooltip;

  /// No description provided for @confirmSwitchToStandardTitle.
  ///
  /// In en, this message translates to:
  /// **'Switch to Standard View?'**
  String get confirmSwitchToStandardTitle;

  /// No description provided for @confirmSwitchToStandardBody.
  ///
  /// In en, this message translates to:
  /// **'You\'ll leave Senior Mode and see the regular app. You can turn Senior Mode back on anytime from Settings.'**
  String get confirmSwitchToStandardBody;

  /// No description provided for @confirmSwitchToStandardAction.
  ///
  /// In en, this message translates to:
  /// **'Yes, Switch'**
  String get confirmSwitchToStandardAction;

  /// No description provided for @confirmSignOutTitle.
  ///
  /// In en, this message translates to:
  /// **'Sign Out?'**
  String get confirmSignOutTitle;

  /// No description provided for @confirmSignOutBody.
  ///
  /// In en, this message translates to:
  /// **'You will need to sign in again to see your health record.'**
  String get confirmSignOutBody;

  /// No description provided for @confirmSignOutAction.
  ///
  /// In en, this message translates to:
  /// **'Yes, Sign Out'**
  String get confirmSignOutAction;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'ms', 'ta', 'zh'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'ms':
      return AppLocalizationsMs();
    case 'ta':
      return AppLocalizationsTa();
    case 'zh':
      return AppLocalizationsZh();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
