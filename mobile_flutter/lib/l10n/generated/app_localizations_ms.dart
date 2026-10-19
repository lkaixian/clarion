// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Malay (`ms`).
class AppLocalizationsMs extends AppLocalizations {
  AppLocalizationsMs([String locale = 'ms']) : super(locale);

  @override
  String get appTitle => 'CLARION';

  @override
  String get apiSettingsTooltip => 'Tetapan API';

  @override
  String get back => 'Kembali';

  @override
  String get loginSubtitle =>
      'Rekod kesihatan anda, di mana sahaja anda berada';

  @override
  String get emailLabel => 'E-mel';

  @override
  String get emailOrNricLabel => 'E-mel atau No. Kad Pengenalan';

  @override
  String get passwordLabel => 'Kata Laluan';

  @override
  String get emailOrNricHint => 'nama@contoh.com atau 900101-01-1234';

  @override
  String get loginFieldRequired =>
      'Masukkan e-mel atau No. K/P dan kata laluan anda.';

  @override
  String get mfaResendButton => 'Hantar kod baharu';

  @override
  String mfaResendIn(int seconds) {
    return 'Hantar kod baharu dalam ${seconds}s';
  }

  @override
  String get signIn => 'Log Masuk';

  @override
  String get signingIn => 'Sedang log masuk…';

  @override
  String get loginFailedGeneric =>
      'Log masuk gagal. Semak kelayakan anda atau alamat API dalam Tetapan.';

  @override
  String get sessionExpiredSnackbar =>
      'Anda telah log keluar — sila log masuk semula.';

  @override
  String get seniorPrompt => 'Warga emas atau pengguna baharu?';

  @override
  String get enableSeniorMode => 'Aktifkan Mod Warga Emas →';

  @override
  String get seniorModeWillOpen =>
      'Mod Warga Emas akan dibuka selepas anda log masuk';

  @override
  String get undo => 'Buat asal';

  @override
  String get scanEmergencyCardButton => 'Imbas kad kecemasan (QR atau NFC)';

  @override
  String get scanEmergencyCardSubtitle =>
      'Untuk responden pertama. Tidak perlu log masuk.';

  @override
  String get orSignInDivider => 'atau log masuk untuk urus rekod anda sendiri';

  @override
  String get forgotPasswordButton => 'Lupa kata laluan?';

  @override
  String get selfRegisterLinkPrompt => 'Pertama kali di sini?';

  @override
  String get selfRegisterLinkAction => 'Daftar';

  @override
  String get forgotPasswordTitle => 'Tetapkan Semula Kata Laluan';

  @override
  String get forgotPasswordDesc =>
      'Hanya untuk pesakit. Masukkan No. Kad Pengenalan dan tarikh lahir anda seperti yang tertera pada rekod kesihatan anda, kemudian pilih kata laluan baharu.';

  @override
  String get forgotPasswordStep1Desc =>
      'Hanya untuk pesakit. Masukkan No. Kad Pengenalan anda dan, jika terdapat e-mel dalam rekod akaun anda, kami akan menghantar kod pengesahan kepadanya.';

  @override
  String get sendCodeButton => 'Hantar kod';

  @override
  String get otpRequestedGenericSnack =>
      'Jika No. Kad Pengenalan ini mempunyai e-mel dalam rekod, kod pengesahan telah dihantar kepadanya.';

  @override
  String get otpCodeLabel => 'Kod pengesahan';

  @override
  String get forgotPasswordStep2Desc =>
      'Masukkan kod 6 digit yang kami hantar, kemudian pilih kata laluan baharu.';

  @override
  String get resendCodeButton => 'Tidak menerima kod? Hantar semula';

  @override
  String get resendCodeSentSnack =>
      'Jika No. Kad Pengenalan ini mempunyai e-mel dalam rekod, kod pengesahan baharu telah dihantar.';

  @override
  String get useDifferentNricButton => 'Guna No. Kad Pengenalan lain';

  @override
  String get requestOtpFailedGeneric =>
      'Tidak dapat meminta kod pengesahan. Semak No. Kad Pengenalan anda atau alamat asas API dalam Tetapan.';

  @override
  String get nricLabel => 'No. Kad Pengenalan';

  @override
  String get dateOfBirthLabel => 'Tarikh lahir';

  @override
  String get newPasswordLabel => 'Kata laluan baharu';

  @override
  String get passwordRulesTitle => 'Kata laluan anda mesti mempunyai:';

  @override
  String get passwordRuleLength => 'Sekurang-kurangnya 8 aksara';

  @override
  String get passwordRuleNumber => 'Sekurang-kurangnya 1 nombor';

  @override
  String get passwordRuleUpper => 'Sekurang-kurangnya 1 huruf besar';

  @override
  String get passwordRuleSpecial =>
      'Sekurang-kurangnya 1 aksara khas (! @ # \$ * . ?)';

  @override
  String get passwordRulesNotMet =>
      'Kata laluan tidak memenuhi semua keperluan.';

  @override
  String get confirmNewPasswordLabel => 'Sahkan kata laluan baharu';

  @override
  String get allFieldsRequired => 'Sila isi semua ruangan.';

  @override
  String get passwordsDoNotMatch => 'Kata laluan tidak sepadan.';

  @override
  String get resetPasswordButton => 'Tetapkan Semula Kata Laluan';

  @override
  String get passwordResetSuccessSnack =>
      'Kata laluan anda telah ditetapkan semula. Sila log masuk dengan kata laluan baharu anda.';

  @override
  String get forgotPasswordFailedGeneric =>
      'Tidak dapat menetapkan semula kata laluan anda. Semak butiran anda atau alamat asas API dalam Tetapan.';

  @override
  String get selfRegisterTitle => 'Cipta Akaun Anda';

  @override
  String get selfRegisterDetailsStepDesc =>
      'Untuk pesakit yang belum mempunyai log masuk CLARION. Masukkan butiran anda persis seperti pada Kad Pengenalan anda — kami akan mengesahkannya dengan rekod hospital anda.';

  @override
  String get selfRegisterContinueButton => 'Teruskan';

  @override
  String get selfRegisterStartFailedGeneric =>
      'Tidak dapat mengesahkan butiran anda. Semak apa yang anda masukkan atau alamat asas API dalam Tetapan.';

  @override
  String get selfRegisterOtpStepDesc =>
      'Masukkan kod pengesahan 6 digit yang kami e-melkan kepada anda.';

  @override
  String get selfRegisterScanButton => 'Imbas K/P saya untuk mengisi maklumat';

  @override
  String get selfRegisterScanPrivacy =>
      'Gambar dibaca pada telefon ini dan tidak dimuat naik. Semak maklumat sebelum meneruskan.';

  @override
  String selfRegisterCodeSentTo(String hint) {
    return 'Kami telah menghantar kod 6 digit ke $hint, alamat dalam rekod hospital anda. Masukkan di bawah.';
  }

  @override
  String get selfRegisterVerifyOtpButton => 'Sahkan Kod';

  @override
  String get selfRegisterVerifyOtpFailedGeneric =>
      'Tidak dapat mengesahkan kod itu. Semak kod anda atau alamat asas API dalam Tetapan.';

