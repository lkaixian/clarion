// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Tamil (`ta`).
class AppLocalizationsTa extends AppLocalizations {
  AppLocalizationsTa([String locale = 'ta']) : super(locale);

  @override
  String get appTitle => 'MediBridge';

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
  String get signIn => 'உள்நுழைக';

  @override
  String get signingIn => 'உள்நுழைகிறது…';

  @override
  String get demoLoginHint =>
      'டெமோ உள்நுழைவு: patient@medibridge.demo / patient123 (அல்லது அடையாள அட்டை 520314-01-1234 / patient123)';

  @override
  String get loginFailedGeneric =>
      'உள்நுழைவு தோல்வியடைந்தது. உங்கள் விவரங்களை அல்லது அமைப்புகளில் உள்ள API முகவரியை சரிபார்க்கவும்.';

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
  String get scanEmergencyCardButton => '🚨 அவசர QR / NFC அட்டையை ஸ்கேன் செய்';

  @override
  String get scanEmergencyCardSubtitle =>
      'முதலுதவியாளர்களுக்கு — உள்நுழைவு தேவையில்லை';

  @override
  String get orSignInDivider =>
      'அல்லது உங்கள் சொந்த பதிவை நிர்வகிக்க உள்நுழையவும்';

  @override
  String get forgotPasswordButton => 'கடவுச்சொல்லை மறந்துவிட்டீர்களா?';

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
  String get remindersButton => 'மருந்து & சந்திப்பு நினைவூட்டல்கள்';

  @override
  String get whoViewedRecord => 'எனது பதிவை யார் பார்த்தார்கள்?';

  @override
  String get retry => 'மீண்டும் முயற்சி';

  @override
  String get emergencyCardTitle => 'அவசர அட்டை';

  @override
  String get emergencyAccessCardTitle => 'அவசர அணுகல் அட்டை';

  @override
  String get emergencyDesc =>
      'அவசர காலத்தில் முதலுதவியாளர் என்ன பார்க்க முடியும் என்பதைத் தேர்ந்தெடுக்கவும். இந்த QR குறியீடு மூலம் உங்கள் பதிவில் உள்ள வேறு எந்த தகவலும் வெளிப்படுத்தப்படாது — ஒவ்வொரு ஸ்கேனும் பதிவு செய்யப்படும், மேலும் நீங்கள் எப்போது வேண்டுமானாலும் அணுகலை ரத்து செய்யலாம்.';

  @override
  String get fieldsToShare => 'அவசர காலத்தில் பகிரப்பட வேண்டிய தகவல்கள்:';

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
  String get auditLogTitle => 'எனது பதிவை யார் பார்த்தார்கள்';

  @override
  String get noAccessLogged =>
      'உங்கள் பதிவிற்கு இதுவரை எந்த அணுகலும் பதிவு செய்யப்படவில்லை.';

  @override
  String fieldsLabel(String fields) {
    return 'தகவல்கள்: $fields';
  }

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
}
