import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/booking.dart';
import '../providers/patient_provider.dart';
import '../providers/reminders_provider.dart';
import '../services/api_client.dart';
import '../services/api_exception.dart';
import '../services/location_service.dart';
import '../services/mysejahtera_launcher.dart';
import '../theme/app_theme.dart';
import '../widgets/booking_labels.dart';
import '../widgets/common.dart';
import '../widgets/loading_view.dart';
import 'reminders_screen.dart';

enum _Step { category, location, timetable, person, confirm, done }

/// Online booking v2: category -> hospital (typed search or GPS) -> date and
/// time -> who is it for -> confirm. One stateful flow; Back walks the steps
/// (see the PopScope in [build]). The hospital timetable is whatever the
/// hospital configured in its admin console; this screen never invents a
/// slot, it books exactly the `start` string a slot carried.
///
/// [openMySejahtera] and [locate] are injectable so tests need no platform
/// channels.
class BookAppointmentScreen extends StatefulWidget {
  const BookAppointmentScreen({
    super.key,
    this.openMySejahtera = MySejahteraLauncher.open,
    this.locate = locateWithGeolocator,
  });

  final Future<bool> Function() openMySejahtera;
  final LocateFn locate;

  @override
  State<BookAppointmentScreen> createState() => _BookAppointmentScreenState();
}

class _BookAppointmentScreenState extends State<BookAppointmentScreen> {
  _Step _step = _Step.category;
  bool _bannerVisible = true;

  // Step 1
  List<BookingCategory>? _categories;
  bool _loadingCategories = true;
  String? _categoriesError;
  BookingCategory? _category;

  // Step 2
  final _searchController = TextEditingController();
  LocationFix? _fix;
  String? _locationMessage;
  bool _locating = false;
  List<BookingFacility>? _facilities;
  bool _loadingFacilities = false;
  String? _facilitiesError;
  int _facilitiesRequest = 0;
  BookingFacility? _facility;

  // Step 3
  FacilityAvailability? _availability;
  bool _loadingAvailability = false;
  String? _availabilityError;
  String? _date;
  List<BookingSlot>? _slots;
  bool _loadingSlots = false;
  String? _slotsError;
  int _slotsRequest = 0;
  BookingSlot? _slot;

  // Step 4
  bool _forSelf = true;
  BookingProfile? _person;
  List<BookingProfile>? _profiles;
  bool _loadingProfiles = false;
  String? _profilesError;

  // Step 5
  final _reasonController = TextEditingController();
  bool _submitting = false;
  String? _submitError;

  @override
  void initState() {
    super.initState();
    _loadCategories();
  }

  @override
  void dispose() {
    _searchController.dispose();
    _reasonController.dispose();
    super.dispose();
  }

  ApiClient get _api => context.read<ApiClient>();

  String _message(Object e) {
    final l10n = AppLocalizations.of(context);
    if (e is ApiException) return e.isUnreachable ? l10n.bkNetworkError : e.message;
    return l10n.bookAppointmentGenericError;
  }

  // ---- loading ------------------------------------------------------------

  Future<void> _loadCategories() async {
    setState(() {
      _loadingCategories = true;
      _categoriesError = null;
    });
    try {
      final list = await _api.getBookingCategories();
      if (!mounted) return;
      setState(() => _categories = list);
    } catch (e) {
      if (!mounted) return;
      setState(() => _categoriesError = _message(e));
    } finally {
      if (mounted) setState(() => _loadingCategories = false);
    }
  }

  Future<void> _searchFacilities() async {
    final category = _category;
    if (category == null) return;
    final request = ++_facilitiesRequest;
    setState(() {
      _loadingFacilities = true;
      _facilitiesError = null;
    });
    try {
      final list = await _api.getBookingFacilities(
        category: category.code,
        q: _searchController.text,
        lat: _fix?.latitude,
        lng: _fix?.longitude,
      );
      if (!mounted || request != _facilitiesRequest) return;
      setState(() => _facilities = list);
    } catch (e) {
      if (!mounted || request != _facilitiesRequest) return;
      setState(() {
        _facilities = null;
        _facilitiesError = _message(e);
      });
    } finally {
      if (mounted && request == _facilitiesRequest) setState(() => _loadingFacilities = false);
    }
  }

