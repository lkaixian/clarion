/// Mirrors the backend's `UserOut` schema (see backend/app/schemas.py).
class MBUser {
  final String id;
  final String email;
  final String fullName;
  final String role; // admin | clinician | records_officer | patient | emergency_responder
  final String? facility;
  final String? patientId;
  // Set by staff when they create/reset an account with a temporary
  // password. When true, `_AuthGate` (see app.dart) routes to
  // ChangePasswordScreen instead of Home/SeniorHome until the user picks
  // their own password. Defaults to false so older cached user JSON
  // (saved before the backend added this field) still parses fine.
  final bool mustChangePassword;
  // Informational only (not a hard gate like mustChangePassword) — a list
  // of PatientOut-side field names (e.g. "email", "phone",
  // "emergency_contact_name", "emergency_contact_phone") still blank on
  // this patient's profile. Empty for non-patient roles or a patient with
  // a complete profile. Drives the dismissible "complete your profile"
  // banner on Home/SeniorHome — see AuthProvider.missingProfileFields.
  // Defaults to empty so older cached user JSON (saved before the backend
  // added this field) still parses fine, same reasoning as
  // mustChangePassword above.
  final List<String> missingProfileFields;
  // Family profiles: true when the session acts for a profile other than the
  // login's own; [homePatientId] is the login's own patient record.
  final bool actingFor;
  final String? homePatientId;
  // Every role this login may act as (length 1 for ordinary accounts) and the
  // responder tier ('community' | 'paramedic') when it holds that role.
  final List<String> roles;
  final String? responderTier;

  const MBUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    this.facility,
    this.patientId,
    this.mustChangePassword = false,
    this.missingProfileFields = const [],
    this.actingFor = false,
    this.homePatientId,
    List<String>? roles,
    this.responderTier,
  }) : roles = roles ?? const [];

  factory MBUser.fromJson(Map<String, dynamic> json) => MBUser(
        id: json['id'] as String,
        email: json['email'] as String,
        fullName: json['full_name'] as String,
        role: json['role'] as String,
        facility: json['facility'] as String?,
        patientId: json['patient_id'] as String?,
        mustChangePassword: json['must_change_password'] as bool? ?? false,
        missingProfileFields: (json['missing_profile_fields'] as List<dynamic>? ?? [])
            .map((e) => e.toString())
            .toList(),
        actingFor: json['acting_for'] as bool? ?? false,
        homePatientId: json['home_patient_id'] as String?,
        roles: (json['roles'] as List<dynamic>?)?.map((e) => e.toString()).toList() ?? [json['role'] as String],
        responderTier: json['responder_tier'] as String?,
      );

  MBUser copyWith({bool? mustChangePassword, List<String>? missingProfileFields}) => MBUser(
        id: id,
        email: email,
        fullName: fullName,
        role: role,
        facility: facility,
        patientId: patientId,
        mustChangePassword: mustChangePassword ?? this.mustChangePassword,
        missingProfileFields: missingProfileFields ?? this.missingProfileFields,
        actingFor: actingFor,
        homePatientId: homePatientId,
        roles: roles,
        responderTier: responderTier,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'full_name': fullName,
        'role': role,
        'facility': facility,
        'patient_id': patientId,
        'must_change_password': mustChangePassword,
        'missing_profile_fields': missingProfileFields,
        'acting_for': actingFor,
        'home_patient_id': homePatientId,
        'roles': roles,
        'responder_tier': responderTier,
      };
}