  @override
  String get selfRegisterPhotosStepTitle => 'Sahkan Identiti Anda';

  @override
  String get selfRegisterPhotosStepDesc =>
      'Sekarang ambil gambar yang jelas bagi bahagian hadapan dan belakang Kad Pengenalan fizikal anda. Gambar ini hanya digunakan untuk mengesahkan identiti anda dengan rekod hospital anda — kakitangan kami, bukan aplikasi ini, yang menyemak padanan.';

  @override
  String get selfRegisterFrontPhotoLabel => 'Bahagian hadapan Kad Pengenalan';

  @override
  String get selfRegisterBackPhotoLabel => 'Bahagian belakang Kad Pengenalan';

  @override
  String get selfRegisterTakePhotoButton => 'Ambil Gambar';

  @override
  String get selfRegisterRetakePhotoButton => 'Ambil Semula';

  @override
  String selfRegisterAttemptsRemaining(int count) {
    return '$count daripada 5 percubaan berbaki';
  }

  @override
  String get selfRegisterSubmitPhotosButton => 'Hantar Gambar';

  @override
  String get selfRegisterPhotosRequiredNote =>
      'Sila ambil kedua-dua gambar sebelum menghantar.';

  @override
  String get selfRegisterPhotosFailedGeneric =>
      'Tidak dapat mengesahkan gambar anda. Semak alamat asas API dalam Tetapan dan cuba lagi.';

  @override
  String get selfRegisterCameraFailed =>
      'Tidak dapat membuka kamera. Semak kebenaran kamera dalam tetapan sistem dan cuba lagi.';

  @override
  String get selfRegisterPasswordStepDesc =>
      'Hampir selesai. Pilih kata laluan untuk akaun baharu anda (sekurang-kurangnya 8 aksara).';

  @override
  String get selfRegisterPendingDesc =>
      'Pendaftaran anda menunggu pengesahan dan anda belum boleh log masuk. Ia diluluskan selepas kakitangan menyemak kad pengenalan anda di kaunter, atau sebaik sahaja foto kad pengenalan anda sepadan. Hanya pendaftaran pertama yang disahkan bagi sesuatu NRIC dikekalkan; yang lain ditolak dan e-melnya ditandakan.';

  @override
  String get selfRegisterCompleteButton => 'Cipta Akaun';

  @override
  String get selfRegisterCompleteFailedGeneric =>
      'Tidak dapat mencipta akaun anda. Semak alamat asas API dalam Tetapan dan cuba lagi.';

  @override
  String get selfRegisterSuccessSnack =>
      'Akaun berjaya dicipta — selamat datang ke CLARION!';

  @override
  String get selfRegisterManualRequiredTitle =>
      'Sila Kunjungi Kaunter Pendaftaran';

  @override
  String get selfRegisterManualRequiredBody =>
      'Kami tidak dapat mengesahkan gambar Kad Pengenalan anda selepas beberapa percubaan. Demi keselamatan anda, sila kunjungi kaunter pendaftaran secara peribadi dengan membawa Kad Pengenalan fizikal anda — kakitangan kami akan membantu menyediakan akaun anda di sana.';

  @override
  String get selfRegisterManualRequiredBackButton => 'Kembali ke Log Masuk';

  @override
  String get changePasswordTitle => 'Tukar Kata Laluan';

  @override
  String get changePasswordRequiredNotice =>
      'Akaun anda disediakan dengan kata laluan sementara. Demi keselamatan, anda perlu menetapkan kata laluan sendiri sebelum meneruskan.';

  @override
  String get temporaryPasswordLabel => 'Kata laluan sementara';

  @override
  String get changePasswordButton => 'Tukar Kata Laluan';

  @override
  String get passwordChangedSnack => 'Kata laluan berjaya ditukar.';

  @override
  String get homeTitle => 'Rekod Kesihatan Saya';

  @override
  String get quickActionsSectionTitle => 'Tindakan Pantas';

  @override
  String get healthRecordSectionTitle => 'Rekod Perubatan Anda';

  @override
  String get scanSomeoneElsesCardTooltip => 'Imbas kad kecemasan orang lain';

  @override
  String get noPatientRecord =>
      'Tiada rekod pesakit dikaitkan dengan akaun ini.';

  @override
  String bloodTypeLabel(String type) {
    return 'Jenis darah $type';
  }

  @override
  String get signOut => 'Log keluar';

  @override
  String get emergencyButton => '🚨 Lihat / Terbitkan Kad QR Kecemasan';

  @override
  String get healthSummaryTitle => 'Ringkasan Kesihatan Anda';

  @override
  String get activeConditionsTitle => 'Keadaan Aktif';

  @override
  String get noConditions => 'Tiada keadaan perubatan direkodkan.';

  @override
  String get chronicSuffix => '(kronik)';

  @override
  String diagnosedOnLabel(String date) {
    return 'Didiagnosis $date';
  }

  @override
  String get currentMedicationsTitle => 'Ubat Semasa';

  @override
  String get noActiveMedications => 'Tiada ubat aktif.';

  @override
  String get unknownFacility => 'kemudahan tidak diketahui';

  @override
  String get allergiesTitle => 'Alahan';

  @override
  String get noAllergies => 'Tiada alahan diketahui direkodkan.';

  @override
  String get recentEncountersTitle => 'Lawatan Terkini';

  @override
  String get noEncounters => 'Tiada rekod lawatan.';

  @override
  String encounterReasonLabel(String reason) {
    return 'Sebab: $reason';
  }

  @override
  String encounterNotesLabel(String notes) {
    return 'Nota: $notes';
  }

  @override
  String encounterDepartmentLabel(String department) {
    return 'Jabatan: $department';
  }

  @override
  String encounterVitalsLabel(String vitals) {
    return 'Tanda vital: $vitals';
  }

  @override
  String get downloadVisitSummary =>
      'Muat turun / kongsi ringkasan lawatan (PDF)';

  @override
  String get visitSummaryUnavailable =>
      'Ringkasan lawatan belum tersedia untuk lawatan ini.';

  @override
  String get documentsTitle => 'Dokumen';

  @override
  String get noDocuments => 'Tiada dokumen direkodkan.';

  @override
  String get docTypePrescription => 'Preskripsi';

  @override
  String get docTypeDischargeSummary => 'Ringkasan Discaj';

  @override
  String get docTypeLabReport => 'Laporan Makmal';

  @override
  String get docTypeImaging => 'Pengimejan';

  @override
  String get docTypeOther => 'Dokumen';

  @override
  String documentUploadedLine(String facility, String date) {
    return 'Dimuat naik oleh $facility pada $date';
  }

  @override
  String get remindersButton => 'Peringatan Ubat & Temu Janji';

  @override
  String get bookAppointmentButton => 'Tempah Temu Janji';

  @override
  String get whoViewedRecord => 'Siapa yang melihat rekod saya?';

  @override
  String get retry => 'Cuba Semula';

  @override
  String showMoreAction(int count) {
    return 'Tunjuk $count lagi';
  }

  @override
  String get showLessAction => 'Tunjuk kurang';

  @override
  String get emergencyCardTitle => 'Kad Kecemasan';

  @override
  String get emergencyAccessCardTitle => 'Kad Akses Kecemasan';