  Future<void> _useMyLocation() async {
    final l10n = AppLocalizations.of(context);
    setState(() {
      _locating = true;
      _locationMessage = null;
    });
    try {
      final fix = await widget.locate();
      if (!mounted) return;
      setState(() => _fix = fix);
    } on LocationException catch (e) {
      if (!mounted) return;
      setState(() {
        _fix = null;
        _locationMessage = switch (e.failure) {
          LocationFailure.denied || LocationFailure.deniedForever => l10n.bkLocationDenied,
          LocationFailure.serviceOff => l10n.bkLocationOff,
          LocationFailure.unavailable => l10n.bkLocationFailed,
        };
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _fix = null;
        _locationMessage = l10n.bkLocationFailed;
      });
    } finally {
      if (mounted) setState(() => _locating = false);
    }
    // Typed search keeps working whatever happened above; re-run it so the
    // list reflects the new (or cleared) position.
    if (mounted) await _searchFacilities();
  }

  Future<void> _loadAvailability({String? preferDate}) async {
    final facility = _facility;
    final category = _category;
    if (facility == null || category == null) return;
    setState(() {
      _loadingAvailability = true;
      _availabilityError = null;
      _slots = null;
      _slotsError = null;
      _slot = null;
    });
    try {
      final result = await _api.getBookingAvailability(facility.facilityName, category.code);
      if (!mounted || _facility != facility) return;
      setState(() => _availability = result);
      final preferred = result.days.where((d) => d.date == preferDate && d.openSlots > 0).firstOrNull;
      final target = preferred ?? firstOpenDay(result.days);
      if (target != null) {
        await _selectDate(target.date);
      } else {
        setState(() => _date = null);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _availabilityError = _message(e));
    } finally {
      if (mounted) setState(() => _loadingAvailability = false);
    }
  }

  Future<void> _selectDate(String date) async {
    final facility = _facility;
    final category = _category;
    if (facility == null || category == null) return;
    final request = ++_slotsRequest;
    setState(() {
      _date = date;
      _slots = null;
      _slot = null;
      _slotsError = null;
      _loadingSlots = true;
    });
    try {
      final list = await _api.getBookingSlots(facility.facilityName, category.code, date);
      if (!mounted || request != _slotsRequest) return;
      setState(() => _slots = list);
    } catch (e) {
      if (!mounted || request != _slotsRequest) return;
      setState(() => _slotsError = _message(e));
    } finally {
      if (mounted && request == _slotsRequest) setState(() => _loadingSlots = false);
    }
  }

  Future<void> _loadProfiles() async {
    setState(() {
      _loadingProfiles = true;
      _profilesError = null;
    });
    try {
      final list = await _api.getBookingProfiles();
      if (!mounted) return;
      setState(() => _profiles = list);
    } catch (e) {
      if (!mounted) return;
      setState(() => _profilesError = _message(e));
    } finally {
      if (mounted) setState(() => _loadingProfiles = false);
    }
  }

  // ---- navigation ---------------------------------------------------------

  void _pickCategory(BookingCategory c) {
    setState(() {
      if (_category?.code != c.code) {
        _facilities = null;
        _facility = null;
        _availability = null;
        _date = null;
        _slots = null;
        _slot = null;
      }
      _category = c;
      _step = _Step.location;
    });
    _searchFacilities();
  }

  void _pickFacility(BookingFacility f) {
    setState(() {
      _facility = f;
      _availability = null;
      _date = null;
      _slots = null;
      _slot = null;
      _step = _Step.timetable;
    });
    _loadAvailability();
  }

  void _toPerson() {
    setState(() => _step = _Step.person);
    if (_profiles == null) _loadProfiles();
  }

  void _back() {
    setState(() {
      _submitError = null;
      _step = switch (_step) {
        _Step.location => _Step.category,
        _Step.timetable => _Step.location,
        _Step.person => _Step.timetable,
        _Step.confirm => _Step.person,
        _ => _step,
      };
    });
  }

  // ---- booking ------------------------------------------------------------

