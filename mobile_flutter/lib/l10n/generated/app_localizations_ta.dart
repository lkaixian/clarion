// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Tamil (`ta`).
class AppLocalizationsTa extends AppLocalizations {
  AppLocalizationsTa([String locale = 'ta']) : super(locale);

  @override
  String get appTitle => 'CLARION';

  @override
  String get apiSettingsTooltip => 'API அமைப்புகள்';

  @override
  String get back => 'பின் செல்';

  @override
  String get loginSubtitle =>
      'நீங்கள் எங்கிருந்தாலும், உங்கள் சுகாதார பதிவு உங்களுடன்';

  @override
  String get emailLabel => 'மின்னஞ்சல்';

  @override
  String get emailOrNricLabel => 'மின்னஞ்சல் அல்லது அடையாள அட்டை எண்';

  @override
  String get passwordLabel => 'கடவுச்சொல்';

  @override
  String get emailOrNricHint => 'name@example.com அல்லது 900101-01-1234';

  @override
  String get loginFieldRequired =>
      'மின்னஞ்சல் அல்லது அடையாள அட்டை எண்ணையும் கடவுச்சொல்லையும் உள்ளிடவும்.';

  @override
  String get mfaResendButton => 'புதிய குறியீட்டை அனுப்பு';

  @override
  String mfaResendIn(int seconds) {
    return '$seconds விநாடிகளில் புதிய குறியீட்டை அனுப்பலாம்';
  }

  @override
  String get signIn => 'உள்நுழைக';

  @override
  String get signingIn => 'உள்நுழைகிறது…';

  @override
  String get loginFailedGeneric =>
      'உள்நுழைவு தோல்வியடைந்தது. உங்கள் விவரங்களை அல்லது அமைப்புகளில் உள்ள API முகவரியை சரிபார்க்கவும்.';

  @override
  String get sessionExpiredSnackbar =>
      'நீங்கள் வெளியேற்றப்பட்டீர்கள் — மீண்டும் உள்நுழையவும்.';

  @override
  String get seniorPrompt => 'மூத்த குடிமகனா அல்லது புதிய பயனரா?';

  @override
  String get enableSeniorMode => 'மூத்த குடிமக்கள் பயன்முறையை இயக்கு →';

  @override
  String get seniorModeWillOpen =>
      'நீங்கள் உள்நுழைந்தவுடன் மூத்த குடிமக்கள் பயன்முறை திறக்கும்';

  @override
  String get undo => 'செயல்தவிர்';

  @override
  String get scanEmergencyCardButton =>
      'அவசர அட்டையை ஸ்கேன் செய்யவும் (QR அல்லது NFC)';

  @override
  String get scanEmergencyCardSubtitle =>
      'முதல் உதவியாளர்களுக்கு. உள்நுழைவு தேவையில்லை.';

  @override
  String get orSignInDivider =>
      'அல்லது உங்கள் சொந்த பதிவை நிர்வகிக்க உள்நுழையவும்';

  @override
  String get forgotPasswordButton => 'கடவுச்சொல்லை மறந்துவிட்டீர்களா?';

  @override
  String get selfRegisterLinkPrompt => 'முதல் முறையா?';

  @override
  String get selfRegisterLinkAction => 'பதிவு செய்';

  @override
  String get forgotPasswordTitle => 'கடவுச்சொல்லை மீட்டமை';

  @override
  String get forgotPasswordDesc =>
      'நோயாளிகளுக்கு மட்டும். உங்கள் சுகாதார பதிவில் உள்ளபடி உங்கள் அடையாள அட்டை எண் மற்றும் பிறந்த தேதியை உள்ளிட்டு, புதிய கடவுச்சொல்லைத் தேர்ந்தெடுக்கவும்.';

  @override
  String get forgotPasswordStep1Desc =>
      'நோயாளிகளுக்கு மட்டும். உங்கள் அடையாள அட்டை எண்ணை உள்ளிடவும்; உங்கள் கணக்கில் மின்னஞ்சல் பதிவு செய்யப்பட்டிருந்தால், அதற்கு சரிபார்ப்பு குறியீட்டை அனுப்புவோம்.';

  @override
  String get sendCodeButton => 'குறியீட்டை அனுப்பு';

  @override
  String get otpRequestedGenericSnack =>
      'இந்த அடையாள அட்டை எண்ணிற்கு மின்னஞ்சல் பதிவு செய்யப்பட்டிருந்தால், சரிபார்ப்பு குறியீடு அனுப்பப்பட்டுள்ளது.';

  @override
  String get otpCodeLabel => 'சரிபார்ப்பு குறியீடு';

  @override
  String get forgotPasswordStep2Desc =>
      'நாங்கள் அனுப்பிய 6 இலக்க குறியீட்டை உள்ளிட்டு, புதிய கடவுச்சொல்லைத் தேர்ந்தெடுக்கவும்.';

  @override
  String get resendCodeButton => 'குறியீடு கிடைக்கவில்லையா? மீண்டும் அனுப்பு';

  @override
  String get resendCodeSentSnack =>
      'இந்த அடையாள அட்டை எண்ணிற்கு மின்னஞ்சல் பதிவு செய்யப்பட்டிருந்தால், புதிய சரிபார்ப்பு குறியீடு அனுப்பப்பட்டுள்ளது.';

  @override
  String get useDifferentNricButton => 'வேறு அடையாள அட்டை எண்ணைப் பயன்படுத்து';

  @override
  String get requestOtpFailedGeneric =>
      'சரிபார்ப்பு குறியீட்டைக் கோர முடியவில்லை. உங்கள் அடையாள அட்டை எண் அல்லது அமைப்புகளில் உள்ள API முகவரியை சரிபார்க்கவும்.';

  @override
  String get nricLabel => 'அடையாள அட்டை எண்';

  @override
  String get dateOfBirthLabel => 'பிறந்த தேதி';

  @override
  String get newPasswordLabel => 'புதிய கடவுச்சொல்';

  @override
  String get passwordRulesTitle => 'உங்கள் கடவுச்சொல்லில் இருக்க வேண்டியவை:';

  @override
  String get passwordRuleLength => 'குறைந்தது 8 எழுத்துகள்';

  @override
  String get passwordRuleNumber => 'குறைந்தது 1 எண்';

  @override
  String get passwordRuleUpper => 'குறைந்தது 1 பெரிய எழுத்து';

  @override
  String get passwordRuleSpecial =>
      'குறைந்தது 1 சிறப்பு எழுத்து (! @ # \$ * . ?)';

  @override
  String get passwordRulesNotMet =>
      'கடவுச்சொல் அனைத்துத் தேவைகளையும் பூர்த்தி செய்யவில்லை.';

  @override
  String get confirmNewPasswordLabel => 'புதிய கடவுச்சொல்லை உறுதிப்படுத்தவும்';

  @override
  String get allFieldsRequired => 'அனைத்து புலங்களையும் நிரப்பவும்.';

  @override
  String get passwordsDoNotMatch => 'கடவுச்சொற்கள் பொருந்தவில்லை.';

  @override
  String get resetPasswordButton => 'கடவுச்சொல்லை மீட்டமை';

  @override
  String get passwordResetSuccessSnack =>
      'உங்கள் கடவுச்சொல் மீட்டமைக்கப்பட்டது. உங்கள் புதிய கடவுச்சொல்லுடன் உள்நுழையவும்.';

  @override
  String get forgotPasswordFailedGeneric =>
      'உங்கள் கடவுச்சொல்லை மீட்டமைக்க முடியவில்லை. உங்கள் விவரங்களை அல்லது அமைப்புகளில் உள்ள API முகவரியை சரிபார்க்கவும்.';

  @override
  String get selfRegisterTitle => 'உங்கள் கணக்கை உருவாக்குங்கள்';

  @override
  String get selfRegisterDetailsStepDesc =>
      'இன்னும் CLARION உள்நுழைவு இல்லாத நோயாளிகளுக்கு. உங்கள் அடையாள அட்டையில் உள்ளபடியே உங்கள் விவரங்களை உள்ளிடவும் — அவற்றை உங்கள் மருத்துவமனை பதிவுடன் சரிபார்ப்போம்.';

  @override
  String get selfRegisterContinueButton => 'தொடரவும்';

  @override
  String get selfRegisterStartFailedGeneric =>
      'உங்கள் விவரங்களை சரிபார்க்க முடியவில்லை. நீங்கள் உள்ளிட்டதை அல்லது அமைப்புகளில் உள்ள API முகவரியை சரிபார்க்கவும்.';

  @override
  String get selfRegisterOtpStepDesc =>
      'நாங்கள் உங்கள் மின்னஞ்சலுக்கு அனுப்பிய 6 இலக்க சரிபார்ப்பு குறியீட்டை உள்ளிடவும்.';

  @override
  String get selfRegisterScanButton =>
      'என் அடையாள அட்டையை ஸ்கேன் செய்து நிரப்பு';

  @override
  String get selfRegisterScanPrivacy =>
      'புகைப்படம் இந்தத் தொலைபேசியிலேயே படிக்கப்படும், பதிவேற்றப்படாது. தொடர்வதற்கு முன் விவரங்களைச் சரிபார்க்கவும்.';

  @override
  String selfRegisterCodeSentTo(String hint) {
    return 'உங்கள் மருத்துவமனைப் பதிவில் உள்ள $hint முகவரிக்கு 6 இலக்கக் குறியீட்டை அனுப்பியுள்ளோம். கீழே உள்ளிடவும்.';
  }

  @override
  String get selfRegisterVerifyOtpButton => 'குறியீட்டை சரிபார்';

  @override
  String get selfRegisterVerifyOtpFailedGeneric =>
      'அந்த குறியீட்டை சரிபார்க்க முடியவில்லை. உங்கள் குறியீட்டை அல்லது அமைப்புகளில் உள்ள API முகவரியை சரிபார்க்கவும்.';

  @override
  String get selfRegisterPhotosStepTitle => 'உங்கள் அடையாளத்தை சரிபார்க்கவும்';