  @override
  String get scopeAllergies => 'Alahan';

  @override
  String get scopeMedications => 'Ubat Semasa';

  @override
  String get scopeConditions => 'Keadaan Kronik';

  @override
  String get scopeBloodType => 'Jenis Darah';

  @override
  String get generateButton => 'Jana Kod QR / Kad';

  @override
  String get issuing => 'Sedang menerbitkan…';

  @override
  String get printNote =>
      'Cetak kad ini untuk kegunaan luar talian / warga emas. Ia juga harus memaparkan jenis darah dan alahan utama anda dalam teks besar sebagai sandaran.';

  @override
  String referenceLabel(String ref) {
    return 'Rujukan: $ref';
  }

  @override
  String validUntilLabel(String date) {
    return 'Sah sehingga: $date';
  }

  @override
  String get revokeCard => 'Batalkan kad ini';

  @override
  String get revokedBadge => 'DIBATALKAN';

  @override
  String get couldNotRenderQr => 'Tidak dapat memaparkan imej kod QR';

  @override
  String get cardRevokedSnack => 'Kad telah dibatalkan.';

  @override
  String get cardRevokeFailedSnack => 'Gagal membatalkan kad.';

  @override
  String get cardIssueFailedSnack => 'Gagal menerbitkan kad.';

  @override
  String get cardIssuedSnack => 'Kad kecemasan baharu telah diterbitkan.';

  @override
  String cardIssuedWithRevokeSnack(int count) {
    return 'Kad baharu diterbitkan. $count kad terdahulu dibatalkan secara automatik.';
  }

  @override
  String get onlyOneLiveCardNote =>
      'Anda hanya boleh mempunyai satu kad QR aktif pada satu masa — menjana kad baharu akan membatalkan kad terdahulu secara automatik.';

  @override
  String get regenerateConfirmTitle => 'Gantikan kad semasa anda?';

  @override
  String regenerateConfirmBody(String ref) {
    return 'Anda sudah mempunyai kad aktif (ruj: $ref). Menjana kad baharu akan membatalkannya secara automatik — kod QR lama akan berhenti berfungsi serta-merta.';
  }

  @override
  String get regenerateConfirmAction => 'Batalkan lama, jana baharu';

  @override
  String get remindersTitle => 'Peringatan';

  @override
  String get announcementsSectionTitle => 'Pengumuman';

  @override
  String get medicationsSection => 'Ubat-ubatan';

  @override
  String get noActiveMedsRecord => 'Tiada ubat aktif direkodkan.';

  @override
  String get suggestedReminder =>
      'Cadangan peringatan: dua kali sehari, 8 pagi / 8 malam';

  @override
  String prescribedBy(String facility) {
    return 'Ditetapkan oleh $facility';
  }

  @override
  String get clinicAppointmentsSection => 'Daripada Klinik Anda';

  @override
  String get noClinicAppointments =>
      'Tiada temu janji akan datang daripada klinik anda buat masa ini.';

  @override
  String get clinicAppointmentBadge => 'Ditetapkan oleh klinik anda';

  @override
  String fastingRequiredNote(int hours) {
    return '⚠ Berpuasa diperlukan: $hours jam sebelum temu janji anda';
  }

  @override
  String get fastingRequiredNoteUnspecified =>
      '⚠ Berpuasa diperlukan sebelum temu janji anda — sila semak dengan klinik anda mengenai tempohnya.';

  @override
  String appointmentReasonLabel(String reason) {
    return 'Sebab: $reason';
  }

  @override
  String get upcomingAppointments => 'Temu Janji Akan Datang';

  @override
  String get noAppointments =>
      'Tiada temu janji dijadualkan. Klinik anda akan menambahnya selepas setiap lawatan.';

  @override
  String get notificationsDisabledNote =>
      'Pemberitahuan dimatikan, jadi peringatan tidak akan memberi amaran kepada anda.';

  @override
  String get notificationsPermanentlyDeniedNote =>
      'Pemberitahuan telah ditolak sebelum ini, jadi Android tidak akan menunjukkan gesaan itu lagi — buka Tetapan untuk mengaktifkannya.';

  @override
  String get enableAction => 'Aktifkan';

  @override
  String get sendTestNotification => 'Hantar pemberitahuan ujian sekarang';

  @override
  String get testNotificationTitle => 'Pemberitahuan ujian';

  @override
  String get testNotificationBody =>
      'Jika anda dapat melihat ini, peringatan ubat dan temu janji akan berfungsi dengan cara yang sama.';

  @override
  String get testNotificationSentSnack =>
      'Pemberitahuan ujian dihantar — semak bar pemberitahuan anda.';

  @override
  String get testNotificationFailedSnack =>
      'Tidak dapat menghantar pemberitahuan ujian. Semak sama ada pemberitahuan diaktifkan untuk aplikasi ini.';

  @override
  String get addAppointmentAction => 'Tambah';

  @override
  String get addAppointmentTitle => 'Tambah peringatan temu janji';

  @override
  String get appointmentLabelField => 'Temu janji ini untuk apa?';

  @override
  String get pickDateTime => 'Pilih tarikh & masa';

  @override
  String get bookViaMySejahtera => '📅 Buat Temu Janji melalui MySejahtera';

  @override
  String get mySejahteraNote =>
      'Membuka aplikasi MySejahtera jika dipasang, jika tidak senarai Play Store-nya.';

  @override
  String get mySejahteraLaunchFailed =>
      'Tidak dapat membuka MySejahtera atau alternatifnya. Adakah pelayar dipasang?';

  @override
  String get apiSettingsTitle => 'Tetapan API';

  @override
  String get backendUrlLabel => 'Alamat Asas API Bahagian Belakang';

  @override
  String get backendUrlDesc =>
      'Arahkan aplikasi ini ke pelayan bahagian belakang anda. Berguna apabila anda memulakan terowong Cloudflare (alamat trycloudflare.com berubah setiap kali terowong dimulakan semula) — tampal alamat baharu di sini tanpa perlu membina semula aplikasi.';

  @override
  String get apiBaseUrlFieldLabel => 'Alamat Asas API';

  @override
  String get save => 'Simpan';

  @override
  String get resetToDefault => 'Set Semula ke Lalai';

  @override
  String currentlyActive(String url) {
    return 'Aktif sekarang: $url';
  }

  @override
  String compileTimeDefault(String url) {
    return 'Lalai masa kompil: $url';
  }

  @override
  String get usingOverride => 'Menggunakan tetapan ganti masa jalan.';

  @override
  String get usingDefault => 'Menggunakan lalai masa kompil.';

  @override
  String get emulatorNote =>
      '10.0.2.2 ialah alamat khas yang digunakan oleh pelemulasi Android untuk mencapai localhost komputer pembangun anda. Pada telefon sebenar, gunakan alamat IP LAN komputer anda (cth. http://192.168.1.42:8000) atau alamat terowong — telefon dan pelayan bahagian belakang mesti boleh mencapai antara satu sama lain.';

  @override
  String savedSnack(String url) {
    return 'Alamat Asas API ditetapkan kepada $url';
  }

  @override
  String get resetSnack => 'Ditetapkan semula ke lalai masa kompil.';