  Future<void> _submit() async {
    final l10n = AppLocalizations.of(context);
    final slot = _slot;
    final facility = _facility;
    final category = _category;
    if (slot == null || facility == null || category == null) return;
    setState(() {
      _submitting = true;
      _submitError = null;
    });
    try {
      await _api.createBookingAppointment(buildBookingBody(
        facilityName: facility.facilityName,
        category: category.code,
        scheduledAt: slot.start,
        profileId: _forSelf ? null : _person?.id,
        reason: _reasonController.text,
      ));
      if (!mounted) return;
      setState(() {
        _step = _Step.done;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 409) {
        context.snack(l10n.bkSlotTaken);
        final date = _date;
        setState(() {
          _slot = null;
          _step = _Step.timetable;
        });
        await _loadAvailability(preferDate: date);
      } else if (e.statusCode == 403) {
        setState(() => _submitError = l10n.bkNoPatientRecord);
      } else {
        setState(() => _submitError = _message(e));
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _submitError = _message(e));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _openAppointments() async {
    final reminders = context.read<RemindersProvider>();
    final api = _api;
    final patientId = context.read<PatientProvider>().patient?.id;
    final navigator = Navigator.of(context);
    if (patientId != null) await reminders.syncServerAppointments(patientId, api);
    if (!mounted) return;
    navigator.pushReplacement(MaterialPageRoute<void>(builder: (_) => const RemindersScreen()));
  }

  Future<void> _launchMySejahtera() async {
    final l10n = AppLocalizations.of(context);
    final ok = await widget.openMySejahtera();
    if (!mounted || ok) return;
    context.snack(l10n.mySejahteraLaunchFailed);
  }

  // ---- profiles -----------------------------------------------------------

  Future<void> _editProfile([BookingProfile? existing]) async {
    final api = _api;
    final saved = await showDialog<BookingProfile>(
      context: context,
      builder: (_) => _ProfileDialog(
        initial: existing,
        save: (body) =>
            existing == null ? api.createBookingProfile(body) : api.updateBookingProfile(existing.id, body),
      ),
    );
    if (saved == null || !mounted) return;
    setState(() {
      final list = [...?_profiles];
      final i = list.indexWhere((p) => p.id == saved.id);
      if (i >= 0) {
        list[i] = saved;
      } else {
        list.add(saved);
      }
      _profiles = list;
      if (_person?.id == saved.id) _person = saved;
    });
  }

  Future<void> _deleteProfile(BookingProfile p) async {
    final l10n = AppLocalizations.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(l10n.bkDeletePersonTitle),
        content: Text(l10n.bkDeletePersonBody(p.fullName)),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: Text(l10n.cancel)),
          FilledButton(onPressed: () => Navigator.of(ctx).pop(true), child: Text(l10n.bkDelete)),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await _api.deleteBookingProfile(p.id);
      if (!mounted) return;
      setState(() {
        _profiles = _profiles?.where((x) => x.id != p.id).toList();
        if (_person?.id == p.id) {
          _person = null;
          _forSelf = true;
        }
      });
    } catch (e) {
      if (!mounted) return;
      context.snack(_message(e));
    }
  }

  // ---- build --------------------------------------------------------------

  String _titleFor(AppLocalizations l10n) => switch (_step) {
        _Step.category => l10n.bkChooseCategory,
        _Step.location => l10n.bkChooseHospital,
        _Step.timetable => l10n.bkChooseTime,
        _Step.person => l10n.bkChoosePerson,
        _Step.confirm => l10n.bkConfirmTitle,
        _Step.done => l10n.bkSuccessTitle,
      };

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final Widget body = switch (_step) {
      _Step.category => _buildCategories(l10n),
      _Step.location => _buildLocation(l10n),
      _Step.timetable => _buildTimetable(l10n),
      _Step.person => _buildPerson(l10n),
      _Step.confirm => _buildConfirm(l10n),
      _Step.done => _buildDone(l10n),
    };
    return PopScope(
      canPop: _step == _Step.category || _step == _Step.done,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _back();
      },
      child: Scaffold(
        appBar: AppBar(title: Text(_titleFor(l10n))),
        body: Column(
          children: [
            if (_bannerVisible && _step != _Step.done) _buildBanner(l10n),
            Expanded(child: body),
          ],
        ),
      ),
    );
  }

  Widget _buildBanner(AppLocalizations l10n) {
    final p = context.palette;
    return MaterialBanner(
      backgroundColor: p.chipBg,
      leading: Icon(Icons.info_outline, color: p.primary),
      forceActionsBelow: true,
      content: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l10n.bkBannerTitle, style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary)),
          const SizedBox(height: 2),
          Text(l10n.bkBannerNote, style: TextStyle(fontSize: 13, color: p.textBody)),
        ],
      ),
      actions: [
        TextButton(onPressed: _launchMySejahtera, child: Text(l10n.bkOpenMySejahtera)),
        TextButton(onPressed: () => setState(() => _bannerVisible = false), child: Text(l10n.bkBookHere)),
      ],
    );
  }

  Widget _buildCategories(AppLocalizations l10n) {
    if (_loadingCategories) return const LoadingView();
    if (_categoriesError != null) {
      return ErrorRetryView(message: _categoriesError!, onRetry: _loadCategories);
    }
    final categories = _categories ?? const <BookingCategory>[];
    if (categories.isEmpty) {
      return Center(
        child: Padding(padding: const EdgeInsets.all(24), child: EmptyText(l10n.bkCategoriesEmpty)),
      );
    }
    final p = context.palette;
    return GridView.builder(
      padding: const EdgeInsets.all(16),
      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 220,
        mainAxisExtent: 128,
        crossAxisSpacing: 12,
        mainAxisSpacing: 12,
      ),
      itemCount: categories.length,
      itemBuilder: (context, i) {
        final c = categories[i];
        final label = bookingCategoryLabel(l10n, c.code, c.label);
        return Semantics(
          button: true,
          label: label,
          excludeSemantics: true,
          child: Material(
            color: p.surface,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(color: p.border),
            ),
            child: InkWell(
              key: Key('cat-${c.code}'),
              borderRadius: BorderRadius.circular(12),
              onTap: () => _pickCategory(c),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(bookingCategoryIcon(c.code), size: 32, color: p.primary),
                    const SizedBox(height: 8),
                    Flexible(
                      child: Text(
                        label,
                        textAlign: TextAlign.center,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14, color: p.textPrimary),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildLocation(AppLocalizations l10n) {
    final p = context.palette;
    final facilities = _facilities;
    Widget results;
    if (_loadingFacilities) {
      results = const LoadingView();
    } else if (_facilitiesError != null) {
      results = ErrorRetryView(message: _facilitiesError!, onRetry: _searchFacilities);
    } else if (facilities == null || facilities.isEmpty) {
      results = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(l10n.bkFacilitiesEmpty, textAlign: TextAlign.center, style: TextStyle(color: p.textMuted)),
        ),
      );
    } else {
      results = ListView.separated(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
        itemCount: facilities.length,
        separatorBuilder: (_, _) => const SizedBox(height: 10),
        itemBuilder: (context, i) => _facilityCard(l10n, facilities[i]),
      );
    }

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                bookingCategoryLabel(l10n, _category?.code ?? '', _category?.label),
                style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary),
              ),
              const SizedBox(height: 8),
              TextField(
                key: const Key('facility-search'),
                controller: _searchController,
                textInputAction: TextInputAction.search,
                onSubmitted: (_) => _searchFacilities(),
                decoration: InputDecoration(
                  hintText: l10n.bkSearchHint,
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: IconButton(
                    tooltip: l10n.bkSearchAction,
                    icon: const Icon(Icons.arrow_forward),
                    onPressed: _searchFacilities,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      key: const Key('use-location'),
                      onPressed: _locating ? null : _useMyLocation,
                      icon: _locating
                          ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.my_location),
                      label: Text(l10n.bkUseMyLocation),
                    ),
                  ),
                  if (_fix != null) ...[
                    const SizedBox(width: 8),
                    TextButton(
                      onPressed: () {
                        setState(() => _fix = null);
                        _searchFacilities();
                      },
                      child: Text(l10n.bkClearLocation),
                    ),
                  ],
                ],
              ),
              if (_fix != null) ...[
                const SizedBox(height: 6),
                Text(l10n.bkSortedNearest, style: TextStyle(fontSize: 12, color: p.textMuted)),
              ],
              if (_locationMessage != null) ...[
                const SizedBox(height: 6),
                Text(
                  _locationMessage!,
                  key: const Key('location-message'),
                  style: TextStyle(fontSize: 13, color: p.attention),
                ),
              ],
            ],
          ),
        ),
        Expanded(child: results),
      ],
    );
  }

  Widget _facilityCard(AppLocalizations l10n, BookingFacility f) {
    final p = context.palette;
    final distance = distanceKmLabel(f.distanceKm);
    final next = f.nextAvailableAt;
    final nextText = next == null
        ? l10n.bkNoNextAvailable
        : l10n.bkNextAvailable(DateFormat('EEE d MMM, h:mm a').format(wallClock(next)));
    return Material(
      color: p.surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: p.border)),
      child: InkWell(
        key: Key('facility-${f.facilityName}'),
        borderRadius: BorderRadius.circular(12),
        onTap: () => _pickFacility(f),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Icon(Icons.local_hospital_outlined, color: p.primary),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      f.displayName,
                      style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15, color: p.textPrimary),
                    ),
                    if (f.address != null && f.address!.trim().isNotEmpty)
                      Text(f.address!, style: TextStyle(fontSize: 13, color: p.textMuted)),
                    const SizedBox(height: 4),
                    Text(
                      distance == null ? nextText : '${l10n.bkDistanceKm(distance)}  |  $nextText',
                      style: TextStyle(fontSize: 13, color: p.success, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: p.textMuted),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildTimetable(AppLocalizations l10n) {
    final p = context.palette;
    if (_loadingAvailability && _availability == null) return const LoadingView();
    if (_availabilityError != null) {
      return ErrorRetryView(message: _availabilityError!, onRetry: _loadAvailability);
    }
    final availability = _availability;
    if (availability == null) return const LoadingView();
    final hasOpenDay = firstOpenDay(availability.days) != null;
    final fmtDay = DateFormat('d');
    final fmtWeek = DateFormat('EEE');
    final fmtMonth = DateFormat('MMM');
    final fmtSemantic = DateFormat('EEE d MMM');

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text(_facility?.displayName ?? '', style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary)),
        const SizedBox(height: 14),
        Text(l10n.bkDateLabel, style: TextStyle(fontWeight: FontWeight.w600, color: p.textPrimary)),
        const SizedBox(height: 8),
        if (!hasOpenDay)
          Text(l10n.bkNoOpenDays, style: TextStyle(color: p.textMuted))
        else
          SizedBox(
            height: 88,
            child: ListView.separated(
              key: const Key('date-strip'),
              scrollDirection: Axis.horizontal,
              itemCount: availability.days.length,
              separatorBuilder: (_, _) => const SizedBox(width: 8),
              itemBuilder: (context, i) {
                final d = availability.days[i];
                final open = d.openSlots > 0;
                final selected = d.date == _date;
                final day = d.day;
                final fg = selected ? context.onFill : (open ? p.textPrimary : p.textFaint);
                return Semantics(
                  button: true,
                  enabled: open,
                  selected: selected,
                  label: open
                      ? l10n.bkDayOpenSemantics(fmtSemantic.format(day), d.openSlots)
                      : l10n.bkDayFullSemantics(fmtSemantic.format(day)),
                  excludeSemantics: true,
                  child: Material(
                    color: selected ? p.primary : (open ? p.surface : p.background),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                      side: BorderSide(color: selected ? p.primary : p.border),
                    ),
                    child: InkWell(
                      key: Key('day-${d.date}'),
                      borderRadius: BorderRadius.circular(12),
                      onTap: open ? () => _selectDate(d.date) : null,
                      child: SizedBox(
                        width: 64,
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Text(fmtWeek.format(day), style: TextStyle(fontSize: 12, color: fg)),
                            Text(
                              fmtDay.format(day),
                              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: fg),
                            ),
                            Text(fmtMonth.format(day), style: TextStyle(fontSize: 12, color: fg)),
                          ],
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        const SizedBox(height: 20),
        if (hasOpenDay) ...[
          Text(l10n.bkTimeLabel, style: TextStyle(fontWeight: FontWeight.w600, color: p.textPrimary)),
          const SizedBox(height: 8),
          _buildSlots(l10n),
        ],
        const SizedBox(height: 24),
        FilledButton(
          key: const Key('timetable-continue'),
          onPressed: _slot == null ? null : _toPerson,
          child: Text(l10n.bkContinue),
        ),
      ],
    );
  }

  Widget _buildSlots(AppLocalizations l10n) {
    final p = context.palette;
    if (_loadingSlots) {
      return const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: LoadingView());
    }
    if (_slotsError != null) {
      final date = _date;
      return ErrorRetryView(message: _slotsError!, onRetry: date == null ? null : () => _selectDate(date));
    }
    final slots = _slots;
    if (slots == null) return const SizedBox.shrink();
    if (slots.isEmpty) {
      return Text(l10n.bkNoSlots, style: TextStyle(color: p.textMuted));
    }
    final fmt = DateFormat('h:mm a');
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: slots.map((s) {
        final selected = identical(s, _slot) || (_slot != null && _slot!.start == s.start);
        final time = fmt.format(s.startWall);
        final label = s.isFull ? '$time  |  ${l10n.bkSlotFull}' : '$time  |  ${l10n.bkSlotsLeft(s.remaining)}';
        return ChoiceChip(
          key: Key('slot-${s.start}'),
          label: Text(label),
          selected: selected,
          showCheckmark: false,
          selectedColor: p.primary,
          labelStyle: TextStyle(
            color: selected ? context.onFill : (s.isFull ? p.textFaint : p.textPrimary),
            fontWeight: FontWeight.w600,
          ),
          materialTapTargetSize: MaterialTapTargetSize.padded,
          onSelected: s.isFull ? null : (_) => setState(() => _slot = s),
        );
      }).toList(),
    );
  }

  Widget _buildPerson(AppLocalizations l10n) {
    final p = context.palette;
    final myName = context.read<PatientProvider>().patient?.fullName;
    final profiles = _profiles;

    Widget saved;
    if (_loadingProfiles) {
      saved = const Padding(padding: EdgeInsets.all(24), child: LoadingView());
    } else if (_profilesError != null) {
      saved = ErrorRetryView(message: _profilesError!, onRetry: _loadProfiles);
    } else if (profiles == null || profiles.isEmpty) {
      saved = Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Text(l10n.bkNoPeople, style: TextStyle(color: p.textMuted)),
      );
    } else {
      saved = Column(
        children: [
          for (final pr in profiles)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _PersonTile(
                key: Key('person-${pr.id}'),
                title: pr.fullName,
                subtitle: bookingRelationshipLabel(l10n, pr.relationship),
                selected: !_forSelf && _person?.id == pr.id,
                onTap: () => setState(() {
                  _forSelf = false;
                  _person = pr;
                }),
                onEdit: () => _editProfile(pr),
                onDelete: () => _deleteProfile(pr),
                editLabel: l10n.bkEditPerson,
                deleteLabel: l10n.bkDelete,
              ),
            ),
        ],
      );
    }

    final canContinue = _forSelf || _person != null;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _PersonTile(
          key: const Key('person-self'),
          title: l10n.bkMyself,
          subtitle: myName != null && myName.isNotEmpty ? myName : l10n.bkMyselfNote,
          selected: _forSelf,
          onTap: () => setState(() {
            _forSelf = true;
            _person = null;
          }),
        ),
        const SizedBox(height: 20),
        Text(l10n.bkSavedPeople, style: TextStyle(fontWeight: FontWeight.w600, color: p.textPrimary)),
        const SizedBox(height: 8),
        saved,
        const SizedBox(height: 4),
        OutlinedButton.icon(
          key: const Key('add-person'),
          onPressed: () => _editProfile(),
          icon: const Icon(Icons.person_add_alt_1_outlined),
          label: Text(l10n.bkAddPerson),
        ),
        const SizedBox(height: 24),
        FilledButton(
          key: const Key('person-continue'),
          onPressed: canContinue ? () => setState(() => _step = _Step.confirm) : null,
          child: Text(l10n.bkContinue),
        ),
      ],
    );
  }

  Widget _summaryCard(AppLocalizations l10n) {
    final p = context.palette;
    final slot = _slot;
    final when = slot == null
        ? ''
        : DateFormat('EEE d MMM yyyy, h:mm a').format(slot.startWall);
    final myName = context.read<PatientProvider>().patient?.fullName;
    final who = _forSelf
        ? (myName != null && myName.isNotEmpty ? '${l10n.bkMyself} ($myName)' : l10n.bkMyself)
        : bookingPersonLabel(l10n, _person?.fullName ?? '', _person?.relationship);

    Widget row(String label, String value) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 110,
                child: Text(label, style: TextStyle(fontSize: 13, color: p.textMuted)),
              ),
              Expanded(
                child: Text(
                  value,
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: p.textPrimary),
                ),
              ),
            ],
          ),
        );

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: [
            row(l10n.bkSummaryCategory, bookingCategoryLabel(l10n, _category?.code ?? '', _category?.label)),
            row(l10n.bkSummaryHospital, _facility?.displayName ?? ''),
            row(l10n.bkSummaryWhen, when),
            row(l10n.bkSummaryPerson, who),
          ],
        ),
      ),
    );
  }

  Widget _buildConfirm(AppLocalizations l10n) {
    final p = context.palette;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _summaryCard(l10n),
        const SizedBox(height: 16),
        TextField(
          key: const Key('reason'),
          controller: _reasonController,
          enabled: !_submitting,
          maxLength: 200,
          maxLines: 2,
          decoration: InputDecoration(labelText: l10n.bkReasonLabel),
        ),
        if (_submitError != null) ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: p.emergencyBg, borderRadius: BorderRadius.circular(10)),
            child: Text(
              _submitError!,
              key: const Key('submit-error'),
              style: TextStyle(color: p.emergency, fontWeight: FontWeight.w600),
            ),
          ),
        ],
        const SizedBox(height: 16),
        FilledButton(
          key: const Key('confirm-booking'),
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const ButtonSpinner()
              : Text(_submitError != null ? l10n.bkTryAgain : l10n.bkConfirmButton),
        ),
      ],
    );
  }

  Widget _buildDone(AppLocalizations l10n) {
    final p = context.palette;
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        const SizedBox(height: 16),
        Icon(Icons.check_circle_outline, size: 72, color: p.success),
        const SizedBox(height: 12),
        Text(
          l10n.bkSuccessTitle,
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: p.textPrimary),
        ),
        const SizedBox(height: 6),
        Text(
          l10n.bkSuccessBody,
          textAlign: TextAlign.center,
          style: TextStyle(color: p.textMuted),
        ),
        const SizedBox(height: 20),
        _summaryCard(l10n),
        const SizedBox(height: 20),
        FilledButton.icon(
          key: const Key('view-appointments'),
          onPressed: _openAppointments,
          icon: const Icon(Icons.event_available_outlined),
          label: Text(l10n.bkViewAppointments),
        ),
        const SizedBox(height: 10),
        OutlinedButton(onPressed: () => Navigator.of(context).maybePop(), child: Text(l10n.bkDone)),
      ],
    );
  }
}