  @override
  String get selfRegisterPhotosStepDesc =>
      'இப்போது உங்கள் இயற்பியல் அடையாள அட்டையின் முன் மற்றும் பின் பக்கங்களின் தெளிவான புகைப்படங்களை எடுக்கவும். இவை உங்கள் மருத்துவமனை பதிவுடன் உங்கள் அடையாளத்தை உறுதிப்படுத்த மட்டுமே பயன்படுத்தப்படும் — இந்த செயலி அல்ல, எங்கள் ஊழியர்கள் தான் பொருத்தத்தை சரிபார்ப்பார்கள்.';

  @override
  String get selfRegisterFrontPhotoLabel => 'அடையாள அட்டையின் முன்பக்கம்';

  @override
  String get selfRegisterBackPhotoLabel => 'அடையாள அட்டையின் பின்பக்கம்';

  @override
  String get selfRegisterTakePhotoButton => 'புகைப்படம் எடு';

  @override
  String get selfRegisterRetakePhotoButton => 'மீண்டும் எடு';

  @override
  String selfRegisterAttemptsRemaining(int count) {
    return '5 இல் $count முயற்சிகள் மீதம்';
  }

  @override
  String get selfRegisterSubmitPhotosButton => 'புகைப்படங்களை சமர்ப்பி';

  @override
  String get selfRegisterPhotosRequiredNote =>
      'சமர்ப்பிக்கும் முன் இரண்டு புகைப்படங்களையும் எடுக்கவும்.';

  @override
  String get selfRegisterPhotosFailedGeneric =>
      'உங்கள் புகைப்படங்களை சரிபார்க்க முடியவில்லை. அமைப்புகளில் உள்ள API முகவரியை சரிபார்த்து மீண்டும் முயற்சிக்கவும்.';

  @override
  String get selfRegisterCameraFailed =>
      'கேமராவைத் திறக்க முடியவில்லை. கணினி அமைப்புகளில் கேமரா அனுமதியை சரிபார்த்து மீண்டும் முயற்சிக்கவும்.';

  @override
  String get selfRegisterPasswordStepDesc =>
      'கிட்டத்தட்ட முடிந்தது. உங்கள் புதிய கணக்கிற்கு ஒரு கடவுச்சொல்லைத் தேர்ந்தெடுக்கவும் (குறைந்தது 8 எழுத்துகள்).';

  @override
  String get selfRegisterPendingDesc =>
      'Your sign-up is waiting for verification and you cannot sign in yet. It is approved once staff check your IC at a counter, or as soon as your IC photos match. Only the first verified sign-up for an NRIC is kept; any others are rejected and their emails flagged.';

  @override
  String get selfRegisterCompleteButton => 'கணக்கை உருவாக்கு';

  @override
  String get selfRegisterCompleteFailedGeneric =>
      'உங்கள் கணக்கை உருவாக்க முடியவில்லை. அமைப்புகளில் உள்ள API முகவரியை சரிபார்த்து மீண்டும் முயற்சிக்கவும்.';

  @override
  String get selfRegisterSuccessSnack =>
      'கணக்கு உருவாக்கப்பட்டது — CLARION-க்கு வரவேற்கிறோம்!';

  @override
  String get selfRegisterManualRequiredTitle =>
      'பதிவு கவுண்டரில் நேரில் வரவும்';

  @override
  String get selfRegisterManualRequiredBody =>
      'பல முயற்சிகளுக்குப் பிறகும் உங்கள் அடையாள அட்டை புகைப்படங்களை சரிபார்க்க முடியவில்லை. உங்கள் பாதுகாப்பிற்காக, உங்கள் இயற்பியல் அடையாள அட்டையுடன் நேரில் ஒரு பதிவு கவுண்டருக்குச் செல்லவும் — எங்கள் ஊழியர்கள் அங்கு உங்கள் கணக்கை அமைக்க உதவுவார்கள்.';

  @override
  String get selfRegisterManualRequiredBackButton => 'உள்நுழைவுக்குத் திரும்பு';

  @override
  String get changePasswordTitle => 'கடவுச்சொல்லை மாற்று';

  @override
  String get changePasswordRequiredNotice =>
      'உங்கள் கணக்கு தற்காலிக கடவுச்சொல்லுடன் அமைக்கப்பட்டது. பாதுகாப்பிற்காக, தொடர்வதற்கு முன் உங்கள் சொந்த கடவுச்சொல்லை அமைக்க வேண்டும்.';

  @override
  String get temporaryPasswordLabel => 'தற்காலிக கடவுச்சொல்';

  @override
  String get changePasswordButton => 'கடவுச்சொல்லை மாற்று';

  @override
  String get passwordChangedSnack => 'கடவுச்சொல் வெற்றிகரமாக மாற்றப்பட்டது.';

  @override
  String get homeTitle => 'எனது சுகாதார பதிவு';

  @override
  String get quickActionsSectionTitle => 'விரைவு செயல்கள்';

  @override
  String get healthRecordSectionTitle => 'உங்கள் மருத்துவ பதிவு';

  @override
  String get scanSomeoneElsesCardTooltip =>
      'மற்றவரின் அவசர அட்டையை ஸ்கேன் செய்யவும்';

  @override
  String get noPatientRecord =>
      'இந்த கணக்கிற்கு தொடர்புடைய நோயாளி பதிவு எதுவும் இல்லை.';

  @override
  String bloodTypeLabel(String type) {
    return 'இரத்த வகை $type';
  }

  @override
  String get signOut => 'வெளியேறு';

  @override
  String get emergencyButton => '🚨 அவசர QR அட்டையை பார்/உருவாக்கு';

  @override
  String get healthSummaryTitle => 'உங்கள் சுகாதார சுருக்கம்';

  @override
  String get activeConditionsTitle => 'தற்போதைய நோய் நிலைகள்';

  @override
  String get noConditions => 'பதிவில் நோய் நிலைகள் இல்லை.';

  @override
  String get chronicSuffix => '(நீடித்த)';

  @override
  String diagnosedOnLabel(String date) {
    return 'கண்டறியப்பட்டது $date';
  }

  @override
  String get currentMedicationsTitle => 'தற்போதைய மருந்துகள்';

  @override
  String get noActiveMedications => 'தற்போதைய மருந்துகள் இல்லை.';

  @override
  String get unknownFacility => 'தெரியாத மருத்துவமனை';

  @override
  String get allergiesTitle => 'ஒவ்வாமைகள்';

  @override
  String get noAllergies => 'பதிவில் அறியப்பட்ட ஒவ்வாமைகள் இல்லை.';

  @override
  String get recentEncountersTitle => 'சமீபத்திய வருகைகள்';

  @override
  String get noEncounters => 'பதிவில் வருகைகள் இல்லை.';

  @override
  String encounterReasonLabel(String reason) {
    return 'காரணம்: $reason';
  }

  @override
  String encounterNotesLabel(String notes) {
    return 'குறிப்புகள்: $notes';
  }

  @override
  String encounterDepartmentLabel(String department) {
    return 'துறை: $department';
  }

  @override
  String encounterVitalsLabel(String vitals) {
    return 'உயிர் அறிகுறிகள்: $vitals';
  }

  @override
  String get downloadVisitSummary =>
      'வருகை சுருக்கத்தைப் பதிவிறக்கு / பகிர் (PDF)';

  @override
  String get visitSummaryUnavailable =>
      'இந்த வருகைக்கான சுருக்கம் இன்னும் கிடைக்கவில்லை.';

  @override
  String get documentsTitle => 'ஆவணங்கள்';

  @override
  String get noDocuments => 'பதிவில் ஆவணங்கள் இல்லை.';

  @override
  String get docTypePrescription => 'மருந்துச் சீட்டு';

  @override
  String get docTypeDischargeSummary => 'வெளியேற்றச் சுருக்கம்';

  @override
  String get docTypeLabReport => 'ஆய்வக அறிக்கை';

  @override
  String get docTypeImaging => 'இமேஜிங்';

  @override
  String get docTypeOther => 'ஆவணம்';

  @override
  String documentUploadedLine(String facility, String date) {
    return '$facility ஆல் $date அன்று பதிவேற்றப்பட்டது';
  }

  @override
  String get remindersButton => 'மருந்து & சந்திப்பு நினைவூட்டல்கள்';

  @override
  String get bookAppointmentButton => 'சந்திப்பு பதிவு செய்யவும்';

  @override
  String get whoViewedRecord => 'எனது பதிவை யார் பார்த்தார்கள்?';

  @override
  String get retry => 'மீண்டும் முயற்சி';

  @override
  String showMoreAction(int count) {
    return 'மேலும் $count காட்டு';
  }

  @override
  String get showLessAction => 'குறைவாகக் காட்டு';

  @override
  String get emergencyCardTitle => 'அவசர அட்டை';

  @override
  String get emergencyAccessCardTitle => 'அவசர அணுகல் அட்டை';

  @override
  String get scopeAllergies => 'ஒவ்வாமைகள்';

  @override
  String get scopeMedications => 'தற்போதைய மருந்துகள்';

  @override
  String get scopeConditions => 'நீடித்த நோய் நிலைகள்';

  @override
  String get scopeBloodType => 'இரத்த வகை';

  @override
  String get generateButton => 'QR / அட்டையை உருவாக்கு';

  @override
  String get issuing => 'உருவாக்குகிறது…';

  @override
  String get printNote =>
      'இணையம் இல்லாத நேரங்களில் / மூத்த குடிமக்களுக்காக இந்த அட்டையை அச்சிடவும். இதில் உங்கள் இரத்த வகை மற்றும் முக்கிய ஒவ்வாமையையும் பெரிய எழுத்தில் காட்ட வேண்டும்.';

  @override
  String referenceLabel(String ref) {
    return 'குறிப்பு எண்: $ref';
  }

  @override
  String validUntilLabel(String date) {
    return 'செல்லுபடியாகும் தேதி: $date';
  }

  @override
  String get revokeCard => 'இந்த அட்டையை ரத்து செய்';

  @override
  String get revokedBadge => 'ரத்து செய்யப்பட்டது';

  @override
  String get couldNotRenderQr => 'QR படத்தை காட்ட முடியவில்லை';

