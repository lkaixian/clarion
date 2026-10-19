import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';

/// Localised label for a `/booking/categories` code; falls back to the
/// server's own label (or the raw code) for a category this build predates.
String bookingCategoryLabel(AppLocalizations l10n, String code, [String? fallback]) {
  switch (code) {
    case 'general':
      return l10n.bkCatGeneral;
    case 'chronic':
      return l10n.bkCatChronic;
    case 'vaccination':
      return l10n.bkCatVaccination;
    case 'maternal_child':
      return l10n.bkCatMaternalChild;
    case 'dental':
      return l10n.bkCatDental;
    case 'screening':
      return l10n.bkCatScreening;
    case 'mental_health':
      return l10n.bkCatMentalHealth;
    case 'physio':
      return l10n.bkCatPhysio;
    default:
      return fallback != null && fallback.isNotEmpty ? fallback : code;
  }
}

IconData bookingCategoryIcon(String code) {
  switch (code) {
    case 'general':
      return Icons.medical_services_outlined;
    case 'chronic':
      return Icons.monitor_heart_outlined;
    case 'vaccination':
      return Icons.vaccines_outlined;
    case 'maternal_child':
      return Icons.child_friendly_outlined;
    case 'dental':
      return Icons.sentiment_satisfied_alt_outlined;
    case 'screening':
      return Icons.fact_check_outlined;
    case 'mental_health':
      return Icons.psychology_outlined;
    case 'physio':
      return Icons.accessibility_new_outlined;
    default:
      return Icons.local_hospital_outlined;
  }
}

String bookingRelationshipLabel(AppLocalizations l10n, String code) {
  switch (code) {
    case 'child':
      return l10n.bkRelChild;
    case 'parent':
      return l10n.bkRelParent;
    case 'spouse':
      return l10n.bkRelSpouse;
    case 'sibling':
      return l10n.bkRelSibling;
    case 'relative':
      return l10n.bkRelRelative;
    default:
      return l10n.bkRelOther;
  }
}

/// "Aisyah Binti Ali (Child)".
String bookingPersonLabel(AppLocalizations l10n, String name, String? relationship) =>
    relationship == null || relationship.isEmpty
        ? name
        : '$name (${bookingRelationshipLabel(l10n, relationship)})';
