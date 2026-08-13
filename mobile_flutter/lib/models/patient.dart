/// Mirrors the shape returned by `GET /patients/{patient_id}`
/// (see backend/app/routers/patients.py::_serialize_patient).
class Condition {
  final String id;
  final String name;
  final String status;
  final String? diagnosedAt;
  final bool isChronic;
  final bool criticalForEmergency;

  const Condition({
    required this.id,
    required this.name,
    required this.status,
    this.diagnosedAt,
    required this.isChronic,
    required this.criticalForEmergency,
  });

  factory Condition.fromJson(Map<String, dynamic> json) => Condition(
        id: json['id'] as String? ?? '',
        name: json['name'] as String? ?? '',
        status: json['status'] as String? ?? 'active',
        diagnosedAt: json['diagnosed_at'] as String?,
        isChronic: json['is_chronic'] as bool? ?? false,
        criticalForEmergency: json['critical_for_emergency'] as bool? ?? false,
      );
}

class Medication {
  final String id;
  final String drugName;
  final String? dosage;
  final String? frequency;
  final bool active;
  final String? prescribedByFacility;
  final String? startDate;
  final bool criticalForEmergency;

  const Medication({
    required this.id,
    required this.drugName,
    this.dosage,
    this.frequency,
    required this.active,
    this.prescribedByFacility,
    this.startDate,
    required this.criticalForEmergency,
  });

  factory Medication.fromJson(Map<String, dynamic> json) => Medication(
        id: json['id'] as String? ?? '',
        drugName: json['drug_name'] as String? ?? '',
        dosage: json['dosage'] as String?,
        frequency: json['frequency'] as String?,
        active: json['active'] as bool? ?? true,
        prescribedByFacility: json['prescribed_by_facility'] as String?,
        startDate: json['start_date'] as String?,
        criticalForEmergency: json['critical_for_emergency'] as bool? ?? false,
      );
}

class Allergy {
  final String id;
  final String substance;
  final String? reaction;
  final String severity;
  final bool criticalForEmergency;

  const Allergy({
    required this.id,
    required this.substance,
    this.reaction,
    required this.severity,
    required this.criticalForEmergency,
  });

  factory Allergy.fromJson(Map<String, dynamic> json) => Allergy(
        id: json['id'] as String? ?? '',
        substance: json['substance'] as String? ?? '',
        reaction: json['reaction'] as String?,
        severity: json['severity'] as String? ?? 'unknown',
        criticalForEmergency: json['critical_for_emergency'] as bool? ?? false,
      );
}

class Encounter {
  final String id;
  final String facilityName;
  final String encounterType;
  final String? reason;
  final String? notes;
  final String startedAt;

  const Encounter({
    required this.id,
    required this.facilityName,
    required this.encounterType,
    this.reason,
    this.notes,
    required this.startedAt,
  });

  factory Encounter.fromJson(Map<String, dynamic> json) => Encounter(
        id: json['id'] as String? ?? '',
        facilityName: json['facility_name'] as String? ?? '',
        encounterType: json['encounter_type'] as String? ?? '',
        reason: json['reason'] as String?,
        notes: json['notes'] as String?,
        startedAt: json['started_at'] as String? ?? '',
      );
}

/// Summary shape only -- matches _serialize_patient's "documents" list.
/// Full document content (raw_text/ai_summary) is fetched on demand via
/// GET /patients/{id}/documents/{document_id}, which is staff-only
/// server-side (403 for a patient token) -- so this app only ever lists
/// document metadata, never fetches or renders document detail/content.
class ClinicalDocumentSummary {
  final String id;
  final String docType;
  final String originalFilename;
  final String? uploadedByFacility;
  final String uploadedAt;

  const ClinicalDocumentSummary({
    required this.id,
    required this.docType,
    required this.originalFilename,
    this.uploadedByFacility,
    required this.uploadedAt,
  });

  factory ClinicalDocumentSummary.fromJson(Map<String, dynamic> json) => ClinicalDocumentSummary(
        id: json['id'] as String? ?? '',
        docType: json['doc_type'] as String? ?? '',
        originalFilename: json['original_filename'] as String? ?? '',
        uploadedByFacility: json['uploaded_by_facility'] as String?,
        uploadedAt: json['uploaded_at'] as String? ?? '',
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
  final List<ClinicalDocumentSummary> documents;
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
    this.documents = const [],
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
  /// allergies/encounters/documents, which that endpoint's response
  /// (PatientOut-shaped, not the full record) doesn't include.
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
        documents: documents,
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
        documents: (json['documents'] as List<dynamic>? ?? [])
            .map((e) => ClinicalDocumentSummary.fromJson(e as Map<String, dynamic>))
            .toList(),
        email: json['email'] as String?,
        emergencyContactName: json['emergency_contact_name'] as String?,
        emergencyContactPhone: json['emergency_contact_phone'] as String?,
        emergencyContactRelationship: json['emergency_contact_relationship'] as String?,
      );
}
