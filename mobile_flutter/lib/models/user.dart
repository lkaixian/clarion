/// Mirrors the backend's `UserOut` schema (see backend/app/schemas.py).
class MBUser {
  final String id;
  final String email;
  final String fullName;
  final String role; // admin | clinician | records_officer | patient | emergency_responder
  final String? facility;
  final String? patientId;

  const MBUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.role,
    this.facility,
    this.patientId,
  });

  factory MBUser.fromJson(Map<String, dynamic> json) => MBUser(
        id: json['id'] as String,
        email: json['email'] as String,
        fullName: json['full_name'] as String,
        role: json['role'] as String,
        facility: json['facility'] as String?,
        patientId: json['patient_id'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'full_name': fullName,
        'role': role,
        'facility': facility,
        'patient_id': patientId,
      };
}