  @override
  String get seniorModeToggleLabel => 'Mod Warga Emas';

  @override
  String get seniorModeToggleDesc =>
      'Paparan ringkas dengan teks lebih besar dan pilihan lebih sedikit';

  @override
  String get languageLabel => 'Bahasa';

  @override
  String get settingsTitle => 'Tetapan';

  @override
  String get themeLabel => 'Tema';

  @override
  String get themeModeLight => 'Terang';

  @override
  String get themeModeDark => 'Gelap';

  @override
  String get themeModeSystem => 'Sistem';

  @override
  String get auditLogTitle => 'Siapa Melihat Rekod Saya';

  @override
  String get noAccessLogged => 'Belum ada akses direkodkan untuk rekod anda.';

  @override
  String fieldsLabel(String fields) {
    return 'Maklumat: $fields';
  }

  @override
  String get auditActorSystemFallback => 'sistem';

  @override
  String get auditActorEmergencyResponderUnverified =>
      'responden kecemasan — dilaporkan sendiri, belum disahkan';

  @override
  String get auditLogLegendIntro =>
      'Warna dan ikon menunjukkan sensitiviti setiap akses:';

  @override
  String get auditSeverityRoutine => 'Rutin';

  @override
  String get auditSeverityAttention => 'Akses kecemasan';

  @override
  String get auditSeverityCritical => 'Percubaan gagal';

  @override
  String get responderScanTitle => 'Imbas Kad Kecemasan';

  @override
  String get responderScanDesc =>
      'Imbas kod QR kecemasan pesakit, sentuh kad NFC fizikal mereka, atau taip rujukan kad / UID NFC yang dicetak. Log masuk tidak diperlukan — ini direka bentuk sedemikian oleh pelayan bahagian belakang.';

  @override
  String get cardReferenceLabel => 'Rujukan Kad';

  @override
  String get cardReferenceHint => 'cth. daripada tab Kecemasan';

  @override
  String get responderNameLabel => 'Nama responden (pilihan)';

  @override
  String get responderOrgLabel => 'Organisasi responden (pilihan)';

  @override
  String get scanButton => 'Cari';

  @override
  String get scanning => 'Sedang mencari…';

  @override
  String get scanModeQr => 'Imbas QR';

  @override
  String get scanModeNfc => 'Sentuh NFC';

  @override
  String get scanModeManual => 'Taip Manual';

  @override
  String get nfcUidLabel => 'UID kad NFC';

  @override
  String get cameraPermissionDenied =>
      'Kebenaran kamera dinafikan, jadi pengimbas QR tidak dapat dimulakan. Berikan akses kamera dalam tetapan sistem untuk menggunakannya.';

  @override
  String get openAppSettings => 'Buka Tetapan';

  @override
  String get nfcUnsupportedPlatform =>
      'Imbasan NFC hanya disokong pada Android dalam aplikasi ini.';

  @override
  String get nfcUnsupportedDevice =>
      'Peranti ini tidak mempunyai perkakasan NFC.';

  @override
  String get nfcDisabled =>
      'NFC dimatikan pada peranti ini. Hidupkannya dalam tetapan sistem, kemudian kembali ke skrin ini.';

  @override
  String get nfcReadyToTap =>
      'Sedia — letakkan kad pada bahagian belakang telefon';

  @override
  String get nfcStarting => 'Memulakan NFC…';

  @override
  String get scanResultFoundTitle => 'Pesakit Ditemui';

  @override
  String scanResultAgeValue(String age) {
    return 'Umur: $age';
  }

  @override
  String get scanResultBloodTypeUnknown => 'Tiada dalam rekod';

  @override
  String scanResultOmittedMedications(int count) {
    return '+$count lagi ubat dalam rekod, tidak dipaparkan di sini — tidak ditanda sebagai kritikal kecemasan.';
  }

  @override
  String scanResultOmittedConditions(int count) {
    return '+$count lagi keadaan dalam rekod, tidak dipaparkan di sini — tidak ditanda sebagai kritikal kecemasan.';
  }

  @override
  String scanResultOmittedAllergies(int count) {
    return '+$count lagi alahan dalam rekod, tidak dipaparkan di sini — tidak ditanda sebagai kritikal kecemasan.';
  }

  @override
  String get scanResultOfflineBanner =>
      'LUAR TALIAN — dibaca terus daripada kad, tiada rangkaian. Mungkin sudah lapuk; nama dan umur tidak disimpan pada kad.';

  @override
  String get scanResultOfflinePlaceholderName =>
      'Pemegang kad (bacaan luar talian)';

  @override
  String get mfaTitle => 'Pengesahan dua langkah';

  @override
  String get mfaPrompt =>
      'Masukkan kod 6 digit daripada aplikasi pengesah anda, atau salah satu kod pemulihan anda.';

  @override
  String get mfaCodeLabel => 'Kod';

  @override
  String get mfaVerifyButton => 'Sahkan';

  @override
  String get mfaCancelButton => 'Kembali ke log masuk';

  @override
  String get mfaEmailButton => 'Hantar kod melalui e-mel';

  @override
  String mfaEmailSent(String hint) {
    return 'Kami telah menghantar kod 6 digit ke $hint. Kod tamat tempoh dalam 10 minit.';
  }

  @override
  String get mfaEmailCodeLabel => 'Kod e-mel';

  @override
  String get mfaUseAuthenticatorButton => 'Guna aplikasi pengesah saya';

  @override
  String get mfaEmailPrompt =>
      'Masukkan kod 6 digit yang kami e-melkan kepada anda.';

  @override
  String get mfaWrongCodeHint =>
      'Kod itu tidak diterima. Kod bertukar setiap 30 saat dan hanya boleh digunakan sekali, jadi tunggu kod seterusnya, pastikan jam telefon ditetapkan secara automatik, atau minta kod melalui e-mel.';

  @override
  String get nfcBasicTagWarning =>
      'Jenis tag ini (NTAG213/215/216) berfungsi, tetapi tiada pembilang bacaan kalis ubah: bacaan luar talian tidak dapat disemak untuk entri yang hilang. Gunakan NTAG 424 DNA jika akauntabiliti penting.';

  @override
  String get scanResultOfflineSignIn =>
      'Tiada sambungan dan tag ini dilindungi. Log masuk dengan akaun kakitangan/responder CLARION untuk membacanya luar talian, atau gunakan kod QR / carian dalam talian.';

  @override
  String get scanResultOfflineKeyMissing =>
      'Tiada sambungan dan peranti ini tidak mempunyai kunci untuk tag ini. Sambung sekali semasa log masuk untuk memuat turunnya, atau gunakan kod QR / carian dalam talian.';

  @override
  String get scanResultOfflineRevoked =>
      'Kad ini telah dibatalkan dan tidak boleh dibaca. Jangan bergantung padanya; gunakan kod QR atau carian dalam talian, dan laporkan kad ini.';

  @override
  String get offlineUnlockReason =>
      'Sahkan anda ialah pemilik untuk membaca kad ini luar talian';

  @override
  String get scanResultOfflineLockRequired =>
      'Telefon ini tiada kunci skrin, jadi kad tidak boleh dibaca luar talian. Tetapkan PIN, corak atau cap jari dalam tetapan telefon, atau gunakan kod QR atau carian dalam talian.';

