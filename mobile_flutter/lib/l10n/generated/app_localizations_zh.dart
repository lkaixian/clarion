// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Chinese (`zh`).
class AppLocalizationsZh extends AppLocalizations {
  AppLocalizationsZh([String locale = 'zh']) : super(locale);

  @override
  String get appTitle => 'CLARION';

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
      '演示账号：patient@clarion.demo / patient123（或身份证号码 520314-01-1234 / patient123）';

  @override
  String get loginFailedGeneric => '登录失败。请检查您的账号密码，或在设置中检查 API 地址。';

  @override
  String get sessionExpiredSnackbar => '您已被登出，请重新登录。';

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
  String get selfRegisterLinkPrompt => '初次使用？';

  @override
  String get selfRegisterLinkAction => '注册';

  @override
  String get forgotPasswordTitle => '重设密码';

  @override
  String get forgotPasswordDesc => '仅限病患使用。请输入与您健康记录一致的身份证号码及出生日期，然后设置新密码。';

  @override
  String get forgotPasswordStep1Desc =>
      '仅限病患使用。请输入您的身份证号码，如果您的账号已登记电邮地址，我们会将验证码发送到该邮箱。';

  @override
  String get sendCodeButton => '发送验证码';

  @override
  String get otpRequestedGenericSnack => '如果该身份证号码已登记电邮地址，验证码已发送至该邮箱。';

  @override
  String get otpCodeLabel => '验证码';

  @override
  String get forgotPasswordStep2Desc => '请输入我们发送的6位数验证码，然后设置新密码。';

  @override
  String get resendCodeButton => '没收到验证码？重新发送';

  @override
  String get resendCodeSentSnack => '如果该身份证号码已登记电邮地址，新的验证码已发送。';

  @override
  String get useDifferentNricButton => '使用其他身份证号码';

  @override
  String get requestOtpFailedGeneric => '无法请求验证码。请检查您的身份证号码，或在设置中检查 API 地址。';

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
  String get selfRegisterTitle => '创建您的账号';

  @override
  String get selfRegisterDetailsStepDesc =>
      '适用于尚未拥有 CLARION 登录账号的病患。请输入与您身份证上完全一致的资料——我们将与您的医院记录进行核对。';

  @override
  String get selfRegisterContinueButton => '继续';

  @override
  String get selfRegisterStartFailedGeneric =>
      '无法核实您的资料。请检查您所输入的内容，或在设置中检查 API 地址。';

  @override
  String get selfRegisterOtpStepDesc => '请输入我们发送到您电邮的6位数验证码。';

  @override
  String get selfRegisterVerifyOtpButton => '验证码';

  @override
  String get selfRegisterVerifyOtpFailedGeneric =>
      '无法验证该验证码。请检查验证码，或在设置中检查 API 地址。';

  @override
  String get selfRegisterPhotosStepTitle => '验证您的身份';

  @override
  String get selfRegisterPhotosStepDesc =>
      '现在请拍摄您实体身份证正反两面的清晰照片。这些照片仅用于与您的医院记录核对身份——由我们的工作人员核对，而非本应用程序本身。';

  @override
  String get selfRegisterFrontPhotoLabel => '身份证正面';

  @override
  String get selfRegisterBackPhotoLabel => '身份证反面';

  @override
  String get selfRegisterTakePhotoButton => '拍照';

  @override
  String get selfRegisterRetakePhotoButton => '重新拍摄';

  @override
  String selfRegisterAttemptsRemaining(int count) {
    return '剩余 $count/5 次尝试机会';
  }

  @override
  String get selfRegisterSubmitPhotosButton => '提交照片';

  @override
  String get selfRegisterPhotosRequiredNote => '请先拍摄两张照片再提交。';

  @override
  String get selfRegisterPhotosFailedGeneric => '无法验证您的照片。请在设置中检查 API 地址后重试。';

  @override
  String get selfRegisterCameraFailed => '无法打开相机。请在系统设置中检查相机权限后重试。';

  @override
  String get selfRegisterPasswordStepDesc => '快完成了。请为您的新账号设置密码（至少8个字符）。';

