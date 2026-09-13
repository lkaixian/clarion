import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/booking.dart';
import '../providers/patient_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../theme/app_theme.dart';

/// P3.10: patient self-service pre-registration — pick a
/// facility/department/doctor, a date, then a bookable time slot. Every
/// slot offered is recomputed live server-side (GET /patients/
/// appointment-slots) and re-validated again on submit (POST .../self-book)
/// -- this screen never invents/rounds a time itself, it only ever books
/// exactly the `scheduledAt` a slot object already carried.
///
/// There is no "list all facilities" backend endpoint (facilities aren't a
/// formal enumerable table anywhere in this system — see
/// backend/app/routers/patients.py::list_booking_options's docstring), so
/// the facility picker is built from the patient's OWN encounter history
/// (facilities they've actually been seen at). A brand-new patient with no
/// encounters yet falls back to typing a facility name manually — a
/// deliberate, documented limitation, not a bug: this app has no other
/// source of truth for "which hospitals exist".
class BookAppointmentScreen extends StatefulWidget {
  const BookAppointmentScreen({super.key});

  @override
  State<BookAppointmentScreen> createState() => _BookAppointmentScreenState();
}

class _BookAppointmentScreenState extends State<BookAppointmentScreen> {
  static const _otherFacility = '__other__';

  final _manualFacilityController = TextEditingController();

  String? _facility; // resolved facility name actually in use
  String? _facilityChoice; // raw dropdown selection (may be _otherFacility)
  BookingOptions? _options;
  bool _loadingOptions = false;
  String? _department;
  String? _clinicianId;
  DateTime? _date;
  List<AppointmentSlot>? _slots;
  bool _loadingSlots = false;
  bool _booking = false;
  String? _error;

  @override
  void dispose() {
    _manualFacilityController.dispose();
    super.dispose();
  }

  List<String> get _knownFacilities {
    final patient = context.read<PatientProvider>().patient;
    if (patient == null) return [];
    return patient.encounters.map((e) => e.facilityName).toSet().toList()..sort();
  }

  Future<void> _onFacilityResolved(String facility) async {
    setState(() {
      _facility = facility;
      _options = null;
      _department = null;
      _clinicianId = null;
      _date = null;
      _slots = null;
      _error = null;
      _loadingOptions = true;
    });
    try {
      final options = await context.read<ApiClient>().getBookingOptions(facility);
      if (!mounted) return;
      setState(() => _options = options);
    } catch (e) {
      if (!mounted) return;
      // Booking options are optional polish (department/doctor narrowing) —
      // a facility with none configured, or a lookup failure, still lets
      // the patient book "any doctor" by date alone.
      setState(() => _options = const BookingOptions(departments: [], clinicians: []));
    } finally {
      if (mounted) setState(() => _loadingOptions = false);
    }
  }

  List<BookingClinician> get _visibleClinicians {
    final all = _options?.clinicians ?? [];
    if (_department == null) return all;
    return all.where((c) => c.department == _department).toList();
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final firstSelectable = DateTime(now.year, now.month, now.day + 1);
    final picked = await showDatePicker(
      context: context,
      initialDate: firstSelectable,
      firstDate: firstSelectable,
      lastDate: firstSelectable.add(const Duration(days: 90)),
    );
    if (picked == null) return;
    setState(() {
      _date = picked;
      _slots = null;
      _error = null;
    });
    await _loadSlots();
  }

  Future<void> _loadSlots() async {
    final facility = _facility;
    final date = _date;
    if (facility == null || date == null) return;
    setState(() {
      _loadingSlots = true;
      _error = null;
    });
    try {
      final slots = await context.read<ApiClient>().getAppointmentSlots(
        facilityName: facility,
        date: DateFormat('yyyy-MM-dd').format(date),
        department: _department,
        clinicianId: _clinicianId,
      );
      if (!mounted) return;
      setState(() => _slots = slots);
    } catch (e) {
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      setState(() => _error = e is ApiException ? e.message : l10n.bookAppointmentGenericError);
    } finally {
      if (mounted) setState(() => _loadingSlots = false);
    }
  }

