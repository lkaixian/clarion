/// Mirrors the shape returned by `GET /patients/{patient_id}`
/// (see backend/app/routers/patients.py::_serialize_patient).
class Condition {
  final String name;
  final String status;
  final bool isChronic;

  const Condition({required this.name, required this.status, required this.isChronic});

  factory Condition.fromJson(Map<String, dynamic> json) => Condition(
        name: json['name'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
        isChronic: json['is_chronic'] as bool? ?? false,
      );
}

class Medication {
  final String drugName;
  final bool active;
  final String? prescribedByFacility;

  const Medication({required this.drugName, required this.active, this.prescribedByFacility});

  factory Medication.fromJson(Map<String, dynamic> json) => Medication(
        drugName: json['drug_name'] as String? ?? '',
        active: json['active'] as bool? ?? true,
        prescribedByFacility: json['prescribed_by_facility'] as String?,
      );
}

class Allergy {
  final String substance;
  final String severity;

  const Allergy({required this.substance, required this.severity});

  factory Allergy.fromJson(Map<String, dynamic> json) => Allergy(
        substance: json['substance'] as String? ?? '',
        severity: json['severity'] as String? ?? 'unknown',
      );
}

class Encounter {
  final String facilityName;
  final String encounterType;
  final String startedAt;

  const Encounter({required this.facilityName, required this.encounterType, required this.startedAt});

  factory Encounter.fromJson(Map<String, dynamic> json) => Encounter(
        facilityName: json['facility_name'] as String? ?? '',
        encounterType: json['encounter_type'] as String? ?? '',
        startedAt: json['started_at'] as String? ?? '',
      );
}

class Patient {
  final String id;
  final String fullName;
  final String dateOfBirth;
  final String? gender;
  final String? nationalId;
  final String? bloodType;
  final String? phone;
  final bool seniorCitizenMode;
  final List<Condition> conditions;
  final List<Medication> medications;
  final List<Allergy> allergies;
  final List<Encounter> encounters;
  // Patient-owned contact/profile fields, editable via
  // PATCH /patients/{id}/profile (see ApiClient.updatePatientProfile /
  // EditProfileScreen). Distinct from the User account's login email — see
  // backend/app/models.py::Patient for the same distinction server-side.
  final String? email;
  final String? emergencyContactName;
  final String? emergencyContactPhone;
  final String? emergencyContactRelationship;

  const Patient({
    required this.id,
    required this.fullName,
    required this.dateOfBirth,
    this.gender,
    this.nationalId,
    this.bloodType,
    this.phone,
    required this.seniorCitizenMode,
    required this.conditions,
    required this.medications,
    required this.allergies,
    required this.encounters,
    this.email,
    this.emergencyContactName,
    this.emergencyContactPhone,
    this.emergencyContactRelationship,
  });

  List<Medication> get activeMedications => medications.where((m) => m.active).toList();

  /// Merges in just the editable contact/profile fields (the subset
  /// `PATCH /patients/{id}/profile` can change) — used by
  /// PatientProvider.updateProfile to fold the PATCH response back into an
  /// already-loaded full record without losing conditions/medications/
  /// allergies/encounters, which that endpoint's response (PatientOut-
  /// shaped, not the full record) doesn't include.
  Patient copyWith({
    String? phone,
    String? email,
    String? emergencyContactName,
    String? emergencyContactPhone,
    String? emergencyContactRelationship,
  }) =>
      Patient(
        id: id,
        fullName: fullName,
        dateOfBirth: dateOfBirth,
        gender: gender,
        nationalId: nationalId,
        bloodType: bloodType,
        phone: phone ?? this.phone,
        seniorCitizenMode: seniorCitizenMode,
        conditions: conditions,
        medications: medications,
        allergies: allergies,
        encounters: encounters,
        email: email ?? this.email,
        emergencyContactName: emergencyContactName ?? this.emergencyContactName,
        emergencyContactPhone: emergencyContactPhone ?? this.emergencyContactPhone,
        emergencyContactRelationship: emergencyContactRelationship ?? this.emergencyContactRelationship,
      );

  factory Patient.fromJson(Map<String, dynamic> json) => Patient(
        id: json['id'] as String,
        fullName: json['full_name'] as String? ?? '',
        dateOfBirth: json['date_of_birth'] as String? ?? '',
        gender: json['gender'] as String?,
        nationalId: json['national_id'] as String?,
        bloodType: json['blood_type'] as String?,
        phone: json['phone'] as String?,
        seniorCitizenMode: json['senior_citizen_mode'] as bool? ?? false,
        conditions: (json['conditions'] as List<dynamic>? ?? [])
            .map((e) => Condition.fromJson(e as Map<String, dynamic>))
            .toList(),
        medications: (json['medications'] as List<dynamic>? ?? [])
            .map((e) => Medication.fromJson(e as Map<String, dynamic>))
            .toList(),
        allergies: (json['allergies'] as List<dynamic>? ?? [])
            .map((e) => Allergy.fromJson(e as Map<String, dynamic>))
            .toList(),
        encounters: (json['encounters'] as List<dynamic>? ?? [])
            .map((e) => Encounter.fromJson(e as Map<String, dynamic>))
            .toList(),
        email: json['email'] as String?,
        emergencyContactName: json['emergency_contact_name'] as String?,
        emergencyContactPhone: json['emergency_contact_phone'] as String?,
        emergencyContactRelationship: json['emergency_contact_relationship'] as String?,
      );
}