  @override
  String get cardRevokedSnack => 'அட்டை ரத்து செய்யப்பட்டது.';

  @override
  String get cardRevokeFailedSnack => 'அட்டையை ரத்து செய்ய முடியவில்லை.';

  @override
  String get cardIssueFailedSnack => 'அட்டையை உருவாக்க முடியவில்லை.';

  @override
  String get cardIssuedSnack => 'புதிய அவசர அட்டை வழங்கப்பட்டது.';

  @override
  String cardIssuedWithRevokeSnack(int count) {
    return 'புதிய அட்டை வழங்கப்பட்டது. $count முந்தைய அட்டை(கள்) தானாக ரத்து செய்யப்பட்டன.';
  }

  @override
  String get onlyOneLiveCardNote =>
      'ஒரே நேரத்தில் ஒரு செயலில் உள்ள QR அட்டை மட்டுமே இருக்க முடியும் — புதிய அட்டையை உருவாக்குவது முந்தைய அட்டையை தானாக ரத்து செய்யும்.';

  @override
  String get regenerateConfirmTitle => 'உங்கள் தற்போதைய அட்டையை மாற்றவா?';

  @override
  String regenerateConfirmBody(String ref) {
    return 'உங்களிடம் ஏற்கனவே செயலில் உள்ள அட்டை உள்ளது (குறிப்பு: $ref). புதிய அட்டையை உருவாக்குவது அதை தானாக ரத்து செய்யும் — பழைய QR குறியீடு உடனடியாக வேலை செய்வதை நிறுத்தும்.';
  }

  @override
  String get regenerateConfirmAction => 'பழையதை ரத்து செய், புதியதை உருவாக்கு';

  @override
  String get remindersTitle => 'நினைவூட்டல்கள்';

  @override
  String get announcementsSectionTitle => 'அறிவிப்புகள்';

  @override
  String get medicationsSection => 'மருந்துகள்';

  @override
  String get noActiveMedsRecord => 'பதிவில் தற்போதைய மருந்துகள் இல்லை.';

  @override
  String get suggestedReminder =>
      'பரிந்துரைக்கப்படும் நேரம்: நாளொன்றுக்கு இருமுறை, காலை 8 மணி / இரவு 8 மணி';

  @override
  String prescribedBy(String facility) {
    return 'பரிந்துரைத்தவர்: $facility';
  }

  @override
  String get clinicAppointmentsSection => 'உங்கள் மருத்துவமனையிலிருந்து';

  @override
  String get noClinicAppointments =>
      'உங்கள் மருத்துவமனையிலிருந்து வரவிருக்கும் சந்திப்புகள் இதுவரை இல்லை.';

  @override
  String get clinicAppointmentBadge => 'உங்கள் மருத்துவமனையால் அமைக்கப்பட்டது';

  @override
  String fastingRequiredNote(int hours) {
    return '⚠ உண்ணாவிரதம் தேவை: உங்கள் சந்திப்புக்கு $hours மணி நேரத்திற்கு முன்பு';
  }

  @override
  String get fastingRequiredNoteUnspecified =>
      '⚠ உங்கள் சந்திப்புக்கு முன் உண்ணாவிரதம் தேவை — எவ்வளவு நேரம் என்பதை உங்கள் மருத்துவமனையிடம் சரிபார்க்கவும்.';

  @override
  String appointmentReasonLabel(String reason) {
    return 'காரணம்: $reason';
  }

  @override
  String get upcomingAppointments => 'வரவிருக்கும் சந்திப்புகள்';

  @override
  String get noAppointments =>
      'எந்த சந்திப்பும் திட்டமிடப்படவில்லை. ஒவ்வொரு வருகைக்குப் பிறகும் உங்கள் மருத்துவமனை இவற்றைச் சேர்க்கும்.';

  @override
  String get notificationsDisabledNote =>
      'அறிவிப்புகள் முடக்கப்பட்டுள்ளன, எனவே நினைவூட்டல்கள் உங்களை எச்சரிக்காது.';

  @override
  String get notificationsPermanentlyDeniedNote =>
      'அறிவிப்புகள் முன்னர் மறுக்கப்பட்டன, எனவே Android அந்த கோரிக்கையை மீண்டும் காட்டாது — அவற்றை இயக்க அமைப்புகளைத் திறக்கவும்.';

  @override
  String get enableAction => 'இயக்கு';

  @override
  String get sendTestNotification => 'இப்போது ஒரு சோதனை அறிவிப்பை அனுப்பு';

  @override
  String get testNotificationTitle => 'சோதனை அறிவிப்பு';

  @override
  String get testNotificationBody =>
      'இதை நீங்கள் காண முடிந்தால், மருந்து மற்றும் சந்திப்பு நினைவூட்டல்கள் இதே வழியில் வேலை செய்யும்.';

  @override
  String get testNotificationSentSnack =>
      'சோதனை அறிவிப்பு அனுப்பப்பட்டது — உங்கள் அறிவிப்பு பட்டியை சரிபார்க்கவும்.';

  @override
  String get testNotificationFailedSnack =>
      'சோதனை அறிவிப்பை அனுப்ப முடியவில்லை. இந்த பயன்பாட்டிற்கு அறிவிப்புகள் இயக்கப்பட்டுள்ளதா எனச் சரிபார்க்கவும்.';

  @override
  String get addAppointmentAction => 'சேர்';

  @override
  String get addAppointmentTitle => 'சந்திப்பு நினைவூட்டலைச் சேர்';

  @override
  String get appointmentLabelField => 'இந்த சந்திப்பு எதற்காக?';

  @override
  String get pickDateTime => 'தேதி & நேரத்தைத் தேர்ந்தெடுக்கவும்';

  @override
  String get bookViaMySejahtera =>
      '📅 MySejahtera மூலம் சந்திப்பை பதிவு செய்யவும்';

  @override
  String get mySejahteraNote =>
      'நிறுவப்பட்டிருந்தால் MySejahtera பயன்பாட்டைத் திறக்கும், இல்லையெனில் அதன் Play Store பட்டியலைத் திறக்கும்.';

  @override
  String get mySejahteraLaunchFailed =>
      'MySejahtera அல்லது மாற்று வழியைத் திறக்க முடியவில்லை. உலாவி நிறுவப்பட்டுள்ளதா?';

  @override
  String get apiSettingsTitle => 'API அமைப்புகள்';

  @override
  String get backendUrlLabel => 'பின்தள API முகவரி';

  @override
  String get backendUrlDesc =>
      'உங்கள் பின்தள சேவையகத்திற்கு பயன்பாட்டை இணைக்கவும். Cloudflare டன்னலைத் தொடங்கியவுடன் (trycloudflare.com முகவரி ஒவ்வொரு முறையும் மறுதொடக்கம் செய்யும்போது மாறும்) — பயன்பாட்டை மீண்டும் உருவாக்காமல் புதிய முகவரியை இங்கே ஒட்டவும்.';

  @override
  String get apiBaseUrlFieldLabel => 'API முகவரி';

  @override
  String get save => 'சேமி';

  @override
  String get resetToDefault => 'இயல்புநிலைக்கு மீட்டமை';

  @override
  String currentlyActive(String url) {
    return 'தற்போது பயன்பாட்டில்: $url';
  }

  @override
  String compileTimeDefault(String url) {
    return 'தொகுப்பு-நேர இயல்புநிலை: $url';
  }

  @override
  String get usingOverride => 'இயக்க-நேர மாற்று முகவரி பயன்படுத்தப்படுகிறது.';

  @override
  String get usingDefault => 'தொகுப்பு-நேர இயல்புநிலை பயன்படுத்தப்படுகிறது.';

  @override
  String get emulatorNote =>
      '10.0.2.2 என்பது Android எமுலேட்டர் உங்கள் கணினியின் localhost-ஐ அணுக பயன்படுத்தும் சிறப்பு முகவரி. இயற்பியல் மொபைலில், உங்கள் கணினியின் LAN IP (எ.கா. http://192.168.1.42:8000) அல்லது டன்னல் முகவரியைப் பயன்படுத்தவும் — மொபைலும் பின்தள சேவையகமும் ஒன்றையொன்று அணுக முடிய வேண்டும்.';

  @override
  String savedSnack(String url) {
    return 'API முகவரி $url ஆக அமைக்கப்பட்டது';
  }

  @override
  String get resetSnack => 'தொகுப்பு-நேர இயல்புநிலைக்கு மீட்டமைக்கப்பட்டது.';

  @override
  String get seniorModeToggleLabel => 'மூத்த குடிமக்கள் பயன்முறை';

  @override
  String get seniorModeToggleDesc =>
      'பெரிய எழுத்துகள் மற்றும் குறைவான தேர்வுகளுடன் எளிமையான காட்சி';

  @override
  String get languageLabel => 'மொழி';

  @override
  String get settingsTitle => 'அமைப்புகள்';

  @override
  String get themeLabel => 'தீம்';

  @override
  String get themeModeLight => 'வெளிர் நிறம்';

  @override
  String get themeModeDark => 'இருள் நிறம்';

  @override
  String get themeModeSystem => 'சாதன இயல்புநிலை';

  @override
  String get auditLogTitle => 'எனது பதிவை யார் பார்த்தார்கள்';

  @override
  String get noAccessLogged =>
      'உங்கள் பதிவிற்கு இதுவரை எந்த அணுகலும் பதிவு செய்யப்படவில்லை.';

  @override
  String fieldsLabel(String fields) {
    return 'தகவல்கள்: $fields';
  }

  @override
  String get auditActorSystemFallback => 'கணினி';

  @override
  String get auditActorEmergencyResponderUnverified =>
      'அவசர பதிலளிப்பாளர் — சுய-அறிவிப்பு, சரிபார்க்கப்படவில்லை';

  @override
  String get auditLogLegendIntro =>
      'நிறமும் சின்னமும் ஒவ்வொரு அணுகலின் முக்கியத்துவத்தைக் காட்டுகின்றன:';

  @override
  String get auditSeverityRoutine => 'வழக்கமான';

  @override
  String get auditSeverityAttention => 'அவசர அணுகல்';