  Future<void> _bookSlot(AppointmentSlot slot) async {
    final l10n = AppLocalizations.of(context);
    final patient = context.read<PatientProvider>().patient;
    final facility = _facility;
    if (patient == null || facility == null) return;

    setState(() {
      _booking = true;
      _error = null;
    });
    try {
      await context.read<ApiClient>().selfBookAppointment(
        patientId: patient.id,
        facilityName: facility,
        department: _department,
        clinicianId: slot.clinicianId ?? _clinicianId,
        scheduledAt: slot.scheduledAt,
      );
      if (!mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(l10n.bookAppointmentSuccess)));
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 409) {
        // Someone else took it — refresh so the list reflects reality
        // instead of leaving a now-stale slot tappable again.
        setState(() => _error = l10n.bookAppointmentSlotTaken);
        await _loadSlots();
      } else {
        setState(() => _error = e.message);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = l10n.bookAppointmentGenericError);
    } finally {
      if (mounted) setState(() => _booking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final knownFacilities = _knownFacilities;
    final usingManualFacility = _facilityChoice == _otherFacility || knownFacilities.isEmpty;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.bookAppointmentTitle)),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            l10n.bookAppointmentFacilityLabel,
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
          ),
          const SizedBox(height: 8),
          if (knownFacilities.isNotEmpty)
            DropdownButtonFormField<String>(
              initialValue: _facilityChoice,
              decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
              items: [
                ...knownFacilities.map(
                  (f) => DropdownMenuItem(value: f, child: Text(f, overflow: TextOverflow.ellipsis)),
                ),
                DropdownMenuItem(value: _otherFacility, child: Text(l10n.bookAppointmentOtherFacility)),
              ],
              onChanged: (value) {
                setState(() => _facilityChoice = value);
                if (value != null && value != _otherFacility) _onFacilityResolved(value);
              },
            ),
          if (usingManualFacility) ...[
            if (knownFacilities.isNotEmpty) const SizedBox(height: 8),
            TextField(
              controller: _manualFacilityController,
              decoration: InputDecoration(
                border: const OutlineInputBorder(),
                isDense: true,
                labelText: l10n.bookAppointmentFacilityManualHint,
              ),
              onSubmitted: (value) {
                final trimmed = value.trim();
                if (trimmed.isNotEmpty) _onFacilityResolved(trimmed);
              },
            ),
            const SizedBox(height: 6),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () {
                  final trimmed = _manualFacilityController.text.trim();
                  if (trimmed.isNotEmpty) _onFacilityResolved(trimmed);
                },
                child: Text(l10n.bookAppointmentUseFacility),
              ),
            ),
          ],
          if (_loadingOptions) ...[
            const SizedBox(height: 16),
            const Center(child: CircularProgressIndicator()),
          ],
          if (_facility != null && !_loadingOptions) ...[
            const SizedBox(height: 20),
            Text(
              l10n.bookAppointmentDepartmentLabel,
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String?>(
              initialValue: _department,
              decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
              items: [
                DropdownMenuItem(value: null, child: Text(l10n.bookAppointmentAnyDepartment)),
                ...(_options?.departments ?? []).map(
                  (d) => DropdownMenuItem(value: d, child: Text(d)),
                ),
              ],
              onChanged: (value) => setState(() {
                _department = value;
                _clinicianId = null;
                _slots = null;
              }),
            ),
            const SizedBox(height: 16),
            Text(
              l10n.bookAppointmentClinicianLabel,
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String?>(
              initialValue: _clinicianId,
              decoration: const InputDecoration(border: OutlineInputBorder(), isDense: true),
              items: [
                DropdownMenuItem(value: null, child: Text(l10n.bookAppointmentAnyClinician)),
                ..._visibleClinicians.map(
                  (c) => DropdownMenuItem(value: c.id, child: Text(c.fullName)),
                ),
              ],
              onChanged: (value) => setState(() {
                _clinicianId = value;
                _slots = null;
              }),
            ),
            const SizedBox(height: 20),
            OutlinedButton.icon(
              onPressed: _pickDate,
              icon: const Icon(Icons.calendar_month),
              label: Text(
                _date == null
                    ? l10n.bookAppointmentPickDate
                    : DateFormat('d MMM yyyy').format(_date!),
              ),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: context.palette.emergency, fontSize: 13)),
          ],
          if (_loadingSlots) ...[
            const SizedBox(height: 20),
            const Center(child: CircularProgressIndicator()),
          ],
          if (_slots != null && !_loadingSlots) ...[
            const SizedBox(height: 16),
            if (_slots!.isEmpty)
              Text(l10n.bookAppointmentNoSlots, style: TextStyle(color: context.palette.textMuted))
            else
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _slots!.map((slot) {
                  final label = DateFormat('h:mm a').format(slot.scheduledAt.toLocal());
                  final full = slot.clinicianName != null ? '$label · ${slot.clinicianName}' : label;
                  return ActionChip(
                    label: Text(full),
                    onPressed: _booking ? null : () => _bookSlot(slot),
                  );
                }).toList(),
              ),
          ],
          if (_booking) ...[
            const SizedBox(height: 16),
            const Center(child: CircularProgressIndicator()),
          ],
        ],
      ),
    );
  }
}