  @override
  String get scanResultOfflineAuthFailed =>
      'Semakan identiti dibatalkan atau gagal, jadi kad tidak dibaca luar talian. Ketik kad sekali lagi dan sahkan dengan cap jari, wajah atau PIN anda.';

  @override
  String get scanResultOfflineExpired =>
      'Kesahan tag ini telah tamat dan tidak boleh dibaca luar talian. Gunakan kod QR atau carian dalam talian, dan minta kad dikeluarkan semula.';

  @override
  String get scanResultOfflineDamaged =>
      'Tag ini tidak dapat disahkan (rosak, diubah, atau bukan tag CLARION tulen). Jangan bergantung padanya - gunakan kod QR atau carian dalam talian.';

  @override
  String get writeOfflineTagTooltip =>
      'Tulis Tag Luar Talian (kakitangan sahaja)';

  @override
  String get writeOfflineTagTitle => 'Tulis Tag Luar Talian';

  @override
  String get writeOfflineTagDesc =>
      'Tampal teks yang dipaparkan selepas mendaftarkan kad NFC di konsol web, kemudian sentuh kad fizikal yang SAMA untuk menulisnya terus pada tag. Setelah ditulis, maklumat kritikal kad itu boleh dibaca tanpa rangkaian — oleh aplikasi ini atau mana-mana pembaca NFC standard.';

  @override
  String get writeOfflineTagTextLabel => 'Teks tag luar talian';

  @override
  String get writeOfflineTagButton => 'Sentuh kad untuk menulis';

  @override
  String get writeOfflineTagWriting =>
      'Tahan kad pada bahagian belakang telefon…';

  @override
  String get writeOfflineTagSuccess =>
      'Berjaya ditulis. Kad ini kini membawa maklumat kritikalnya secara luar talian.';

  @override
  String get writeOfflineTagNotNdef =>
      'Tag ini tidak menyokong NDEF — cuba kad fizikal lain.';

  @override
  String get writeOfflineTagNotWritable =>
      'Tag ini hanya boleh dibaca (dikunci) dan tidak boleh ditulis.';

  @override
  String get writeOfflineTagTooLarge =>
      'Teks ini terlalu besar untuk memori tag ini. Daftar semula dengan kurang medan dipilih, atau gunakan tag berkapasiti lebih tinggi.';

  @override
  String get writeOfflineTagNotEncrypted =>
      'Hanya rekod disulitkan daripada konsol web boleh ditulis. Tampal teks yang bermula dengan C1. dan cuba lagi.';

  @override
  String get writeOfflineTagWriteFailed =>
      'Penulisan pada tag gagal. Cuba sentuh semula, pegang kad dengan stabil.';

  @override
  String seniorBloodType(String type) {
    return 'JENIS DARAH: $type';
  }

  @override
  String seniorAllergicTo(String allergy) {
    return 'ALAH KEPADA: $allergy';
  }

  @override
  String get seniorEmergencyTile => '🚨\nKAD\nKECEMASAN';

  @override
  String get seniorMedsTile => '💊\nUBAT\nSAYA';

  @override
  String get switchToStandard => 'Tukar ke Paparan Biasa';

  @override
  String get signOutSenior => 'Log Keluar';

  @override
  String get seniorLanguageTitle => 'Tukar Bahasa';

  @override
  String get seniorEmergencyTitle => 'KAD KECEMASAN';

  @override
  String get preparingCard => 'Sedang menyediakan kad anda…';

  @override
  String get showToResponder => 'TUNJUKKAN INI KEPADA\nRESPONDEN PERUBATAN';

  @override
  String refLabel(String ref) {
    return 'Ruj: $ref';
  }

  @override
  String get getNewCard => 'Dapatkan Kad Baharu';

  @override
  String get tryAgain => 'Cuba Lagi';

  @override
  String get seniorMedsTitle => 'UBAT SAYA';

  @override
  String get noMedsRecord => 'Tiada ubat direkodkan.';

  @override
  String get takeTwiceDaily => 'Ambil dua kali sehari: 8 pagi dan 8 malam';

  @override
  String fromFacility(String facility) {
    return 'Daripada $facility';
  }

  @override
  String get yourClinic => 'klinik anda';

  @override
  String get nfcCardSectionTitle => 'Kad NFC Fizikal';

  @override
  String nfcCardActiveLine(String uid) {
    return 'Kad $uid — aktif';
  }

  @override
  String nfcCardRevokedLine(String uid) {
    return 'Kad $uid — dibatalkan';
  }

  @override
  String get editProfileTitle => 'Sunting Profil';

  @override
  String get readOnlyFieldsNote =>
      'Nama, tarikh lahir, dan No. Kad Pengenalan anda tidak boleh diubah di sini. Hubungi klinik anda untuk membetulkannya.';

  @override
  String get fullNameLabel => 'Nama penuh';

  @override
  String get editableProfileSectionTitle => 'Butiran Hubungan';

  @override
  String get profileEmailLabel => 'E-mel';

  @override
  String get profilePhoneLabel => 'Telefon';

  @override
  String get emergencyContactSectionTitle => 'Kenalan Kecemasan';

  @override
  String get emergencyContactNameLabel => 'Nama kenalan kecemasan';

  @override
  String get emergencyContactPhoneLabel => 'Telefon kenalan kecemasan';

  @override
  String get emergencyContactRelationshipLabel => 'Hubungan dengan anda';

  @override
  String get saveProfileButton => 'Simpan Perubahan';

  @override
  String get profileUpdatedSnack => 'Profil anda telah dikemas kini.';

  @override
  String get profileUpdateFailedGeneric =>
      'Tidak dapat mengemas kini profil anda. Sila cuba lagi.';

  @override
  String get missingProfileBannerText =>
      'Profil anda belum lengkap — ketik untuk melengkapkannya.';

  @override
  String get dismiss => 'Tolak';

  @override
  String get unexpectedErrorGeneric => 'Sesuatu tidak kena. Sila cuba lagi.';

  @override
  String get queueStatusButton => 'Status Giliran';

  @override
  String get queueStatusTitle => 'Status Giliran Anda';

  @override
  String yourNumberLabel(String number) {
    return 'Nombor anda: $number';
  }

  @override
  String nowServingLabel(String number) {
    return 'Sedang dilayan: $number';
  }

  @override
  String get nowServingNoneYet => 'Belum ada nombor dipanggil';

  @override
  String peopleAheadLabel(String count) {
    return '$count orang sebelum anda';
  }

  @override
  String get queueTicketDetailsTitle => 'Butiran Tiket';

  @override
  String get queueStatusLabel => 'Status';

  @override
  String get queueFacilityLabel => 'Kemudahan';

  @override
  String get queueDepartmentLabel => 'Jabatan';

  @override
  String get queueReasonLabel => 'Sebab';

  @override
  String get queueStatusWaiting => 'Menunggu';

  @override
  String get queueStatusCalled => 'Dipanggil';

  @override
  String get queueStatusDone => 'Selesai';

  @override
  String get queueStatusCancelled => 'Dibatalkan';

  @override
  String get noActiveQueueTicketTitle => 'Tiada tiket giliran aktif';

