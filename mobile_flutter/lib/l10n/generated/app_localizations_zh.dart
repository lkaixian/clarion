// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Chinese (`zh`).
class AppLocalizationsZh extends AppLocalizations {
  AppLocalizationsZh([String locale = 'zh']) : super(locale);

  @override
  String get appTitle => 'MediBridge';

  @override
  String get apiSettingsTooltip => 'API 设置';

  @override
  String get back => '返回';

  @override
  String get loginSubtitle => '无论身在何处，随时查阅您的健康记录';

  @override
  String get emailLabel => '电子邮件';

  @override
  String get emailOrNricLabel => '电邮或身份证号码';

  @override
  String get passwordLabel => '密码';

  @override
  String get signIn => '登录';

  @override
  String get signingIn => '正在登录…';

  @override
  String get demoLoginHint =>
      '演示账号：patient@medibridge.demo / patient123（或身份证号码 520314-01-1234 / patient123）';

  @override
  String get loginFailedGeneric => '登录失败。请检查您的账号密码，或在设置中检查 API 地址。';

  @override
  String get seniorPrompt => '长者或初次使用者？';

  @override
  String get enableSeniorMode => '启用长者模式 →';

  @override
  String get seniorModeWillOpen => '登录后将自动进入长者模式';

  @override
  String get undo => '撤销';

  @override
  String get scanEmergencyCardButton => '🚨 扫描紧急二维码 / NFC 卡';

  @override
  String get scanEmergencyCardSubtitle => '供急救人员使用——无需登录';

  @override
  String get orSignInDivider => '或登录以管理您自己的记录';

  @override
  String get forgotPasswordButton => '忘记密码？';

  @override
  String get forgotPasswordTitle => '重设密码';

  @override
  String get forgotPasswordDesc => '仅限病患使用。请输入与您健康记录一致的身份证号码及出生日期，然后设置新密码。';

  @override
  String get nricLabel => '身份证号码';

  @override
  String get dateOfBirthLabel => '出生日期';

  @override
  String get newPasswordLabel => '新密码';

  @override
  String get confirmNewPasswordLabel => '确认新密码';

  @override
  String get allFieldsRequired => '请填写所有栏位。';

  @override
  String get passwordsDoNotMatch => '两次输入的密码不一致。';

  @override
  String get resetPasswordButton => '重设密码';

  @override
  String get passwordResetSuccessSnack => '您的密码已重设。请使用新密码登录。';

  @override
  String get forgotPasswordFailedGeneric => '无法重设您的密码。请检查您的资料，或在设置中检查 API 地址。';

  @override
  String get changePasswordTitle => '更改密码';

  @override
  String get changePasswordRequiredNotice =>
      '您的账号使用了临时密码。为了安全起见，请先设置您自己的密码后再继续。';

  @override
  String get temporaryPasswordLabel => '临时密码';

  @override
  String get changePasswordButton => '更改密码';

  @override
  String get passwordChangedSnack => '密码已成功更改。';

  @override
  String get homeTitle => '我的健康记录';

  @override
  String get scanSomeoneElsesCardTooltip => '扫描他人的紧急卡';

  @override
  String get noPatientRecord => '此账号未关联任何病患记录。';

  @override
  String bloodTypeLabel(String type) {
    return '血型 $type';
  }

  @override
  String get signOut => '登出';

  @override
  String get emergencyButton => '🚨 查看 / 生成紧急二维码卡';

  @override
  String get healthSummaryTitle => '您的健康摘要';

  @override
  String get activeConditionsTitle => '现有病症';

  @override
  String get noConditions => '暂无病症记录。';

  @override
  String get chronicSuffix => '（慢性）';

  @override
  String get currentMedicationsTitle => '目前用药';

  @override
  String get noActiveMedications => '暂无正在使用的药物。';

  @override
  String get unknownFacility => '未知医疗机构';

  @override
  String get allergiesTitle => '过敏史';

  @override
  String get noAllergies => '暂无已知过敏记录。';

  @override
  String get recentEncountersTitle => '近期就诊记录';

  @override
  String get noEncounters => '暂无就诊记录。';

  @override
  String get remindersButton => '用药与预约提醒';

  @override
  String get whoViewedRecord => '谁查看过我的记录？';

  @override
  String get retry => '重试';

  @override
  String get emergencyCardTitle => '紧急卡';

  @override
  String get emergencyAccessCardTitle => '紧急访问卡';

