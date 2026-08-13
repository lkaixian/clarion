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

  const MBUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    this.facility,
    this.patientId,
    this.mustChangePassword = false,
  });

  factory MBUser.fromJson(Map<String, dynamic> json) => MBUser(
        id: json['id'] as String,
        email: json['email'] as String,
        fullName: json['full_name'] as String,
        role: json['role'] as String,
        facility: json['facility'] as String?,
        patientId: json['patient_id'] as String?,
        mustChangePassword: json['must_change_password'] as bool? ?? false,
      );

  MBUser copyWith({bool? mustChangePassword}) => MBUser(
        id: id,
        email: email,
        fullName: fullName,
        role: role,
        facility: facility,
        patientId: patientId,
        mustChangePassword: mustChangePassword ?? this.mustChangePassword,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'full_name': fullName,
        'role': role,
        'facility': facility,
        'patient_id': patientId,
        'must_change_password': mustChangePassword,
      };
}