  @override
  String get noActiveQueueTicketDesc =>
      'Daftar masuk di kaunter penerimaan untuk mendapatkan nombor giliran.';

  @override
  String get bookAppointmentTitle => 'Tempah Temu Janji';

  @override
  String get bookAppointmentGenericError =>
      'Tempahan tidak dapat diselesaikan. Sila cuba lagi.';

  @override
  String get scanCheckinButton => 'Imbas untuk Daftar Masuk';

  @override
  String get scanCheckinTitle => 'Imbas untuk Daftar Masuk';

  @override
  String get scanCheckinDesc =>
      'Imbas kod QR di stesen daftar masuk sendiri kaunter penerimaan, atau taip kodnya di bawah. Tiada bantuan kakitangan diperlukan — anda akan mendapat nombor giliran serta-merta.';

  @override
  String get checkinReasonLabel => 'Sebab lawatan (pilihan)';

  @override
  String get checkinReasonHint => 'cth. susulan, ujian darah';

  @override
  String get stationCodeLabel => 'Kod stesen';

  @override
  String get stationCodeHint =>
      'cth. daripada kod bercetak di kaunter penerimaan';

  @override
  String get checkinSubmitButton => 'Daftar Masuk';

  @override
  String get checkinSubmitting => 'Mendaftar masuk…';

  @override
  String get requestRescheduleButton => 'Minta Tukar Jadual';

  @override
  String get rescheduleDialogTitle => 'Minta Penjadualan Semula';

  @override
  String get rescheduleDialogDesc =>
      'Beritahu klinik anda jika anda tidak dapat hadir temu janji ini. Mereka akan menyemak permintaan anda dan menghubungi anda.';

  @override
  String get rescheduleReasonScheduleConflict => 'Pertindihan jadual';

  @override
  String get rescheduleReasonUnwell => 'Tidak sihat / tidak dapat bermusafir';

  @override
  String get rescheduleReasonTransport => 'Masalah pengangkutan';

  @override
  String get rescheduleReasonOther => 'Lain-lain';

  @override
  String get rescheduleOtherReasonLabel => 'Sila terangkan sebab anda';

  @override
  String get rescheduleOtherReasonRequired => 'Sila terangkan sebab anda.';

  @override
  String get rescheduleSubmitButton => 'Hantar Permintaan';

  @override
  String get rescheduleSubmitting => 'Menghantar…';

  @override
  String get reschedulePendingNote =>
      'Permintaan tukar jadual dihantar — menunggu maklum balas klinik';

  @override
  String get rescheduleAcceptedNote =>
      'Permintaan tukar jadual anda telah diterima.';

  @override
  String get rescheduleRejectedNote =>
      'Permintaan tukar jadual anda telah ditolak.';

  @override
  String rescheduleClinicianNoteLabel(String note) {
    return 'Nota klinik: $note';
  }

  @override
  String previouslyScheduledLabel(String date) {
    return 'Sebelum ini: $date';
  }

  @override
  String get seniorMenuTooltip => 'Menu';

  @override
  String get seniorMenuTitle => 'Menu';

  @override
  String get seniorThemeToggleTooltip => 'Tukar tema warna';

  @override
  String get confirmSwitchToStandardTitle => 'Tukar ke Paparan Standard?';

  @override
  String get confirmSwitchToStandardBody =>
      'Anda akan keluar daripada Mod Warga Emas dan melihat aplikasi biasa. Anda boleh menghidupkan semula Mod Warga Emas bila-bila masa daripada Tetapan.';

  @override
  String get confirmSwitchToStandardAction => 'Ya, Tukar';

  @override
  String get confirmSignOutTitle => 'Log Keluar?';

  @override
  String get confirmSignOutBody =>
      'Anda perlu log masuk semula untuk melihat rekod kesihatan anda.';

  @override
  String get confirmSignOutAction => 'Ya, Log Keluar';

  @override
  String get myBills => 'Bil saya';

  @override
  String get billsEmpty => 'Anda tiada bil.';

  @override
  String get paymentHistory => 'Sejarah bayaran';

  @override
  String billToPay(String amount) {
    return '$amount perlu dibayar';
  }

  @override
  String get billInsurerPending => 'Menunggu penanggung insurans anda';

  @override
  String get billPaidInFull => 'Telah dibayar sepenuhnya';

  @override
  String get billItems => 'Butiran';

  @override
  String get payNow => 'Bayar sekarang';

  @override
  String get payAmountLabel => 'Jumlah untuk dibayar (RM)';

  @override
  String get payContinue => 'Teruskan';

  @override
  String get payInvalidAmount => 'Masukkan jumlah dalam RM, contohnya 25.00.';

  @override
  String payTooMuch(String amount) {
    return 'Jumlah maksimum yang boleh dibayar ialah $amount.';
  }

  @override
  String get paySimulatedNotice =>
      'Halaman bayaran simulasi. Ini ialah get laluan demo: tiada wang sebenar bergerak.';

  @override
  String get payApprove => 'Luluskan bayaran';

  @override
  String get payDecline => 'Tolak bayaran';

  @override
  String get payCancel => 'Batalkan bayaran';

  @override
  String get paySecurely => 'Bayar dengan selamat';

  @override
  String payDeclined(String reason) {
    return '$reason Anda tidak dicaj.';
  }

  @override
  String receiptTitle(String number) {
    return 'Resit $number';
  }

  @override
  String get receiptVoided => 'Bayaran ini telah dibatalkan.';

  @override
  String get receiptEmail => 'E-mel resit';

  @override
  String get receiptSharePdf => 'Kongsi PDF';

  @override
  String receiptEmailSent(String to) {
    return 'Resit dihantar ke $to.';
  }

  @override
  String get cancel => 'Batal';

  @override
  String get close => 'Tutup';

  @override
  String get navHome => 'Utama';

  @override
  String get navCare => 'Penjagaan';

  @override
  String get navScan => 'Imbas';

  @override
  String get navQueue => 'Giliran';

  @override
  String get navProfile => 'Profil';

  @override
  String get scanHubNotClarion =>
      'Ini bukan kod CLARION. Imbas kod daftar masuk klinik atau kad kecemasan.';

  @override
  String get scanHubQrHint =>
      'Halakan kamera ke kod daftar masuk klinik atau QR kad kecemasan.';

  @override
  String get scanHubUnreadableTag =>
      'Kad tidak dapat dibaca. Pegang kad dengan stabil pada telefon dan cuba lagi.';

  @override
  String get scanAnotherCard => 'Imbas kad lain';

  @override
  String get responderIdentityTitle => 'Siapa yang mengimbas?';

  @override
  String get responderIdentityNote =>
      'Nama anda disimpan pada telefon ini dan direkodkan dalam log akses kad.';

  @override
  String responderScanningAs(String who) {
    return 'Mengimbas sebagai $who';
  }

  @override
  String get responderChange => 'Tukar';

  @override
  String get responderAdd => 'Tambah nama dan organisasi anda';

  @override
  String callContactLabel(String name) {
    return 'Hubungi $name';
  }

  @override
  String get legacyTagWarningTitle => 'Kad NFC lama';