  @override
  String get emergencyDesc =>
      '选择急救人员在紧急情况下可以查看的信息。此二维码不会泄露记录中的其他任何信息——每次扫描都会被记录，您可以随时撤销授权。';

  @override
  String get fieldsToShare => '紧急情况下要分享的信息：';

  @override
  String get scopeAllergies => '过敏史';

  @override
  String get scopeMedications => '目前用药';

  @override
  String get scopeConditions => '慢性病症';

  @override
  String get scopeBloodType => '血型';

  @override
  String get generateButton => '生成二维码 / 卡片';

  @override
  String get issuing => '正在生成…';

  @override
  String get printNote => '可打印此卡供离线或长者使用。建议同时以大字体注明血型及主要过敏原，作为备用信息。';

  @override
  String referenceLabel(String ref) {
    return '参考编号：$ref';
  }

  @override
  String validUntilLabel(String date) {
    return '有效期至：$date';
  }

  @override
  String get revokeCard => '撤销此卡';

  @override
  String get revokedBadge => '已撤销';

  @override
  String get couldNotRenderQr => '无法显示二维码图片';

  @override
  String get cardRevokedSnack => '卡片已撤销。';

  @override
  String get cardRevokeFailedSnack => '撤销卡片失败。';

  @override
  String get cardIssueFailedSnack => '生成卡片失败。';

  @override
  String get cardIssuedSnack => '新的紧急卡已生成。';

  @override
  String cardIssuedWithRevokeSnack(int count) {
    return '新卡已生成。$count 张先前的卡已被自动撤销。';
  }

  @override
  String get onlyOneLiveCardNote => '同一时间只能有一张有效的二维码卡——生成新卡会自动撤销之前的卡。';

  @override
  String get regenerateConfirmTitle => '要替换当前的卡吗？';

  @override
  String regenerateConfirmBody(String ref) {
    return '您已有一张有效卡（编号：$ref）。生成新卡将自动撤销该卡——旧的二维码将立即失效。';
  }

  @override
  String get regenerateConfirmAction => '撤销旧卡并生成新卡';

  @override
  String get remindersTitle => '提醒事项';

  @override
  String get medicationsSection => '药物';

  @override
  String get noActiveMedsRecord => '暂无正在使用的药物记录。';

  @override
  String get suggestedReminder => '建议提醒：每日两次，早上8点 / 晚上8点';

  @override
  String prescribedBy(String facility) {
    return '处方医疗机构：$facility';
  }

  @override
  String get upcomingAppointments => '即将到来的预约';

  @override
  String get noAppointments => '暂无预约安排。您的诊所将在每次就诊后添加预约。';

  @override
  String get notificationsDisabledNote => '通知已关闭，提醒将不会提示您。';

  @override
  String get notificationsPermanentlyDeniedNote =>
      '此前已拒绝通知权限，Android 将不再显示该请求——请前往系统设置手动开启。';

  @override
  String get enableAction => '启用';

  @override
  String get sendTestNotification => '立即发送测试通知';

  @override
  String get testNotificationTitle => '测试通知';

  @override
  String get testNotificationBody => '如果您能看到此通知，说明用药和预约提醒功能可以正常工作。';

  @override
  String get testNotificationSentSnack => '测试通知已发送——请查看通知栏。';

  @override
  String get testNotificationFailedSnack => '无法发送测试通知。请检查此应用的通知权限是否已开启。';

  @override
  String get addAppointmentAction => '添加';

  @override
  String get addAppointmentTitle => '添加预约提醒';

  @override
  String get appointmentLabelField => '这是什么预约？';

  @override
  String get pickDateTime => '选择日期和时间';

  @override
  String get bookViaMySejahtera => '📅 通过 MySejahtera 预约';

  @override
  String get mySejahteraNote => '若已安装 MySejahtera 将打开该应用，否则打开其 Play 商店页面。';

  @override
  String get mySejahteraLaunchFailed => '无法打开 MySejahtera 或备用链接。是否已安装浏览器？';

  @override
  String get apiSettingsTitle => 'API 设置';

  @override
  String get backendUrlLabel => '后端 API 地址';

  @override
  String get backendUrlDesc =>
      '在此设置应用连接的后端服务器地址。启动 Cloudflare 隧道后（trycloudflare.com 地址每次重启都会改变），可在此粘贴新地址，无需重新构建应用。';

  @override
  String get apiBaseUrlFieldLabel => 'API 地址';

  @override
  String get save => '保存';

