/// One entry of `GET /profiles` (first item is the login's own profile).
class FamilyProfile {
  const FamilyProfile({
    required this.patientId,
    required this.fullName,
    this.dateOfBirth,
    this.age,
    this.isSelf = false,
    this.relationCode,
    this.linkId,
    this.pendingApproval = false,
  });

  final String patientId;
  final String fullName;
  final String? dateOfBirth;
  final int? age;
  final bool isSelf;
  final String? relationCode;
  final String? linkId;
  /// An adult with their own login who has not yet approved me.
  final bool pendingApproval;

  factory FamilyProfile.fromJson(Map<String, dynamic> j) => FamilyProfile(
        patientId: j['patient_id'] as String,
        fullName: j['full_name'] as String,
        dateOfBirth: j['date_of_birth'] as String?,
        age: (j['age'] as num?)?.toInt(),
        isSelf: j['is_self'] as bool? ?? false,
        relationCode: j['relation_code']?.toString(),
        linkId: j['link_id']?.toString(),
        pendingApproval: j['pending_approval'] as bool? ?? false,
      );
}

/// One entry of `GET /profiles/guardians`: someone who can act for me.
class Guardian {
  const Guardian({
    required this.linkId,
    required this.fullName,
    this.relationCode,
    this.approved = true,
    this.pending = false,
  });
  final String linkId;
  final String fullName;
  final String? relationCode;
  final bool approved;
  /// A carer is waiting for MY approval.
  final bool pending;

  factory Guardian.fromJson(Map<String, dynamic> j) => Guardian(
        linkId: j['link_id'].toString(),
        fullName: j['full_name'] as String,
        relationCode: j['relation_code']?.toString(),
        approved: j['approved'] as bool? ?? true,
        pending: j['pending'] as bool? ?? false,
      );
}

/// Relationship codes accepted by `POST /profiles`.
const kRelationCodes = ['1', '3', '4', '9', '10', '12', '99'];
