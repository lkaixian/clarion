/// A single allergy entry as returned by the emergency-scan endpoints
/// (`POST /emergency/scan` / `POST /emergency/nfc/scan`). Deliberately a
/// separate, smaller shape from models/patient.dart's `Allergy` -- there's
/// no `id`/`criticalForEmergency` flag here because the backend has
/// already filtered the patient's full allergy list down to just the
/// emergency-relevant entries before building this response.
class ScanAllergy {
  final String substance;
  final String severity;
  final String? reaction;

  const ScanAllergy({required this.substance, required this.severity, this.reaction});

  factory ScanAllergy.fromJson(Map<String, dynamic> json) => ScanAllergy(
        substance: json['substance'] as String? ?? '',
        severity: json['severity'] as String? ?? '',
        reaction: json['reaction'] as String?,
      );
}

/// A single medication entry as returned by the emergency-scan endpoints.
/// Note this is a *different*, richer shape than the bare drug-name
/// strings this field used to be -- the backend now sends dosage/frequency
/// alongside the name so a responder can see exactly what's being taken
/// and how, not just that the patient takes "it".
class ScanMedication {
  final String drugName;
  final String? dosage;
  final String? frequency;

  const ScanMedication({required this.drugName, this.dosage, this.frequency});

  factory ScanMedication.fromJson(Map<String, dynamic> json) => ScanMedication(
        drugName: json['drug_name'] as String? ?? '',
        dosage: json['dosage'] as String?,
        frequency: json['frequency'] as String?,
      );
}

/// Typed shape of the emergency-scan response -- `POST /emergency/scan`
/// (QR / card-reference lookup) and `POST /emergency/nfc/scan` (NFC UID
/// lookup) share this exact response shape, so both
/// `ApiClient.scanEmergencyCard` and `ApiClient.scanNfcCard` results are
/// parsed through this one model.
///
/// Introduced to replace rendering the raw `Map<String, dynamic>` as a
/// flat `key: value` text dump in EmergencyScannerScreen -- that dump
/// didn't clearly show medication dosage/frequency and gave no visual
/// structure for a first responder skimming under pressure.
class EmergencyScanResult {
  final String fullName;
  final String dateOfBirth;
  final String? bloodType;
  final List<ScanAllergy> allergies;
  final List<ScanMedication> medications;
  final List<String> conditions;

  /// Category name -> count of additional, non-critical items on file
  /// that the backend deliberately left out of this response (e.g.
  /// `{"medications": 2, "conditions": 1}`). Only keys for categories that
  /// actually had something filtered are present here -- may be entirely
  /// empty when nothing was omitted. This is surfaced to the responder as
  /// a safety-communication notice (see EmergencyScannerScreen), not just
  /// decoration: they should know the list they're looking at might not
  /// be the *complete* list of e.g. medications on file.
  final Map<String, int> omittedNonCritical;

  const EmergencyScanResult({
    required this.fullName,
    required this.dateOfBirth,
    this.bloodType,
    required this.allergies,
    required this.medications,
    required this.conditions,
    this.omittedNonCritical = const {},
  });

  factory EmergencyScanResult.fromJson(Map<String, dynamic> json) => EmergencyScanResult(
        fullName: json['full_name'] as String? ?? '',
        dateOfBirth: json['date_of_birth'] as String? ?? '',
        bloodType: json['blood_type'] as String?,
        allergies: (json['allergies'] as List<dynamic>? ?? [])
            .map((e) => ScanAllergy.fromJson(e as Map<String, dynamic>))
            .toList(),
        medications: (json['medications'] as List<dynamic>? ?? [])
            .map((e) => ScanMedication.fromJson(e as Map<String, dynamic>))
            .toList(),
        conditions: (json['conditions'] as List<dynamic>? ?? []).map((e) => e.toString()).toList(),
        // `omitted_non_critical` is new and additive -- may be entirely
        // absent from the response (older-shaped payload, or nothing was
        // omitted), in which case this just defaults to an empty map and
        // no category shows an omitted-items notice.
        omittedNonCritical: (json['omitted_non_critical'] as Map<String, dynamic>? ?? {})
            .map((key, value) => MapEntry(key, (value as num?)?.toInt() ?? 0)),
      );
}