  @override
  String get auditSeverityCritical => 'தோல்வியுற்ற முயற்சி';

  @override
  String get responderScanTitle => 'அவசர அட்டையை ஸ்கேன் செய்';

  @override
  String get responderScanDesc =>
      'நோயாளியின் அவசர QR குறியீட்டை ஸ்கேன் செய்யவும், அவர்களின் உடல் NFC அட்டையைத் தொடவும், அல்லது அச்சிடப்பட்ட அட்டை குறிப்பு / NFC UID-ஐ தட்டச்சு செய்யவும். உள்நுழைவு தேவையில்லை — இது பின்தளத்தால் வடிவமைக்கப்பட்டதே.';

  @override
  String get cardReferenceLabel => 'அட்டை குறிப்பு எண்';

  @override
  String get cardReferenceHint => 'எ.கா. அவசர பக்கத்திலிருந்து';

  @override
  String get responderNameLabel => 'பதிலளிப்பாளர் பெயர் (விருப்பம்)';

  @override
  String get responderOrgLabel => 'பதிலளிப்பாளர் நிறுவனம் (விருப்பம்)';

  @override
  String get scanButton => 'தேடு';

  @override
  String get scanning => 'தேடுகிறது…';

  @override
  String get scanModeQr => 'QR ஸ்கேன்';

  @override
  String get scanModeNfc => 'NFC தொடு';

  @override
  String get scanModeManual => 'கைமுறையாக தட்டச்சு';

  @override
  String get nfcUidLabel => 'NFC அட்டை UID';

  @override
  String get cameraPermissionDenied =>
      'கேமரா அனுமதி மறுக்கப்பட்டது, எனவே QR ஸ்கேனரைத் தொடங்க முடியவில்லை. இதைப் பயன்படுத்த கணினி அமைப்புகளில் கேமரா அணுகலை வழங்கவும்.';

  @override
  String get openAppSettings => 'அமைப்புகளைத் திற';

  @override
  String get nfcUnsupportedPlatform =>
      'இந்த பயன்பாட்டில் NFC ஸ்கேனிங் Android-இல் மட்டுமே ஆதரிக்கப்படுகிறது.';

  @override
  String get nfcUnsupportedDevice => 'இந்த சாதனத்தில் NFC வன்பொருள் இல்லை.';

  @override
  String get nfcDisabled =>
      'இந்த சாதனத்தில் NFC அணைக்கப்பட்டுள்ளது. கணினி அமைப்புகளில் அதை இயக்கவும், பின்னர் இந்த திரைக்குத் திரும்பவும்.';

  @override
  String get nfcReadyToTap =>
      'தயார் — அட்டையை தொலைபேசியின் பின்புறத்தில் வைக்கவும்';

  @override
  String get nfcStarting => 'NFC தொடங்குகிறது…';

  @override
  String get scanResultFoundTitle => 'நோயாளி கண்டறியப்பட்டார்';

  @override
  String scanResultAgeValue(String age) {
    return 'வயது: $age';
  }

  @override
  String get scanResultBloodTypeUnknown => 'பதிவில் இல்லை';

  @override
  String scanResultOmittedMedications(int count) {
    return '+$count மேலும் மருந்துகள் பதிவில் உள்ளன, இங்கே காட்டப்படவில்லை — அவசரகால முக்கியமானதாகக் குறிக்கப்படவில்லை.';
  }

  @override
  String scanResultOmittedConditions(int count) {
    return '+$count மேலும் நோய் நிலைகள் பதிவில் உள்ளன, இங்கே காட்டப்படவில்லை — அவசரகால முக்கியமானதாகக் குறிக்கப்படவில்லை.';
  }

  @override
  String scanResultOmittedAllergies(int count) {
    return '+$count மேலும் ஒவ்வாமைகள் பதிவில் உள்ளன, இங்கே காட்டப்படவில்லை — அவசரகால முக்கியமானதாகக் குறிக்கப்படவில்லை.';
  }

  @override
  String get scanResultOfflineBanner =>
      'ஆஃப்லைன் — கார்டிலிருந்து நேரடியாகப் படிக்கப்பட்டது, நெட்வொர்க் இல்லை. காலாவதியாக இருக்கலாம்; பெயரும் வயதும் கார்டில் சேமிக்கப்படவில்லை.';

  @override
  String get scanResultOfflinePlaceholderName =>
      'கார்டு வைத்திருப்பவர் (ஆஃப்லைன் வாசிப்பு)';

  @override
  String get mfaTitle => 'இரு-படி சரிபார்ப்பு';

  @override
  String get mfaPrompt =>
      'உங்கள் அங்கீகரிப்பு செயலியின் 6 இலக்கக் குறியீட்டை அல்லது ஒரு மீட்புக் குறியீட்டை உள்ளிடவும்.';

  @override
  String get mfaCodeLabel => 'குறியீடு';

  @override
  String get mfaVerifyButton => 'சரிபார்';

  @override
  String get mfaCancelButton => 'உள்நுழைவுக்குத் திரும்பு';

  @override
  String get mfaEmailButton => 'மின்னஞ்சலில் குறியீட்டைப் பெறு';

  @override
  String mfaEmailSent(String hint) {
    return '6 இலக்கக் குறியீட்டை $hint க்கு மின்னஞ்சல் செய்துள்ளோம். இது 10 நிமிடங்களில் காலாவதியாகும்.';
  }

  @override
  String get mfaEmailCodeLabel => 'மின்னஞ்சல் குறியீடு';

  @override
  String get mfaUseAuthenticatorButton =>
      'என் அங்கீகரிப்பு செயலியைப் பயன்படுத்து';

  @override
  String get mfaEmailPrompt =>
      'நாங்கள் மின்னஞ்சலில் அனுப்பிய 6 இலக்கக் குறியீட்டை உள்ளிடவும்.';

  @override
  String get mfaWrongCodeHint =>
      'அந்தக் குறியீடு ஏற்கப்படவில்லை. குறியீடுகள் 30 விநாடிகளுக்கு ஒருமுறை மாறும், ஒருமுறை மட்டுமே செல்லும். அடுத்த குறியீட்டுக்குக் காத்திருக்கவும், தொலைபேசியின் நேரம் தானியங்கியாக இருப்பதை உறுதிசெய்யவும் அல்லது மின்னஞ்சலில் குறியீட்டைப் பெறவும்.';

  @override
  String get nfcBasicTagWarning =>
      'இந்த டேக் வகை (NTAG213/215/216) செயல்படும், ஆனால் சேதப்படுத்த முடியாத வாசிப்பு கவுண்டர் இல்லை: அதன் ஆஃப்லைன் வாசிப்புகளில் விடுபட்டவற்றைச் சரிபார்க்க முடியாது. பொறுப்புக்கூறல் முக்கியமெனில் NTAG 424 DNA பயன்படுத்தவும்.';

  @override
  String get scanResultOfflineSignIn =>
      'இணைப்பு இல்லை, இந்த டேக் பாதுகாக்கப்பட்டுள்ளது. ஆஃப்லைனில் படிக்க CLARION ஊழியர்/பதிலளிப்பவர் கணக்கில் உள்நுழையவும், அல்லது QR குறியீடு / ஆன்லைன் தேடலைப் பயன்படுத்தவும்.';

  @override
  String get scanResultOfflineKeyMissing =>
      'இணைப்பு இல்லை, இந்தச் சாதனத்தில் இந்த டேக்கிற்கான விசை இல்லை. உள்நுழைந்த நிலையில் ஒருமுறை இணைத்து அதைப் பதிவிறக்கவும், அல்லது QR குறியீடு / ஆன்லைன் தேடலைப் பயன்படுத்தவும்.';

  @override
  String get scanResultOfflineRevoked =>
      'இந்த கார்டு ரத்து செய்யப்பட்டுள்ளது; படிக்க முடியாது. இதை நம்ப வேண்டாம்; QR குறியீடு அல்லது ஆன்லைன் தேடலைப் பயன்படுத்தி, கார்டைப் புகாரளிக்கவும்.';

  @override
  String get offlineUnlockReason =>
      'இந்த கார்டை ஆஃப்லைனில் படிக்க உங்கள் அடையாளத்தை உறுதிப்படுத்தவும்';

  @override
  String get scanResultOfflineLockRequired =>
      'இந்த தொலைபேசியில் திரைப் பூட்டு இல்லை, எனவே கார்டை ஆஃப்லைனில் படிக்க முடியாது. தொலைபேசி அமைப்புகளில் PIN, பேட்டர்ன் அல்லது கைரேகையை அமைக்கவும், அல்லது QR குறியீடு அல்லது ஆன்லைன் தேடலைப் பயன்படுத்தவும்.';

  @override
  String get scanResultOfflineAuthFailed =>
      'அடையாளச் சரிபார்ப்பு ரத்து செய்யப்பட்டது அல்லது தோல்வியடைந்தது, எனவே கார்டு ஆஃப்லைனில் படிக்கப்படவில்லை. கார்டை மீண்டும் தட்டி, கைரேகை, முகம் அல்லது PIN மூலம் உறுதிப்படுத்தவும்.';

  @override
  String get scanResultOfflineExpired =>
      'இந்த டேக்கின் செல்லுபடியாகும் காலம் முடிந்துவிட்டது; ஆஃப்லைனில் படிக்க முடியாது. QR குறியீடு அல்லது ஆன்லைன் தேடலைப் பயன்படுத்தி, கார்டை மீண்டும் வழங்கவும்.';

  @override
  String get scanResultOfflineDamaged =>
      'இந்த டேக்கைச் சரிபார்க்க முடியவில்லை (சேதம், மாற்றம், அல்லது உண்மையான CLARION டேக் அல்ல). இதை நம்ப வேண்டாம் - QR குறியீடு அல்லது ஆன்லைன் தேடலைப் பயன்படுத்தவும்.';

  @override
  String get writeOfflineTagTooltip =>
      'ஆஃப்லைன் டேக் எழுதவும் (பணியாளர் மட்டும்)';

  @override
  String get writeOfflineTagTitle => 'ஆஃப்லைன் டேக் எழுதவும்';

