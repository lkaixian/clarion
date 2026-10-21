import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/scan_location_entry.dart';
import '../providers/auth_provider.dart';
import '../services/api_client.dart';
import '../services/map_launcher.dart';
import '../theme/app_theme.dart';
import '../widgets/record_widgets.dart' show joinNonEmpty;
import '../widgets/loading_view.dart';
import '../widgets/scan_result_view.dart' show scanTierLabel;

/// "Where my card was scanned": positions reported by the phones of people who
/// scanned the acting patient's card, newest first. Tap a row to open the map.
class CardScanLocationsScreen extends StatefulWidget {
  const CardScanLocationsScreen({super.key, this.open});

  /// Replaces the real launcher in tests.
  final UrlOpener? open;

  @override
  State<CardScanLocationsScreen> createState() => _CardScanLocationsScreenState();
}

class _CardScanLocationsScreenState extends State<CardScanLocationsScreen> {
  List<ScanLocationEntry>? _items;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    final id = context.read<AuthProvider>().user?.patientId;
    if (id == null) {
      setState(() => _items = const []);
      return;
    }
    setState(() => _error = false);
    try {
      final items = await api.getScanLocations(id);
      if (mounted) setState(() => _items = items);
    } catch (_) {
      if (mounted) setState(() => _error = true);
    }
  }

  String _who(AppLocalizations l10n, ScanLocationEntry e) {
    final tier = e.tier == null || e.tier == 'public' ? null : scanTierLabel(l10n, e.tier);
    return joinNonEmpty([tier ?? l10n.scanWhoAnonymous, e.actorFacility], ' · ');
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    final items = _items;
    final locale = Localizations.localeOf(context).toString();
    final Widget body;
    if (items == null) {
      body = _error ? ErrorRetryView(message: l10n.cardScanLocationsError, onRetry: _load) : const LoadingView();
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(l10n.cardScanLocationsNote, style: TextStyle(fontSize: 14, color: p.textBody, height: 1.3)),
            const SizedBox(height: 12),
            if (items.isEmpty) Text(l10n.cardScanLocationsEmpty, style: TextStyle(fontSize: 16, color: p.textBody)),
            for (final e in items)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  key: Key('scan-location-${items.indexOf(e)}'),
                  minTileHeight: 56,
                  leading: Icon(Icons.place_outlined, color: p.primary),
                  title: Text(
                    e.createdAt == null ? '' : DateFormat('d MMM yyyy, h:mm a', locale).format(e.createdAt!),
                    style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary),
                  ),
                  subtitle: Text(
                    joinNonEmpty([_who(l10n, e), e.accuracyM == null ? null : l10n.cardScanLocationsAccuracy(e.accuracyM!)], '\n'),
                    style: TextStyle(color: p.textBody),
                  ),
                  trailing: Tooltip(message: l10n.openInMaps, child: Icon(Icons.map_outlined, color: p.primary)),
                  onTap: () => openMapOrSnack(context, e.lat, e.lng, open: widget.open),
                ),
              ),
          ],
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: Text(l10n.cardScanLocationsTitle)), body: body);
  }
}