  @override
  String get selfRegisterCompleteButton => '创建账号';

  @override
  String get selfRegisterCompleteFailedGeneric => '无法创建您的账号。请在设置中检查 API 地址后重试。';

  @override
  String get selfRegisterSuccessSnack => '账号创建成功——欢迎使用 CLARION！';

  @override
  String get selfRegisterManualRequiredTitle => '请前往登记柜台';

  @override
  String get selfRegisterManualRequiredBody =>
      '经过多次尝试，我们仍无法核实您的身份证照片。为了您的安全，请携带实体身份证亲自前往登记柜台，我们的工作人员将协助您在现场设置账号。';

  @override
  String get selfRegisterManualRequiredBackButton => '返回登录';

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
  String get quickActionsSectionTitle => '快捷操作';

  @override
  String get healthRecordSectionTitle => '您的医疗记录';

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
  String diagnosedOnLabel(String date) {
    return '诊断日期 $date';
  }

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
  String encounterReasonLabel(String reason) {
    return '原因：$reason';
  }

  @override
  String encounterNotesLabel(String notes) {
    return '备注：$notes';
  }

  @override
  String encounterDepartmentLabel(String department) {
    return '科室：$department';
  }

  @override
  String encounterVitalsLabel(String vitals) {
    return '生命体征：$vitals';
  }

  @override
  String get downloadVisitSummary => '下载/分享就诊摘要（PDF）';

  @override
  String get visitSummaryUnavailable => '此次就诊的摘要尚不可用。';

  @override
  String get documentsTitle => '文件';

  @override
  String get noDocuments => '暂无文件记录。';

  @override
  String get docTypePrescription => '处方';

  @override
  String get docTypeDischargeSummary => '出院小结';

  @override
  String get docTypeLabReport => '化验报告';

  @override
  String get docTypeImaging => '影像检查';

  @override
  String get docTypeOther => '文件';

  @override
  String documentUploadedLine(String facility, String date) {
    return '由 $facility 于 $date 上传';
  }

  @override
  String get remindersButton => '用药与预约提醒';

  @override
  String get bookAppointmentButton => '预约门诊';

  @override
  String get whoViewedRecord => '谁查看过我的记录？';

  @override
  String get retry => '重试';

  @override
  String showMoreAction(int count) {
    return '显示另外 $count 项';
  }

  @override
  String get showLessAction => '收起';

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
  String get announcementsSectionTitle => '公告';

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
  String get clinicAppointmentsSection => '来自您的诊所';

  @override
  String get noClinicAppointments => '暂无来自您诊所的即将到来的预约。';

  @override
  String get clinicAppointmentBadge => '由您的诊所设置';

  @override
  String fastingRequiredNote(int hours) {
    return '⚠ 需要禁食：预约前 $hours 小时';
  }

  @override
  String get fastingRequiredNoteUnspecified => '⚠ 此预约前需要禁食——具体时长请咨询您的诊所。';