  @override
  String get writeOfflineTagDesc =>
      'வலை பணியகத்தில் NFC கார்டை பதிவு செய்த பிறகு காட்டப்படும் உரையை ஒட்டவும், பின்னர் அதே பௌதீக கார்டைத் தொட்டு நேரடியாக டேக்கில் எழுதவும். எழுதப்பட்டதும், அந்த கார்டின் முக்கிய தகவல்களை நெட்வொர்க் இல்லாமல் — இந்த ஆப்பாலோ எந்த நிலையான NFC ரீடராலோ — படிக்க முடியும்.';

  @override
  String get writeOfflineTagTextLabel => 'ஆஃப்லைன் டேக் உரை';

  @override
  String get writeOfflineTagButton => 'எழுத கார்டைத் தொடவும்';

  @override
  String get writeOfflineTagWriting =>
      'தொலைபேசியின் பின்பக்கத்தில் கார்டைப் பிடிக்கவும்…';

  @override
  String get writeOfflineTagSuccess =>
      'எழுதப்பட்டது. இந்த கார்டு இப்போது அதன் முக்கிய தகவல்களை ஆஃப்லைனில் கொண்டுள்ளது.';

  @override
  String get writeOfflineTagNotNdef =>
      'இந்த டேக் NDEF ஐ ஆதரிக்கவில்லை — வேறு பௌதீக கார்டை முயற்சிக்கவும்.';

  @override
  String get writeOfflineTagNotWritable =>
      'இந்த டேக் படிக்க மட்டும் (பூட்டப்பட்டது), எழுத முடியாது.';

  @override
  String get writeOfflineTagTooLarge =>
      'இந்த உரை இந்த டேக்கின் நினைவகத்திற்கு மிகப் பெரியது. குறைவான புலங்களுடன் மீண்டும் பதிவு செய்யவும், அல்லது அதிக கொள்ளளவு கொண்ட டேக்கைப் பயன்படுத்தவும்.';

  @override
  String get writeOfflineTagNotEncrypted =>
      'வலை கன்சோலில் இருந்து பெற்ற மறைகுறியாக்கப்பட்ட பதிவை மட்டுமே எழுத முடியும். C1. என்று தொடங்கும் உரையை ஒட்டி மீண்டும் முயலவும்.';

  @override
  String get writeOfflineTagWriteFailed =>
      'டேக்கில் எழுதுவது தோல்வியடைந்தது. மீண்டும் தொட்டு முயற்சிக்கவும், கார்டை உறுதியாகப் பிடிக்கவும்.';

  @override
  String seniorBloodType(String type) {
    return 'இரத்த வகை: $type';
  }

  @override
  String seniorAllergicTo(String allergy) {
    return 'ஒவ்வாமை: $allergy';
  }

  @override
  String get seniorEmergencyTile => '🚨\nஅவசர\nஅட்டை';

  @override
  String get seniorMedsTile => '💊\nஎனது\nமருந்துகள்';

  @override
  String get switchToStandard => 'இயல்பு பயன்முறைக்கு மாறு';

  @override
  String get signOutSenior => 'வெளியேறு';

  @override
  String get seniorLanguageTitle => 'மொழியை மாற்று';

  @override
  String get seniorEmergencyTitle => 'அவசர அட்டை';

  @override
  String get preparingCard => 'உங்கள் அட்டையை தயார் செய்கிறது…';

  @override
  String get showToResponder => 'இதை மருத்துவ\nமுதலுதவியாளரிடம் காட்டவும்';

  @override
  String refLabel(String ref) {
    return 'எண்: $ref';
  }

  @override
  String get getNewCard => 'புதிய அட்டையைப் பெறு';

  @override
  String get tryAgain => 'மீண்டும் முயற்சி செய்';

  @override
  String get seniorMedsTitle => 'எனது மருந்துகள்';

  @override
  String get noMedsRecord => 'மருந்துகள் எதுவும் பதிவு செய்யப்படவில்லை.';

  @override
  String get takeTwiceDaily =>
      'நாளொன்றுக்கு இருமுறை உட்கொள்ளவும்: காலை 8 மணி மற்றும் இரவு 8 மணி';

  @override
  String fromFacility(String facility) {
    return '$facility இலிருந்து';
  }

  @override
  String get yourClinic => 'உங்கள் மருத்துவமனை';

  @override
  String get nfcCardSectionTitle => 'உடல் NFC அட்டை';

  @override
  String nfcCardActiveLine(String uid) {
    return 'அட்டை $uid — செயலில்';
  }

  @override
  String nfcCardRevokedLine(String uid) {
    return 'அட்டை $uid — ரத்து செய்யப்பட்டது';
  }

  @override
  String get editProfileTitle => 'சுயவிவரத்தைத் திருத்து';

  @override
  String get readOnlyFieldsNote =>
      'உங்கள் பெயர், பிறந்த தேதி, மற்றும் அடையாள அட்டை எண்ணை இங்கே மாற்ற முடியாது. இவற்றைத் திருத்த உங்கள் மருத்துவமனையைத் தொடர்பு கொள்ளவும்.';

  @override
  String get fullNameLabel => 'முழுப் பெயர்';

  @override
  String get editableProfileSectionTitle => 'தொடர்பு விவரங்கள்';

  @override
  String get profileEmailLabel => 'மின்னஞ்சல்';

  @override
  String get profilePhoneLabel => 'தொலைபேசி';

  @override
  String get emergencyContactSectionTitle => 'அவசர தொடர்பு';

  @override
  String get emergencyContactNameLabel => 'அவசர தொடர்பு பெயர்';

  @override
  String get emergencyContactPhoneLabel => 'அவசர தொடர்பு தொலைபேசி';

  @override
  String get emergencyContactRelationshipLabel => 'உங்களுடனான உறவு';

  @override
  String get saveProfileButton => 'மாற்றங்களைச் சேமி';

  @override
  String get profileUpdatedSnack => 'உங்கள் சுயவிவரம் புதுப்பிக்கப்பட்டது.';

  @override
  String get profileUpdateFailedGeneric =>
      'உங்கள் சுயவிவரத்தைப் புதுப்பிக்க முடியவில்லை. மீண்டும் முயற்சிக்கவும்.';

  @override
  String get missingProfileBannerText =>
      'உங்கள் சுயவிவரத்தில் சில விவரங்கள் இல்லை — அதை முடிக்க தட்டவும்.';

  @override
  String get dismiss => 'நிராகரி';

  @override
  String get unexpectedErrorGeneric =>
      'ஏதோ தவறு நடந்தது. மீண்டும் முயற்சிக்கவும்.';

  @override
  String get queueStatusButton => 'வரிசை நிலை';

  @override
  String get queueStatusTitle => 'உங்கள் வரிசை நிலை';

  @override
  String yourNumberLabel(String number) {
    return 'உங்கள் எண்: $number';
  }

  @override
  String nowServingLabel(String number) {
    return 'தற்போது சேவை செய்யப்படும் எண்: $number';
  }

  @override
  String get nowServingNoneYet => 'இன்னும் எண் அழைக்கப்படவில்லை';

  @override
  String peopleAheadLabel(String count) {
    return 'உங்களுக்கு முன் $count பேர் உள்ளனர்';
  }

  @override
  String get queueTicketDetailsTitle => 'டிக்கெட் விவரங்கள்';

  @override
  String get queueStatusLabel => 'நிலை';

  @override
  String get queueFacilityLabel => 'மருத்துவமனை';

  @override
  String get queueDepartmentLabel => 'துறை';

  @override
  String get queueReasonLabel => 'காரணம்';

  @override
  String get queueStatusWaiting => 'காத்திருக்கிறது';

  @override
  String get queueStatusCalled => 'அழைக்கப்பட்டது';

  @override
  String get queueStatusDone => 'முடிந்தது';

  @override
  String get queueStatusCancelled => 'ரத்து செய்யப்பட்டது';

  @override
  String get noActiveQueueTicketTitle => 'செயலில் உள்ள வரிசை டிக்கெட் இல்லை';

  @override
  String get noActiveQueueTicketDesc =>
      'வரிசை எண்ணைப் பெற வரவேற்பறையில் பதிவு செய்யவும்.';

  @override
  String get bookAppointmentTitle => 'சந்திப்பு பதிவு செய்யவும்';

  @override
  String get bookAppointmentGenericError =>
      'பதிவை முடிக்க முடியவில்லை. மீண்டும் முயற்சிக்கவும்.';

  @override
  String get scanCheckinButton => 'பதிவு செய்ய ஸ்கேன் செய்';

  @override
  String get scanCheckinTitle => 'பதிவு செய்ய ஸ்கேன் செய்';

  @override
  String get scanCheckinDesc =>
      'வரவேற்பறையின் சுய-பதிவு நிலையத்தில் உள்ள QR குறியீட்டை ஸ்கேன் செய்யவும், அல்லது அதன் குறியீட்டை கீழே தட்டச்சு செய்யவும். ஊழியர் உதவி தேவையில்லை — உடனடியாக வரிசை எண் கிடைக்கும்.';

  @override
  String get checkinReasonLabel => 'வருகைக்கான காரணம் (விருப்பத்தேர்வு)';

  @override
  String get checkinReasonHint => 'எ.கா. பின்தொடர் வருகை, இரத்த பரிசோதனை';

  @override
  String get stationCodeLabel => 'நிலைய குறியீடு';

  @override
  String get stationCodeHint =>
      'எ.கா. வரவேற்பு கவுன்ட்டரில் அச்சிடப்பட்ட குறியீடு';

  @override
  String get checkinSubmitButton => 'பதிவு செய்';

  @override
  String get checkinSubmitting => 'பதிவு செய்கிறது…';

  @override
  String get requestRescheduleButton => 'மறு அட்டவணை கோரிக்கை';

  @override
  String get rescheduleDialogTitle => 'மறு அட்டவணை கோரிக்கை';

  @override
  String get rescheduleDialogDesc =>
      'இந்த சந்திப்புக்கு உங்களால் வர முடியாது என்பதை உங்கள் கிளினிக்கிற்குத் தெரியப்படுத்துங்கள். அவர்கள் உங்கள் கோரிக்கையை மதிப்பாய்வு செய்து உங்களைத் தொடர்புகொள்வார்கள்.';