  @override
  String get legacyTagWarningBody =>
      'Data pada kad ini tidak disulitkan dan tidak boleh disemak sama ada diubah tanpa rangkaian. Minta kakitangan mengeluarkan semula kad ini.';

  @override
  String get bkBannerTitle => 'Lebih suka MySejahtera?';

  @override
  String get bkBannerNote =>
      'Tempahan di sini hanya berfungsi di hospital yang telah mengaktifkan tempahan dalam talian.';

  @override
  String get bkOpenMySejahtera => 'Buka MySejahtera';

  @override
  String get bkBookHere => 'Tempah di sini';

  @override
  String get bkChooseCategory => 'Apa yang anda perlukan?';

  @override
  String get bkChooseHospital => 'Cari hospital';

  @override
  String get bkChooseTime => 'Pilih tarikh dan masa';

  @override
  String get bkChoosePerson => 'Untuk siapa?';

  @override
  String get bkConfirmTitle => 'Semak dan sahkan';

  @override
  String get bkCategoriesEmpty =>
      'Tiada perkhidmatan tempahan tersedia buat masa ini.';

  @override
  String get bkSearchHint => 'Nama hospital atau kawasan';

  @override
  String get bkSearchAction => 'Cari';

  @override
  String get bkUseMyLocation => 'Guna lokasi saya';

  @override
  String get bkClearLocation => 'Berhenti guna lokasi';

  @override
  String get bkSortedNearest => 'Terdekat dahulu';

  @override
  String get bkLocationDenied =>
      'Kebenaran lokasi ditolak. Taip nama hospital atau kawasan, atau benarkan lokasi dalam tetapan telefon anda.';

  @override
  String get bkLocationOff =>
      'Lokasi dimatikan pada telefon ini. Hidupkannya, atau taip nama hospital atau kawasan.';

  @override
  String get bkLocationFailed =>
      'Tidak dapat mengesan lokasi anda. Sila taip nama hospital atau kawasan.';

  @override
  String get bkFacilitiesEmpty =>
      'Tiada hospital ditemui. Hanya hospital yang mengaktifkan tempahan dalam talian untuk perkhidmatan ini disenaraikan. Cuba nama atau kawasan lain, atau buka MySejahtera.';

  @override
  String bkDistanceKm(String km) {
    return '$km km dari anda';
  }

  @override
  String bkNextAvailable(String when) {
    return 'Kekosongan seterusnya: $when';
  }

  @override
  String get bkNoNextAvailable => 'Tiada slot kosong dalam masa terdekat';

  @override
  String get bkDateLabel => 'Tarikh';

  @override
  String get bkTimeLabel => 'Masa';

  @override
  String get bkNoOpenDays =>
      'Hospital ini tiada slot kosong dalam 14 hari akan datang.';

  @override
  String get bkNoSlots => 'Tiada slot lagi pada hari ini. Pilih tarikh lain.';

  @override
  String bkSlotsLeft(int count) {
    return '$count lagi';
  }

  @override
  String get bkSlotFull => 'Penuh';

  @override
  String bkDayOpenSemantics(String date, int count) {
    return '$date, $count slot kosong';
  }

  @override
  String bkDayFullSemantics(String date) {
    return '$date, tiada slot kosong';
  }

  @override
  String get bkContinue => 'Teruskan';

  @override
  String get bkMyself => 'Diri saya';

  @override
  String get bkMyselfNote => 'Akaun anda yang dilog masuk';

  @override
  String get bkSavedPeople => 'Orang tersimpan';

  @override
  String get bkNoPeople =>
      'Anda belum menyimpan sesiapa. Tambah anak atau ibu bapa untuk membuat tempahan bagi mereka.';

  @override
  String get bkAddPerson => 'Tambah orang';

  @override
  String get bkEditPerson => 'Sunting orang';

  @override
  String get bkDelete => 'Padam';

  @override
  String get bkDeletePersonTitle => 'Padam orang ini?';

  @override
  String bkDeletePersonBody(String name) {
    return '$name akan dibuang daripada senarai orang tersimpan. Temu janji sedia ada tidak terjejas.';
  }

  @override
  String get bkFullName => 'Nama penuh';

  @override
  String get bkRelationship => 'Hubungan';

  @override
  String get bkRelChild => 'Anak';

  @override
  String get bkRelParent => 'Ibu bapa';

  @override
  String get bkRelSpouse => 'Pasangan';

  @override
  String get bkRelSibling => 'Adik-beradik';

  @override
  String get bkRelRelative => 'Saudara-mara';

  @override
  String get bkRelOther => 'Lain-lain';

  @override
  String get bkPickDob => 'Pilih tarikh lahir';

  @override
  String get bkNric => 'No. KP (pilihan)';

  @override
  String get bkNameRequired => 'Masukkan nama penuh.';

  @override
  String get bkDobRequired => 'Pilih tarikh lahir.';

  @override
  String get bkSummaryCategory => 'Perkhidmatan';

  @override
  String get bkSummaryHospital => 'Hospital';

  @override
  String get bkSummaryWhen => 'Tarikh dan masa';

  @override
  String get bkSummaryPerson => 'Untuk';

  @override
  String get bkReasonLabel => 'Sebab (pilihan)';

  @override
  String get bkConfirmButton => 'Sahkan tempahan';

  @override
  String get bkTryAgain => 'Cuba lagi';

  @override
  String get bkSlotTaken =>
      'Masa itu baru sahaja diambil. Sila pilih masa lain.';

  @override
  String get bkNoPatientRecord =>
      'Akaun anda belum dipautkan kepada rekod pesakit, jadi tidak boleh membuat tempahan. Minta kaunter pendaftaran hospital memautkannya.';

  @override
  String get bkNetworkError =>
      'Tidak dapat menghubungi pelayan. Semak sambungan anda dan cuba lagi.';

  @override
  String get bkSuccessTitle => 'Tempahan disahkan';

  @override
  String get bkSuccessBody =>
      'Temu janji anda telah ditempah. Anda boleh melihatnya di bawah temu janji anda.';

  @override
  String get bkViewAppointments => 'Lihat temu janji saya';

  @override
  String get bkDone => 'Selesai';

  @override
  String get bkCancelAppointment => 'Batalkan tempahan';

  @override
  String get bkCancelTitle => 'Batalkan temu janji ini?';

  @override
  String get bkCancelBody => 'Masa ini akan dilepaskan untuk pesakit lain.';

  @override
  String get bkKeepAppointment => 'Kekalkan temu janji';

  @override
  String get bkCancelled => 'Temu janji dibatalkan.';

  @override
  String bkForPerson(String name) {
    return 'Untuk $name';
  }

  @override
  String get bkCatGeneral => 'Konsultasi am';

  @override
  String get bkCatChronic => 'Susulan dan penjagaan kronik';

  @override
  String get bkCatVaccination => 'Vaksinasi';

  @override
  String get bkCatMaternalChild => 'Kesihatan ibu dan anak';

  @override
  String get bkCatDental => 'Pergigian';

  @override
  String get bkCatScreening => 'Saringan kesihatan';

  @override
  String get bkCatMentalHealth => 'Kesihatan mental dan kaunseling';

  @override
  String get bkCatPhysio => 'Fisioterapi dan pemulihan';