  @override
  String get resetToDefault => '恢复默认值';

  @override
  String currentlyActive(String url) {
    return '当前使用：$url';
  }

  @override
  String compileTimeDefault(String url) {
    return '编译时默认值：$url';
  }

  @override
  String get usingOverride => '正在使用运行时自定义地址。';

  @override
  String get usingDefault => '正在使用编译时默认地址。';

  @override
  String get emulatorNote =>
      '10.0.2.2 是 Android 模拟器用来访问主机 localhost 的特殊地址。若在真机上使用，请改用您电脑的局域网 IP（例如 http://192.168.1.42:8000）或隧道地址——手机与后端服务器必须能够互相访问。';

  @override
  String savedSnack(String url) {
    return 'API 地址已设置为 $url';
  }

  @override
  String get resetSnack => '已恢复为编译时默认地址。';

  @override
  String get seniorModeToggleLabel => '长者模式';

  @override
  String get seniorModeToggleDesc => '简化视图，文字更大，选项更少';

  @override
  String get languageLabel => '语言';

  @override
  String get auditLogTitle => '谁查看过我的记录';

  @override
  String get noAccessLogged => '您的记录尚无访问记录。';

  @override
  String fieldsLabel(String fields) {
    return '涉及信息：$fields';
  }

  @override
  String get responderScanTitle => '扫描紧急卡';

  @override
  String get responderScanDesc =>
      '扫描病患的紧急二维码、轻触其实体 NFC 卡，或输入打印卡片上的参考编号 / NFC UID。此操作无需登录——后端系统本身即是如此设计的。';

  @override
  String get cardReferenceLabel => '卡片参考编号';

  @override
  String get cardReferenceHint => '例如来自“紧急卡”页面';

  @override
  String get responderNameLabel => '急救人员姓名（选填）';

  @override
  String get responderOrgLabel => '急救人员所属机构（选填）';

  @override
  String get scanButton => '查询';

  @override
  String get scanning => '正在查询…';

  @override
  String get scanModeQr => '扫描二维码';

  @override
  String get scanModeNfc => '轻触 NFC';

  @override
  String get scanModeManual => '手动输入';

  @override
  String get nfcUidLabel => 'NFC 卡 UID';

  @override
  String get cameraPermissionDenied => '相机权限被拒绝，二维码扫描器无法启动。请在系统设置中授予相机权限后再试。';

  @override
  String get openAppSettings => '打开设置';

  @override
  String get nfcUnsupportedPlatform => '此应用的 NFC 扫描功能仅支持 Android。';

  @override
  String get nfcUnsupportedDevice => '此设备没有 NFC 硬件。';

  @override
  String get nfcDisabled => '此设备的 NFC 功能已关闭。请在系统设置中开启，然后返回此页面。';

  @override
  String get nfcReadyToTap => '就绪——将卡片贴近手机背面';

  @override
  String get nfcStarting => '正在启动 NFC…';

  @override
  String seniorBloodType(String type) {
    return '血型：$type';
  }

  @override
  String seniorAllergicTo(String allergy) {
    return '过敏原：$allergy';
  }

  @override
  String get seniorEmergencyTile => '🚨\n紧急\n卡片';

  @override
  String get seniorMedsTile => '💊\n我的\n药物';

  @override
  String get switchToStandard => '切换到标准模式';

  @override
  String get signOutSenior => '登出';

  @override
  String get seniorLanguageTitle => '更改语言';

  @override
  String get seniorEmergencyTitle => '紧急卡片';

  @override
  String get preparingCard => '正在准备您的卡片…';

  @override
  String get showToResponder => '请将此卡出示给\n医护急救人员';

  @override
  String refLabel(String ref) {
    return '编号：$ref';
  }

  @override
  String get getNewCard => '生成新卡片';

  @override
  String get tryAgain => '重试';

  @override
  String get seniorMedsTitle => '我的药物';

  @override
  String get noMedsRecord => '暂无药物记录。';

  @override
  String get takeTwiceDaily => '每日服用两次：早上8点和晚上8点';

  @override
  String fromFacility(String facility) {
    return '来自 $facility';
  }

  @override
  String get yourClinic => '您的诊所';

  @override
  String get nfcCardSectionTitle => '实体 NFC 卡';

  @override
  String nfcCardActiveLine(String uid) {
    return '卡片 $uid — 有效';
  }

  @override
  String nfcCardRevokedLine(String uid) {
    return '卡片 $uid — 已撤销';
  }
}