  @override
  String get rescheduleReasonScheduleConflict => 'அட்டவணை முரண்பாடு';

  @override
  String get rescheduleReasonUnwell => 'உடல்நலக்குறைவு / பயணிக்க முடியாது';

  @override
  String get rescheduleReasonTransport => 'போக்குவரத்து பிரச்சினை';

  @override
  String get rescheduleReasonOther => 'மற்றவை';

  @override
  String get rescheduleOtherReasonLabel => 'உங்கள் காரணத்தை விவரிக்கவும்';

  @override
  String get rescheduleOtherReasonRequired => 'உங்கள் காரணத்தை விவரிக்கவும்.';

  @override
  String get rescheduleSubmitButton => 'கோரிக்கையை சமர்ப்பி';

  @override
  String get rescheduleSubmitting => 'சமர்ப்பிக்கிறது…';

  @override
  String get reschedulePendingNote =>
      'மறு அட்டவணை கோரப்பட்டது — கிளினிக்கின் பதிலுக்காக காத்திருக்கிறது';

  @override
  String get rescheduleAcceptedNote =>
      'உங்கள் மறு அட்டவணை கோரிக்கை ஏற்கப்பட்டது.';

  @override
  String get rescheduleRejectedNote =>
      'உங்கள் மறு அட்டவணை கோரிக்கை நிராகரிக்கப்பட்டது.';

  @override
  String rescheduleClinicianNoteLabel(String note) {
    return 'கிளினிக் குறிப்பு: $note';
  }

  @override
  String previouslyScheduledLabel(String date) {
    return 'முன்னர்: $date';
  }

  @override
  String get seniorMenuTooltip => 'மெனு';

  @override
  String get seniorMenuTitle => 'மெனு';

  @override
  String get seniorThemeToggleTooltip => 'நிற தீம் மாற்று';

  @override
  String get confirmSwitchToStandardTitle => 'நிலையான காட்சிக்கு மாறவா?';

  @override
  String get confirmSwitchToStandardBody =>
      'நீங்கள் மூத்த குடிமக்கள் பயன்முறையிலிருந்து வெளியேறி வழக்கமான பயன்பாட்டைப் பார்ப்பீர்கள். அமைப்புகளில் இருந்து எப்போது வேண்டுமானாலும் மூத்த குடிமக்கள் பயன்முறையை மீண்டும் இயக்கலாம்.';

  @override
  String get confirmSwitchToStandardAction => 'ஆம், மாற்று';

  @override
  String get confirmSignOutTitle => 'வெளியேறவா?';

  @override
  String get confirmSignOutBody =>
      'உங்கள் சுகாதார பதிவைப் பார்க்க நீங்கள் மீண்டும் உள்நுழைய வேண்டும்.';

  @override
  String get confirmSignOutAction => 'ஆம், வெளியேறு';

  @override
  String get myBills => 'என் பில்கள்';

  @override
  String get billsEmpty => 'உங்களுக்கு பில்கள் எதுவும் இல்லை.';

  @override
  String get paymentHistory => 'கட்டண வரலாறு';

  @override
  String billToPay(String amount) {
    return 'செலுத்த வேண்டியது $amount';
  }

  @override
  String get billInsurerPending => 'உங்கள் காப்பீட்டாளருக்காக காத்திருக்கிறது';

  @override
  String get billPaidInFull => 'முழுமையாக செலுத்தப்பட்டது';

  @override
  String get billItems => 'பொருட்கள்';

  @override
  String get payNow => 'இப்போது செலுத்துங்கள்';

  @override
  String get payAmountLabel => 'செலுத்த வேண்டிய தொகை (RM)';

  @override
  String get payContinue => 'தொடரவும்';

  @override
  String get payInvalidAmount =>
      'RM இல் தொகையை உள்ளிடவும், எடுத்துக்காட்டாக 25.00.';

  @override
  String payTooMuch(String amount) {
    return 'நீங்கள் அதிகபட்சம் $amount மட்டுமே செலுத்த முடியும்.';
  }

  @override
  String get paySimulatedNotice =>
      'இது மாதிரி கட்டணப் பக்கம். இது டெமோ நுழைவாயில்: உண்மையான பணம் எதுவும் நகராது.';

  @override
  String get payApprove => 'கட்டணத்தை அங்கீகரிக்கவும்';

  @override
  String get payDecline => 'கட்டணத்தை நிராகரிக்கவும்';

  @override
  String get payCancel => 'கட்டணத்தை ரத்து செய்யவும்';

  @override
  String get paySecurely => 'பாதுகாப்பாகப் பணம் செலுத்துங்கள்';

  @override
  String payDeclined(String reason) {
    return '$reason உங்களிடம் கட்டணம் வசூலிக்கப்படவில்லை.';
  }

  @override
  String receiptTitle(String number) {
    return 'ரசீது $number';
  }

  @override
  String get receiptVoided => 'இந்த கட்டணம் செல்லாதாக்கப்பட்டது.';

  @override
  String get receiptEmail => 'ரசீதை மின்னஞ்சல் செய்';

  @override
  String get receiptSharePdf => 'PDF ஐப் பகிர்';

  @override
  String receiptEmailSent(String to) {
    return 'ரசீது $to க்கு அனுப்பப்பட்டது.';
  }

  @override
  String get cancel => 'ரத்து செய்';

  @override
  String get close => 'மூடு';

  @override
  String get navHome => 'முகப்பு';

  @override
  String get navCare => 'பராமரிப்பு';

  @override
  String get navScan => 'ஸ்கேன்';

  @override
  String get navQueue => 'வரிசை';

  @override
  String get navProfile => 'சுயவிவரம்';

  @override
  String get scanHubNotClarion =>
      'இது CLARION குறியீடு அல்ல. கிளினிக் செக்-இன் குறியீடு அல்லது அவசர அட்டையை ஸ்கேன் செய்யுங்கள்.';

  @override
  String get scanHubQrHint =>
      'கிளினிக் செக்-இன் குறியீடு அல்லது அவசர அட்டை QR-ஐ கேமராவால் காட்டுங்கள்.';

  @override
  String get scanHubUnreadableTag =>
      'இந்த அட்டையைப் படிக்க முடியவில்லை. தொலைபேசியில் அசையாமல் பிடித்து மீண்டும் முயற்சிக்கவும்.';

  @override
  String get scanAnotherCard => 'மற்றொரு அட்டையை ஸ்கேன் செய்';

  @override
  String get responderIdentityTitle => 'ஸ்கேன் செய்பவர் யார்?';

  @override
  String get responderIdentityNote =>
      'உங்கள் பெயர் இந்த தொலைபேசியில் சேமிக்கப்படும்; அட்டையின் அணுகல் பதிவில் பதிவாகும்.';

  @override
  String responderScanningAs(String who) {
    return '$who ஆக ஸ்கேன் செய்கிறீர்கள்';
  }

  @override
  String get responderChange => 'மாற்று';

  @override
  String get responderAdd => 'உங்கள் பெயர் மற்றும் அமைப்பைச் சேர்க்கவும்';

  @override
  String callContactLabel(String name) {
    return '$name ஐ அழைக்கவும்';
  }

  @override
  String get legacyTagWarningTitle => 'பழைய NFC அட்டை';

  @override
  String get legacyTagWarningBody =>
      'இந்த அட்டையில் உள்ள தரவு குறியாக்கம் செய்யப்படவில்லை; நெட்வொர்க் இல்லாமல் மாற்றப்பட்டதா என சரிபார்க்க முடியாது. அட்டையை மீண்டும் வழங்க ஊழியர்களிடம் கேளுங்கள்.';

  @override
  String get bkBannerTitle => 'MySejahtera பயன்படுத்த விரும்புகிறீர்களா?';

  @override
  String get bkBannerNote =>
      'இங்கு முன்பதிவு செய்வது ஆன்லைன் முன்பதிவை இயக்கியுள்ள மருத்துவமனைகளில் மட்டுமே செயல்படும்.';

  @override
  String get bkOpenMySejahtera => 'MySejahtera ஐத் திற';

  @override
  String get bkBookHere => 'இங்கே முன்பதிவு செய்';

  @override
  String get bkChooseCategory => 'உங்களுக்கு என்ன தேவை?';

  @override
  String get bkChooseHospital => 'மருத்துவமனையைத் தேடுங்கள்';

  @override
  String get bkChooseTime => 'தேதி மற்றும் நேரத்தைத் தேர்ந்தெடுங்கள்';

  @override
  String get bkChoosePerson => 'இது யாருக்காக?';

  @override
  String get bkConfirmTitle => 'சரிபார்த்து உறுதிப்படுத்துங்கள்';

  @override
  String get bkCategoriesEmpty => 'தற்போது முன்பதிவு சேவைகள் எதுவும் இல்லை.';

  @override
  String get bkSearchHint => 'மருத்துவமனை பெயர் அல்லது பகுதி';

  @override
  String get bkSearchAction => 'தேடு';

  @override
  String get bkUseMyLocation => 'என் இருப்பிடத்தைப் பயன்படுத்து';

  @override
  String get bkClearLocation => 'இருப்பிடத்தை நிறுத்து';

  @override
  String get bkSortedNearest => 'அருகிலுள்ளவை முதலில்';

  @override
  String get bkLocationDenied =>
      'இருப்பிட அனுமதி மறுக்கப்பட்டது. மருத்துவமனை பெயர் அல்லது பகுதியை உள்ளிடுங்கள், அல்லது தொலைபேசி அமைப்புகளில் இருப்பிடத்தை அனுமதியுங்கள்.';

  @override
  String get bkLocationOff =>
      'இந்த தொலைபேசியில் இருப்பிடம் அணைக்கப்பட்டுள்ளது. அதை இயக்குங்கள், அல்லது மருத்துவமனை பெயர் அல்லது பகுதியை உள்ளிடுங்கள்.';