class _PersonTile extends StatelessWidget {
  const _PersonTile({
    super.key,
    required this.title,
    required this.subtitle,
    required this.selected,
    required this.onTap,
    this.onEdit,
    this.onDelete,
    this.editLabel,
    this.deleteLabel,
  });

  final String title;
  final String subtitle;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onEdit;
  final VoidCallback? onDelete;
  final String? editLabel;
  final String? deleteLabel;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      button: true,
      selected: selected,
      inMutuallyExclusiveGroup: true,
      label: '$title, $subtitle',
      excludeSemantics: true,
      onTap: onTap,
      child: Material(
        color: selected ? p.chipBg : p.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: selected ? p.primary : p.border, width: selected ? 2 : 1),
        ),
        child: Row(
          children: [
            Expanded(
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: onTap,
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    children: [
                      Icon(
                        selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                        color: selected ? p.primary : p.textMuted,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              title,
                              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15, color: p.textPrimary),
                            ),
                            Text(subtitle, style: TextStyle(fontSize: 13, color: p.textMuted)),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (onEdit != null)
              IconButton(
                tooltip: editLabel,
                constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: Icon(Icons.edit_outlined, color: p.primary),
                onPressed: onEdit,
              ),
            if (onDelete != null)
              IconButton(
                tooltip: deleteLabel,
                constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
                icon: Icon(Icons.delete_outline, color: p.emergency),
                onPressed: onDelete,
              ),
          ],
        ),
      ),
    );
  }
}