  @override
  String appointmentReasonLabel(String reason) {
    return '原因：$reason';
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
  String get themeLabel => '主题';

  @override
  String get themeModeLight => '浅色';

  @override
  String get themeModeDark => '深色';

  @override
  String get themeModeSystem => '跟随系统';

  @override
  String get auditLogTitle => '谁查看过我的记录';

  @override
  String get noAccessLogged => '您的记录尚无访问记录。';

  @override
  String fieldsLabel(String fields) {
    return '涉及信息：$fields';
  }

  @override
  String get auditActorSystemFallback => '系统';

  @override
  String get auditActorEmergencyResponderUnverified => '急救人员 — 自行填报，未经核实';

  @override
  String get auditLogLegendIntro => '颜色和图标显示每次访问的敏感程度：';

  @override
  String get auditSeverityRoutine => '常规';

  @override
  String get auditSeverityAttention => '紧急访问';

  @override
  String get auditSeverityCritical => '失败的尝试';

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
  String get scanResultFoundTitle => '已找到病患';

  @override
  String scanResultAgeValue(String age) {
    return '年龄：$age';
  }

  @override
  String get scanResultBloodTypeUnknown => '记录中无此信息';

  @override
  String scanResultOmittedMedications(int count) {
    return '另有 $count 项药物记录未在此显示——未被标记为紧急重要信息。';
  }

  @override
  String scanResultOmittedConditions(int count) {
    return '另有 $count 项病症记录未在此显示——未被标记为紧急重要信息。';
  }

  @override
  String scanResultOmittedAllergies(int count) {
    return '另有 $count 项过敏记录未在此显示——未被标记为紧急重要信息。';
  }

  @override
  String get scanResultOfflineBanner =>
      '离线——直接从卡片读取，无网络连接。信息可能已过期；卡片上未存储姓名和年龄。';

  @override
  String get scanResultOfflinePlaceholderName => '持卡人（离线读取）';

  @override
  String get writeOfflineTagTooltip => '写入离线标签（仅限工作人员）';

  @override
  String get writeOfflineTagTitle => '写入离线标签';

  @override
  String get writeOfflineTagDesc =>
      '在网页控制台注册 NFC 卡后，复制显示的文本，然后触碰同一张实体卡将其直接写入标签。写入后，该卡的关键信息可在无网络的情况下读取——通过本应用或任何标准 NFC 读卡器均可。';

  @override
  String get writeOfflineTagTextLabel => '离线标签文本';

  @override
  String get writeOfflineTagButton => '触碰卡片以写入';

  @override
  String get writeOfflineTagWriting => '将卡片贴近手机背面…';

  @override
  String get writeOfflineTagSuccess => '写入成功。此卡现已离线携带其关键信息。';

  @override
  String get writeOfflineTagNotNdef => '此标签不支持 NDEF——请尝试其他实体卡。';

  @override
  String get writeOfflineTagNotWritable => '此标签为只读（已锁定），无法写入。';

  @override
  String get writeOfflineTagTooLarge =>
      '此文本对该标签的存储容量来说太大。请选择更少字段重新注册，或使用容量更大的标签。';

  @override
  String get writeOfflineTagWriteFailed => '写入标签失败。请重新触碰，并保持卡片稳定。';

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

  @override
  String get editProfileTitle => '编辑个人资料';

  @override
  String get readOnlyFieldsNote => '您的姓名、出生日期和身份证号码无法在此更改。如需更正，请联系您的诊所。';

  @override
  String get fullNameLabel => '全名';

  @override
  String get editableProfileSectionTitle => '联系方式';

  @override
  String get profileEmailLabel => '电子邮件';

  @override
  String get profilePhoneLabel => '电话';

  @override
  String get emergencyContactSectionTitle => '紧急联系人';

  @override
  String get emergencyContactNameLabel => '紧急联系人姓名';

  @override
  String get emergencyContactPhoneLabel => '紧急联系人电话';

  @override
  String get emergencyContactRelationshipLabel => '与您的关系';

  @override
  String get saveProfileButton => '保存更改';

  @override
  String get profileUpdatedSnack => '您的个人资料已更新。';

  @override
  String get profileUpdateFailedGeneric => '无法更新您的个人资料。请再试一次。';

  @override
  String get missingProfileBannerText => '您的个人资料尚未完善——点按以完善资料。';

  @override
  String get dismiss => '关闭';

  @override
  String get unexpectedErrorGeneric => '出现问题，请再试一次。';

  @override
  String get queueStatusButton => '排队状态';

  @override
  String get queueStatusTitle => '您的排队状态';

  @override
  String yourNumberLabel(String number) {
    return '您的号码：$number';
  }

  @override
  String nowServingLabel(String number) {
    return '现在叫号：$number';
  }

  @override
  String get nowServingNoneYet => '尚未叫号';

  @override
  String peopleAheadLabel(String count) {
    return '您前面还有 $count 人';
  }

  @override
  String get queueTicketDetailsTitle => '号码详情';

  @override
  String get queueStatusLabel => '状态';

  @override
  String get queueFacilityLabel => '医疗机构';

  @override
  String get queueDepartmentLabel => '科室';

  @override
  String get queueReasonLabel => '就诊原因';

  @override
  String get queueStatusWaiting => '等候中';

  @override
  String get queueStatusCalled => '已叫号';

  @override
  String get queueStatusDone => '已完成';

  @override
  String get queueStatusCancelled => '已取消';

  @override
  String get noActiveQueueTicketTitle => '暂无排队号码';

  @override
  String get noActiveQueueTicketDesc => '请在接待处办理登记以获取排队号码。';

  @override
  String get bookAppointmentTitle => '预约门诊';

  @override
  String get bookAppointmentFacilityLabel => '医疗机构';

  @override
  String get bookAppointmentOtherFacility => '其他（手动输入）';

  @override
  String get bookAppointmentFacilityManualHint => '机构名称';

  @override
  String get bookAppointmentUseFacility => '使用此机构';

  @override
  String get bookAppointmentDepartmentLabel => '科室';

  @override
  String get bookAppointmentAnyDepartment => '不限科室';

  @override
  String get bookAppointmentClinicianLabel => '医生';

  @override
  String get bookAppointmentAnyClinician => '不限医生';

  @override
  String get bookAppointmentPickDate => '选择日期';

  @override
  String get bookAppointmentNoSlots => '该日期暂无空档 — 请尝试其他日期。';

  @override
  String get bookAppointmentSuccess => '预约成功。';

  @override
  String get bookAppointmentSlotTaken => '该时段刚被预约 — 请选择其他时段。';

  @override
  String get bookAppointmentGenericError => '无法完成预约，请重试。';

  @override
  String get scanCheckinButton => '扫码登记';

  @override
  String get scanCheckinTitle => '扫码登记';

  @override
  String get scanCheckinDesc => '扫描接待处自助登记站的二维码，或在下方输入代码。无需工作人员协助，您将立即获得排队号码。';

  @override
  String get checkinReasonLabel => '就诊原因（可选）';

  @override
  String get checkinReasonHint => '例如：复诊、验血';

  @override
  String get stationCodeLabel => '站点代码';

  @override
  String get stationCodeHint => '例如：接待柜台打印的代码';

  @override
  String get checkinSubmitButton => '登记';

  @override
  String get checkinSubmitting => '正在登记…';

  @override
  String get requestRescheduleButton => '申请改期';

  @override
  String get rescheduleDialogTitle => '申请改期';

  @override
  String get rescheduleDialogDesc => '让诊所知道您无法赴约。他们会审核您的申请并与您跟进。';

  @override
  String get rescheduleReasonScheduleConflict => '日程冲突';

  @override
  String get rescheduleReasonUnwell => '身体不适/无法出行';

  @override
  String get rescheduleReasonTransport => '交通问题';

  @override
  String get rescheduleReasonOther => '其他';

  @override
  String get rescheduleOtherReasonLabel => '请说明原因';

  @override
  String get rescheduleOtherReasonRequired => '请说明原因。';

  @override
  String get rescheduleSubmitButton => '提交申请';

  @override
  String get rescheduleSubmitting => '正在提交…';

  @override
  String get reschedulePendingNote => '改期申请已提交 — 等待诊所回复';

  @override
  String get rescheduleAcceptedNote => '您的改期申请已获批准。';

  @override
  String get rescheduleRejectedNote => '您的改期申请已被拒绝。';

  @override
  String rescheduleClinicianNoteLabel(String note) {
    return '诊所备注：$note';
  }

  @override
  String previouslyScheduledLabel(String date) {
    return '原定时间：$date';
  }

  @override
  String get seniorMenuTooltip => '菜单';

  @override
  String get seniorMenuTitle => '菜单';

  @override
  String get seniorThemeToggleTooltip => '切换配色主题';

  @override
  String get confirmSwitchToStandardTitle => '切换到标准视图？';

  @override
  String get confirmSwitchToStandardBody =>
      '您将退出长者模式并查看常规应用。您可以随时在设置中重新开启长者模式。';

  @override
  String get confirmSwitchToStandardAction => '是，切换';

  @override
  String get confirmSignOutTitle => '登出？';

  @override
  String get confirmSignOutBody => '您需要重新登录才能查看您的健康记录。';

  @override
  String get confirmSignOutAction => '是，登出';
}