  @override
  String get bkLocationFailed =>
      'உங்கள் இருப்பிடத்தைக் கண்டறிய முடியவில்லை. மருத்துவமனை பெயர் அல்லது பகுதியை உள்ளிடுங்கள்.';

  @override
  String get bkFacilitiesEmpty =>
      'மருத்துவமனைகள் எதுவும் இல்லை. இந்தச் சேவைக்கு ஆன்லைன் முன்பதிவை இயக்கிய மருத்துவமனைகள் மட்டுமே பட்டியலிடப்படும். வேறு பெயர் அல்லது பகுதியை முயற்சிக்கவும், அல்லது MySejahtera ஐத் திறக்கவும்.';

  @override
  String bkDistanceKm(String km) {
    return '$km கி.மீ தொலைவில்';
  }

  @override
  String bkNextAvailable(String when) {
    return 'அடுத்த வாய்ப்பு: $when';
  }

  @override
  String get bkNoNextAvailable => 'விரைவில் காலியிடம் இல்லை';

  @override
  String get bkDateLabel => 'தேதி';

  @override
  String get bkTimeLabel => 'நேரம்';

  @override
  String get bkNoOpenDays =>
      'இந்த மருத்துவமனையில் அடுத்த 14 நாட்களில் காலியிடம் இல்லை.';

  @override
  String get bkNoSlots =>
      'இந்த நாளில் நேரங்கள் இல்லை. வேறு தேதியைத் தேர்ந்தெடுங்கள்.';

  @override
  String bkSlotsLeft(int count) {
    return '$count மீதம்';
  }

  @override
  String get bkSlotFull => 'நிரம்பியது';

  @override
  String bkDayOpenSemantics(String date, int count) {
    return '$date, $count காலி நேரங்கள்';
  }

  @override
  String bkDayFullSemantics(String date) {
    return '$date, காலி நேரம் இல்லை';
  }

  @override
  String get bkContinue => 'தொடரவும்';

  @override
  String get bkMyself => 'நான்';

  @override
  String get bkMyselfNote => 'நீங்கள் உள்நுழைந்த கணக்கு';

  @override
  String get bkSavedPeople => 'சேமித்த நபர்கள்';

  @override
  String get bkNoPeople =>
      'நீங்கள் இன்னும் யாரையும் சேமிக்கவில்லை. குழந்தை அல்லது பெற்றோரைச் சேர்த்து அவர்களுக்காக முன்பதிவு செய்யுங்கள்.';

  @override
  String get bkAddPerson => 'நபரைச் சேர்';

  @override
  String get bkEditPerson => 'நபரைத் திருத்து';

  @override
  String get bkDelete => 'நீக்கு';

  @override
  String get bkDeletePersonTitle => 'இந்த நபரை நீக்கவா?';

  @override
  String bkDeletePersonBody(String name) {
    return '$name சேமித்த நபர்களிலிருந்து நீக்கப்படுவார். ஏற்கனவே உள்ள சந்திப்புகள் பாதிக்கப்படாது.';
  }

  @override
  String get bkFullName => 'முழுப் பெயர்';

  @override
  String get bkRelationship => 'உறவு';

  @override
  String get bkRelChild => 'குழந்தை';

  @override
  String get bkRelParent => 'பெற்றோர்';

  @override
  String get bkRelSpouse => 'துணைவர்';

  @override
  String get bkRelSibling => 'சகோதரர் அல்லது சகோதரி';

  @override
  String get bkRelRelative => 'உறவினர்';

  @override
  String get bkRelOther => 'மற்றவர்';

  @override
  String get bkPickDob => 'பிறந்த தேதியைத் தேர்ந்தெடுங்கள்';

  @override
  String get bkNric => 'அடையாள அட்டை எண் (விருப்பம்)';

  @override
  String get bkNameRequired => 'முழுப் பெயரை உள்ளிடுங்கள்.';

  @override
  String get bkDobRequired => 'பிறந்த தேதியைத் தேர்ந்தெடுங்கள்.';

  @override
  String get bkSummaryCategory => 'சேவை';

  @override
  String get bkSummaryHospital => 'மருத்துவமனை';

  @override
  String get bkSummaryWhen => 'தேதி மற்றும் நேரம்';

  @override
  String get bkSummaryPerson => 'யாருக்கு';

  @override
  String get bkReasonLabel => 'காரணம் (விருப்பம்)';

  @override
  String get bkConfirmButton => 'முன்பதிவை உறுதிப்படுத்து';

  @override
  String get bkTryAgain => 'மீண்டும் முயற்சி';

  @override
  String get bkSlotTaken =>
      'அந்த நேரம் இப்போதுதான் எடுக்கப்பட்டது. வேறு நேரத்தைத் தேர்ந்தெடுங்கள்.';

  @override
  String get bkNoPatientRecord =>
      'உங்கள் கணக்கு நோயாளி பதிவுடன் இணைக்கப்படவில்லை, எனவே முன்பதிவு செய்ய முடியாது. மருத்துவமனை பதிவு மேசையில் இணைக்கக் கேளுங்கள்.';

  @override
  String get bkNetworkError =>
      'சேவையகத்தை அடைய முடியவில்லை. இணைப்பைச் சரிபார்த்து மீண்டும் முயலுங்கள்.';

  @override
  String get bkSuccessTitle => 'முன்பதிவு உறுதிசெய்யப்பட்டது';

  @override
  String get bkSuccessBody =>
      'உங்கள் சந்திப்பு முன்பதிவு செய்யப்பட்டது. உங்கள் சந்திப்புகளில் பார்க்கலாம்.';

  @override
  String get bkViewAppointments => 'என் சந்திப்புகளைப் பார்';

  @override
  String get bkDone => 'முடிந்தது';

  @override
  String get bkCancelAppointment => 'முன்பதிவை ரத்து செய்';

  @override
  String get bkCancelTitle => 'இந்தச் சந்திப்பை ரத்து செய்யவா?';

  @override
  String get bkCancelBody => 'இந்த நேரம் மற்ற நோயாளிகளுக்கு விடுவிக்கப்படும்.';

  @override
  String get bkKeepAppointment => 'சந்திப்பை வைத்திரு';

  @override
  String get bkCancelled => 'சந்திப்பு ரத்து செய்யப்பட்டது.';

  @override
  String bkForPerson(String name) {
    return '$name க்காக';
  }

  @override
  String get bkCatGeneral => 'பொது ஆலோசனை';

  @override
  String get bkCatChronic => 'தொடர் சிகிச்சை மற்றும் நாள்பட்ட பராமரிப்பு';

  @override
  String get bkCatVaccination => 'தடுப்பூசி';

  @override
  String get bkCatMaternalChild => 'தாய் சேய் நலம்';

  @override
  String get bkCatDental => 'பல் மருத்துவம்';

  @override
  String get bkCatScreening => 'சுகாதார பரிசோதனை';

  @override
  String get bkCatMentalHealth => 'மனநலம் மற்றும் ஆலோசனை';

  @override
  String get bkCatPhysio => 'இயன்முறை சிகிச்சை மற்றும் மறுவாழ்வு';

  @override
  String get emergencyTabQr => 'QR குறியீடு';

  @override
  String get emergencyTabCard => 'அட்டை';

  @override
  String get emergencyDescFixed =>
      'முதலுதவியாளர் உங்கள் QR குறியீட்டை ஸ்கேன் செய்தால் கீழே உள்ள நான்கு விவரங்களை மட்டுமே பார்ப்பார். ஒவ்வொரு ஸ்கேனும் பதிவு செய்யப்படும்; எப்போது வேண்டுமானாலும் குறியீட்டை ரத்து செய்யலாம்.';

  @override
  String get whatWillBeShared => 'பகிரப்படுபவை';

  @override
  String get sharedAlwaysNote =>
      'இவை எப்போதும் சேர்க்கப்படும். உங்கள் பதிவில் உள்ள வேறு எதுவும் பகிரப்படாது.';

  @override
  String get previewTooltip =>
      'முதலுதவியாளர் பார்ப்பதை முன்னோட்டம் பார்க்கவும்';

  @override
  String get previewTitle => 'முதலுதவியாளர் பார்ப்பது';

  @override
  String get previewIntro =>
      'உங்கள் சொந்த பதிவிலிருந்து எடுக்கப்பட்டது. உங்கள் QR குறியீடு ஸ்கேன் செய்யப்படும்போது இதுவே காட்டப்படும். வேறு எதுவும் பகிரப்படாது.';

  @override
  String get previewNone => 'பதிவு இல்லை';

  @override
  String previewOmitted(int count) {
    return 'முக்கியமெனக் குறிக்கப்படாத மேலும் $count விவரங்கள் காட்டப்படாது.';
  }

  @override
  String get regenerateButton => 'QR குறியீட்டை மீண்டும் உருவாக்கு';

  @override
  String get cardStatusActive => 'செயலில்';

  @override
  String get cardStatusExpired => 'காலாவதியானது';

  @override
  String get cardStatusRevoked => 'ரத்து செய்யப்பட்டது';

  @override
  String cardEndingIn(String last4) {
    return '••••$last4 இல் முடியும் அட்டை';
  }

  @override
  String get shareCardImage => 'அட்டை படத்தைப் பகிர்';

  @override
  String get shareCardFailed => 'அட்டை படத்தைப் பகிர முடியவில்லை.';

  @override
  String get cardOutdatedTitle => 'பழைய NFC சிப்';

  @override
  String cardOutdatedBody(String date) {
    return 'இந்த அட்டை, மாற்ற முடியாத வாசிப்பு எண்ணி இல்லாத பழைய சிப்பைப் பயன்படுத்துகிறது. புதிய அட்டைக்கு கிளினிக் ஊழியரிடம் கேளுங்கள். இது $date அன்று காலாவதியாகும்.';
  }

  @override
  String get cardInfoTitle => 'அட்டை விவரங்கள்';

  @override
  String get cardChipLabel => 'சிப் வகை';

  @override
  String get chipNtag21x => 'NTAG213/215/216 (பழைய சிப்)';

  @override
  String get chipNtag424 => 'NTAG 424 DNA';

  @override
  String get chipUnknown => 'தெரியாத சிப்';