  @override
  String get emergencyTabQr => 'Kod QR';

  @override
  String get emergencyTabCard => 'Kad';

  @override
  String get emergencyDescFixed =>
      'Responden kecemasan yang mengimbas kod QR anda hanya melihat empat perkara di bawah. Setiap imbasan direkodkan dan anda boleh membatalkan kod pada bila-bila masa.';

  @override
  String get whatWillBeShared => 'Apa yang akan dikongsi';

  @override
  String get sharedAlwaysNote =>
      'Perkara ini sentiasa disertakan. Tiada maklumat lain dalam rekod anda dikongsi.';

  @override
  String get previewTooltip => 'Pratonton apa yang responden lihat';

  @override
  String get previewTitle => 'Apa yang responden lihat';

  @override
  String get previewIntro =>
      'Diambil daripada rekod anda sendiri. Ini yang dipaparkan apabila kod QR anda diimbas. Tiada maklumat lain dikongsi.';

  @override
  String get previewNone => 'Tiada rekod';

  @override
  String previewOmitted(int count) {
    return '$count lagi yang tidak ditanda kritikal tidak dipaparkan.';
  }

  @override
  String get regenerateButton => 'Jana semula kod QR';

  @override
  String get cardStatusActive => 'Aktif';

  @override
  String get cardStatusExpired => 'Tamat tempoh';

  @override
  String get cardStatusRevoked => 'Dibatalkan';

  @override
  String cardEndingIn(String last4) {
    return 'Kad berakhir ••••$last4';
  }

  @override
  String get shareCardImage => 'Kongsi imej kad';

  @override
  String get shareCardFailed => 'Imej kad tidak dapat dikongsi.';

  @override
  String get cardOutdatedTitle => 'Cip NFC lama';

  @override
  String cardOutdatedBody(String date) {
    return 'Kad ini menggunakan cip lama tanpa kaunter bacaan kalis ubah. Minta kad yang lebih baharu daripada kakitangan klinik. Kad ini tamat tempoh pada $date.';
  }

  @override
  String get cardInfoTitle => 'Butiran kad';

  @override
  String get cardChipLabel => 'Jenis cip';

  @override
  String get chipNtag21x => 'NTAG213/215/216 (cip lama)';

  @override
  String get chipNtag424 => 'NTAG 424 DNA';

  @override
  String get chipUnknown => 'Cip tidak diketahui';

  @override
  String get cardRegisteredLabel => 'Didaftarkan';

  @override
  String get cardValidUntilLabel => 'Sah sehingga';

  @override
  String cardDaysLeft(int days) {
    String _temp0 = intl.Intl.pluralLogic(
      days,
      locale: localeName,
      other: '$days hari lagi',
      one: '1 hari lagi',
      zero: 'Tamat hari ini',
    );
    return '$_temp0';
  }

  @override
  String get cardSharesLabel => 'Dikongsi';

  @override
  String get cardHistoryTitle => 'Sejarah';

  @override
  String get cardHistoryEmpty => 'Belum ada aktiviti direkodkan untuk kad ini.';

  @override
  String get cardHistoryError => 'Sejarah kad ini tidak dapat dimuatkan.';

  @override
  String get cardEventRegistered => 'Didaftarkan';

  @override
  String get cardEventRenewed => 'Diperbaharui';

  @override
  String get cardEventRevoked => 'Dibatalkan';

  @override
  String get cardEventScanned => 'Diimbas';

  @override
  String cardEventBy(String who) {
    return 'oleh $who';
  }

  @override
  String get cardsEmptyTitle => 'Belum ada kad NFC';

  @override
  String get cardsEmptyBody =>
      'Kad NFC dikeluarkan oleh kakitangan klinik. Tanya di kaunter klinik anda jika mahu satu. Sementara itu, kod QR anda boleh digunakan.';

  @override
  String get cardsLoadError => 'Kad NFC anda tidak dapat dimuatkan.';

  @override
  String get dayToday => 'Hari ini';

  @override
  String get dayYesterday => 'Semalam';

  @override
  String daysAgo(int count) {
    return '$count hari lalu';
  }

  @override
  String get auditTagAll => 'Semua';

  @override
  String get auditTagEmergency => 'Imbasan kecemasan';

  @override
  String get auditTagViews => 'Paparan rekod';

  @override
  String get auditTagChanges => 'Perubahan';

  @override
  String get auditTagAccount => 'Akaun dan kad';

  @override
  String get auditTagFailed => 'Percubaan gagal';

  @override
  String get auditNeedsAttention => 'Perlu perhatian';

  @override
  String auditSummary(int count, String window, int attention) {
    return '$count akses dalam $window lalu, $attention perlu perhatian';
  }

  @override
  String get auditWindow7d => '7 hari';

  @override
  String get auditWindow30d => '30 hari';

  @override
  String get auditWindow1y => 'tahun';

  @override
  String get auditWindow7y => '7 tahun';

  @override
  String auditCollapsedCount(int count, String time) {
    return 'x$count, terkini $time';
  }

  @override
  String get auditInfoTooltip => 'Cara tahap keterukan ditunjukkan';

  @override
  String get auditInfoTitle => 'Tahap keterukan';

  @override
  String auditDetailLabel(String detail) {
    return 'Butiran: $detail';
  }

  @override
  String auditTimesLabel(String times) {
    return 'Masa: $times';
  }

  @override
  String get auditNoMatches => 'Tiada entri sepadan dengan penapis ini.';

  @override
  String get auditClearFilters => 'Kosongkan penapis';

  @override
  String get auditLoadError => 'Log akses tidak dapat dimuatkan.';

  @override
  String get nricScanTitle => 'Imbas NRIC anda';

  @override
  String get nricScanHint =>
      'Letakkan bahagian hadapan NRIC anda dalam bingkai';

  @override
  String get nricScanLooking => 'Mencari kad…';

  @override
  String get nricScanHold => 'Kekalkan kedudukan';

  @override
  String get nricScanTimeout =>
      'Kad tidak dapat dibaca. Tekan butang rakam untuk mengambil gambar sendiri, atau kembali dan taip butiran anda.';

  @override
  String get nricScanShutter => 'Ambil gambar';

  @override
  String get nricScanTorch => 'Lampu suluh';

  @override
  String get nricScanTorchFailed =>
      'Telefon ini tidak boleh menghidupkan lampu suluh.';

  @override
  String get nricScanPermission =>
      'Akses kamera dimatikan. Benarkan kamera untuk CLARION dalam tetapan telefon, atau kembali dan taip butiran anda.';

  @override
  String get nricScanNoCamera =>
      'Tiada kamera ditemui pada telefon ini. Kembali dan taip butiran anda.';

  @override
  String get nricScanCameraFailed =>
      'Kamera tidak dapat dimulakan. Kembali dan taip butiran anda.';

  @override
  String get nricScanTypeInstead => 'Taip butiran saya sebaliknya';

  @override
  String get nricScanReviewTitle => 'Semak butiran anda';

  @override
  String get nricScanReviewHint =>
      'Betulkan sebarang bacaan yang salah sebelum meneruskan.';

  @override
  String get nricScanUse => 'Guna butiran ini';

  @override
  String get nricScanRetake => 'Ambil semula';
}