/// Add/edit one saved person. Pops with the saved [BookingProfile]; server
/// errors stay inline so the typed values are not lost.
class _ProfileDialog extends StatefulWidget {
  const _ProfileDialog({this.initial, required this.save});

  final BookingProfile? initial;
  final Future<BookingProfile> Function(Map<String, dynamic> body) save;

  @override
  State<_ProfileDialog> createState() => _ProfileDialogState();
}

class _ProfileDialogState extends State<_ProfileDialog> {
  late final TextEditingController _name = TextEditingController(text: widget.initial?.fullName ?? '');
  final _nric = TextEditingController();
  late String _relationship = widget.initial?.relationship ?? 'child';
  late DateTime? _dob = DateTime.tryParse(widget.initial?.dateOfBirth ?? '');
  bool _touched = false;
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _nric.dispose();
    super.dispose();
  }

  Future<void> _pickDob() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _dob ?? DateTime(now.year - 10, now.month, now.day),
      firstDate: DateTime(1900),
      lastDate: now,
    );
    if (picked != null) setState(() => _dob = picked);
  }

  Future<void> _submit() async {
    setState(() => _touched = true);
    if (_name.text.trim().isEmpty || _dob == null) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final nric = _nric.text.trim();
    try {
      final saved = await widget.save({
        'full_name': _name.text.trim(),
        'relationship': _relationship,
        'date_of_birth': DateFormat('yyyy-MM-dd').format(_dob!),
        if (nric.isNotEmpty) 'national_id': nric,
      });
      if (!mounted) return;
      Navigator.of(context).pop(saved);
    } catch (e) {
      if (!mounted) return;
      final l10n = AppLocalizations.of(context);
      setState(() {
        _saving = false;
        _error = e is ApiException ? (e.isUnreachable ? l10n.bkNetworkError : e.message) : l10n.bookAppointmentGenericError;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    return AlertDialog(
      title: Text(widget.initial == null ? l10n.bkAddPerson : l10n.bkEditPerson),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              key: const Key('profile-name'),
              controller: _name,
              enabled: !_saving,
              textCapitalization: TextCapitalization.words,
              decoration: InputDecoration(
                labelText: l10n.bkFullName,
                errorText: _touched && _name.text.trim().isEmpty ? l10n.bkNameRequired : null,
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _relationship,
              decoration: InputDecoration(labelText: l10n.bkRelationship),
              items: [
                for (final r in bookingRelationships)
                  DropdownMenuItem(value: r, child: Text(bookingRelationshipLabel(l10n, r))),
              ],
              onChanged: _saving ? null : (v) => setState(() => _relationship = v ?? _relationship),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              key: const Key('profile-dob'),
              onPressed: _saving ? null : _pickDob,
              icon: const Icon(Icons.cake_outlined),
              label: Text(_dob == null ? l10n.bkPickDob : DateFormat('d MMM yyyy').format(_dob!)),
            ),
            if (_touched && _dob == null)
              Padding(
                padding: const EdgeInsets.only(top: 4, left: 4),
                child: Text(l10n.bkDobRequired, style: TextStyle(fontSize: 12, color: p.emergency)),
              ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('profile-nric'),
              controller: _nric,
              enabled: !_saving,
              decoration: InputDecoration(labelText: l10n.bkNric),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: TextStyle(color: p.emergency, fontSize: 13)),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: _saving ? null : () => Navigator.of(context).pop(), child: Text(l10n.cancel)),
        FilledButton(
          key: const Key('profile-save'),
          onPressed: _saving ? null : _submit,
          child: _saving ? const ButtonSpinner() : Text(l10n.save),
        ),
      ],
    );
  }
}
