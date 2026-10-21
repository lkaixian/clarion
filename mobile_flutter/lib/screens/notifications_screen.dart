import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../models/app_notification.dart';
import '../services/api_client.dart';
import '../services/map_launcher.dart';
import '../theme/app_theme.dart';
import '../widgets/loading_view.dart';

/// The signed-in user's inbox (`GET /notifications`). A notification whose link
/// is an https URL (a card scan's position) shows a pin and "Open in Maps" and
/// opens outside the app; other links are in-app routes this app does not follow.
class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key, this.open});

  /// Replaces the real launcher in tests.
  final UrlOpener? open;

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  List<AppNotification>? _items;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  Future<void> _load() async {
    final api = context.read<ApiClient>();
    setState(() => _error = false);
    try {
      final items = await api.getNotifications();
      if (mounted) setState(() => _items = items);
    } catch (_) {
      if (mounted) setState(() => _error = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final items = _items;
    final Widget body;
    if (items == null) {
      body = _error ? ErrorRetryView(message: l10n.notificationsLoadError, onRetry: _load) : const LoadingView();
    } else if (items.isEmpty) {
      body = Center(child: Text(l10n.notificationsEmpty, style: TextStyle(color: context.palette.textBody)));
    } else {
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView.separated(
          padding: const EdgeInsets.all(16),
          itemCount: items.length,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (_, i) => _NotificationTile(item: items[i], open: widget.open),
        ),
      );
    }
    return Scaffold(appBar: AppBar(title: Text(l10n.notificationsTitle)), body: body);
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.item, this.open});
  final AppNotification item;
  final UrlOpener? open;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final p = context.palette;
    final at = item.createdAt;
    final when = at == null ? '' : DateFormat('d MMM yyyy, h:mm a', Localizations.localeOf(context).toString()).format(at);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (item.urgent) ...[
                  Icon(Icons.priority_high, size: 20, color: p.emergency),
                  const SizedBox(width: 4),
                ],
                Expanded(
                  child: Text(
                    item.title,
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: item.read ? FontWeight.w500 : FontWeight.w800,
                      color: p.textPrimary,
                    ),
                  ),
                ),
              ],
            ),
            if (item.body != null && item.body!.trim().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(item.body!, style: TextStyle(fontSize: 14, color: p.textBody, height: 1.3)),
              ),
            if (when.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(when, style: TextStyle(fontSize: 13, color: p.textMuted)),
              ),
            if (item.isExternalLink)
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: TextButton.icon(
                  key: Key('open-maps-${item.id}'),
                  style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
                  onPressed: () => openExternalLinkOrSnack(context, item.link!, open: open),
                  icon: const Icon(Icons.place_outlined),
                  label: Text(l10n.openInMaps),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