  @override
  String get cardRegisteredLabel => 'பதிவு செய்த நாள்';

  @override
  String get cardValidUntilLabel => 'செல்லுபடியாகும் வரை';

  @override
  String cardDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days நாட்கள் மீதம்',
      one: '1 நாள் மீதம்',
      zero: 'இன்று காலாவதியாகும்',
    );
    return '$_temp0';
  }

  @override
  String get cardSharesLabel => 'பகிர்வவை';

  @override
  String get cardHistoryTitle => 'வரலாறு';

  @override
  String get cardHistoryEmpty =>
      'இந்த அட்டைக்கு இன்னும் செயல்பாடு எதுவும் பதிவாகவில்லை.';

  @override
  String get cardHistoryError => 'இந்த அட்டையின் வரலாற்றை ஏற்ற முடியவில்லை.';

  @override
  String get cardEventRegistered => 'பதிவு செய்யப்பட்டது';

  @override
  String get cardEventRenewed => 'புதுப்பிக்கப்பட்டது';

  @override
  String get cardEventRevoked => 'ரத்து செய்யப்பட்டது';

  @override
  String get cardEventScanned => 'ஸ்கேன் செய்யப்பட்டது';

  @override
  String cardEventBy(String who) {
    return '$who மூலம்';
  }

  @override
  String get cardsEmptyTitle => 'NFC அட்டை இன்னும் இல்லை';

  @override
  String get cardsEmptyBody =>
      'NFC அட்டைகளை கிளினிக் ஊழியர்களே வழங்குவார்கள். வேண்டுமெனில் கிளினிக் வரவேற்பில் கேளுங்கள். அதுவரை உங்கள் QR குறியீடு செயல்படும்.';

  @override
  String get cardsLoadError => 'உங்கள் NFC அட்டைகளை ஏற்ற முடியவில்லை.';

  @override
  String get dayToday => 'இன்று';

  @override
  String get dayYesterday => 'நேற்று';

  @override
  String daysAgo(int count) {
    return '$count நாட்களுக்கு முன்';
  }

  @override
  String get auditTagAll => 'அனைத்தும்';

  @override
  String get auditTagEmergency => 'அவசர ஸ்கேன்கள்';

  @override
  String get auditTagViews => 'பதிவு பார்வைகள்';

  @override
  String get auditTagChanges => 'மாற்றங்கள்';

  @override
  String get auditTagAccount => 'கணக்கு மற்றும் அட்டைகள்';

  @override
  String get auditTagFailed => 'தோல்வியுற்ற முயற்சிகள்';

  @override
  String get auditNeedsAttention => 'கவனம் தேவை';

  @override
  String auditSummary(int count, String window, int attention) {
    return 'கடந்த $window இல் $count அணுகல்கள், $attention கவனம் தேவை';
  }

  @override
  String get auditWindow7d => '7 நாட்கள்';

  @override
  String get auditWindow30d => '30 நாட்கள்';

  @override
  String get auditWindow1y => 'ஆண்டு';

  @override
  String get auditWindow7y => '7 ஆண்டுகள்';

  @override
  String auditCollapsedCount(int count, String time) {
    return 'x$count, சமீபத்தியது $time';
  }

  @override
  String get auditInfoTooltip => 'தீவிரம் எவ்வாறு காட்டப்படுகிறது';

  @override
  String get auditInfoTitle => 'தீவிரம்';

  @override
  String auditDetailLabel(String detail) {
    return 'விவரம்: $detail';
  }

  @override
  String auditTimesLabel(String times) {
    return 'நேரங்கள்: $times';
  }

  @override
  String get auditNoMatches =>
      'இந்த வடிகட்டிகளுக்குப் பொருந்தும் பதிவுகள் இல்லை.';

  @override
  String get auditClearFilters => 'வடிகட்டிகளை அழி';

  @override
  String get auditLoadError => 'அணுகல் பதிவை ஏற்ற முடியவில்லை.';

  @override
  String get nricScanTitle => 'உங்கள் NRIC ஐ ஸ்கேன் செய்யுங்கள்';

  @override
  String get nricScanHint =>
      'உங்கள் NRIC இன் முன்பக்கத்தை சட்டத்திற்குள் வையுங்கள்';

  @override
  String get nricScanLooking => 'அட்டையைத் தேடுகிறது…';

  @override
  String get nricScanHold => 'அசையாமல் பிடியுங்கள்';

  @override
  String get nricScanTimeout =>
      'அட்டையைப் படிக்க முடியவில்லை. நீங்களே படம் எடுக்க ஷட்டர் பொத்தானை அழுத்துங்கள், அல்லது திரும்பிச் சென்று விவரங்களை தட்டச்சு செய்யுங்கள்.';

  @override
  String get nricScanShutter => 'படம் எடு';

  @override
  String get nricScanTorch => 'டார்ச்';

  @override
  String get nricScanTorchFailed =>
      'இந்த தொலைபேசியில் டார்ச்சை இயக்க முடியவில்லை.';

  @override
  String get nricScanPermission =>
      'கேமரா அணுகல் முடக்கப்பட்டுள்ளது. தொலைபேசி அமைப்புகளில் CLARION க்கு கேமராவை அனுமதியுங்கள், அல்லது திரும்பிச் சென்று விவரங்களை தட்டச்சு செய்யுங்கள்.';

  @override
  String get nricScanNoCamera =>
      'இந்த தொலைபேசியில் கேமரா கிடைக்கவில்லை. திரும்பிச் சென்று விவரங்களை தட்டச்சு செய்யுங்கள்.';

  @override
  String get nricScanCameraFailed =>
      'கேமராவைத் தொடங்க முடியவில்லை. திரும்பிச் சென்று விவரங்களை தட்டச்சு செய்யுங்கள்.';

  @override
  String get nricScanTypeInstead => 'விவரங்களை தட்டச்சு செய்கிறேன்';

  @override
  String get nricScanReviewTitle => 'உங்கள் விவரங்களைச் சரிபாருங்கள்';

  @override
  String get nricScanReviewHint =>
      'தொடர்வதற்கு முன் தவறாகப் படிக்கப்பட்டதைத் திருத்துங்கள்.';

  @override
  String get nricScanUse => 'இந்த விவரங்களைப் பயன்படுத்து';

  @override
  String get nricScanRetake => 'மீண்டும் எடு';

  @override
  String get familyTitle => 'என் குடும்பம்';

  @override
  String get familySwitcherTooltip => 'சுயவிவரத்தை மாற்று';

  @override
  String get familySwitch => 'மாற்று';

  @override
  String get familyYou => 'நீங்கள்';

  @override
  String familyActingFor(String name) {
    return '$name சார்பாக செயல்படுகிறீர்கள்';
  }

  @override
  String get familyBackToMine => 'என் சுயவிவரத்துக்குத் திரும்பு';

  @override
  String get familyAdd => 'குடும்ப உறுப்பினரைச் சேர்';

  @override
  String get familyAddTitle => 'குழந்தை அல்லது பெற்றோரைச் சேர்';

  @override
  String get familyAddAction => 'சேர்';

  @override
  String get familyName => 'முழுப் பெயர்';

  @override
  String get familyDob => 'பிறந்த தேதி';

  @override
  String get familyRelation => 'உறவு';

  @override
  String get familyNameRequired => 'பெயரை உள்ளிடவும்.';

  @override
  String get familyDobRequired => 'பிறந்த தேதியைத் தேர்வு செய்யவும்.';

  @override
  String get familyRelationRequired => 'உறவைத் தேர்வு செய்யவும்.';

  @override
  String familyAge(int age) {
    return '$age வயது';
  }

  @override
  String get familyGuardiansTitle => 'என் கணக்குக்காக யார் செயல்படலாம்';

  @override
  String get familyNoGuardians =>
      'வேறு யாரும் உங்கள் கணக்குக்காகச் செயல்பட முடியாது.';

  @override
  String get familyRemove => 'நீக்கு';

  @override
  String get familyRemoveMinor =>
      'அணுகலை நீக்க 18 வயது அல்லது அதற்கு மேல் இருக்க வேண்டும்.';

  @override
  String get familyLinkRemoved =>
      'அந்த சுயவிவரத்துக்காக இனி செயல்பட முடியாது. உங்கள் சுயவிவரத்துக்குத் திரும்பியது.';

  @override
  String get relChild => 'குழந்தை';

  @override
  String get relMother => 'தாய்';

  @override
  String get relFather => 'தந்தை';

  @override
  String get relGrandmother => 'பாட்டி';

  @override
  String get relGrandfather => 'தாத்தா';

  @override
  String get relGuardian => 'பாதுகாவலர்';

  @override
  String get relOthers => 'மற்றவை';

  @override
  String get familyIcHint =>
      'இந்த குடும்ப உறுப்பினருக்கு கிளினிக்கில் ஏற்கனவே அடையாள அட்டைப் பதிவு இருந்தால், கிளினிக் மேசையில் இணைக்கக் கேளுங்கள்.';

  @override
  String get familyPendingApproval =>
      'அவர்களின் ஒப்புதலுக்காகக் காத்திருக்கிறது';

  @override
  String familyWantsToManage(String name) {
    return '$name உங்கள் கணக்கை நிர்வகிக்க விரும்புகிறார்';
  }

  @override
  String get familyApprove => 'ஒப்புக்கொள்';

  @override
  String get familyEmailActingHint =>
      'மின்னஞ்சலை மாற்ற உங்கள் சுயவிவரத்துக்குத் திரும்பவும்.';

  @override
  String get writeOfflineTagUrlLabel =>
      'பதிவிலிருந்து பொது இணைப்பு (விருப்பம்)';

  @override
  String get writeOfflineTagUrlInvalid =>
      'இணைப்பு சரியாக https://<host>/e/<token> ஆக இருக்க வேண்டும். எதுவும் எழுதப்படவில்லை.';

  @override
  String get writeOfflineTagNoUrlHint =>
      'இணைப்பு இல்லாமல், செயலி இல்லாத தொலைபேசியால் இந்த அட்டையைத் திறக்க முடியாது.';
}
