import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config/app_config.dart';
import '../services/api_client.dart';
import '../services/update_check.dart';

/// Checks `GET /app/version` once per launch and, when a newer build exists,
/// shows a dismissible banner above the app (or a blocking one when this
/// build is below the server's `min_supported`). Silent on any failure.
class UpdateBanner extends StatefulWidget {
  const UpdateBanner({
    super.key,
    required this.api,
    required this.config,
    required this.child,
  });

  final ApiClient api;
  final AppConfig config;
  final Widget child;

  @override
  State<UpdateBanner> createState() => _UpdateBannerState();
}

class _UpdateBannerState extends State<UpdateBanner> {
  UpdateInfo? _info;
  bool _dismissed = false;

  @override
  void initState() {
    super.initState();
    checkForUpdate(widget.api, widget.config).then((info) {
      if (mounted) setState(() => _info = info);
    });
  }

  Future<void> _open(UpdateInfo info) =>
      launchUrl(info.downloadUrl, mode: LaunchMode.externalApplication);

  @override
  Widget build(BuildContext context) {
    final info = _info;
    if (info == null) return widget.child;

    if (info.required) {
      return Stack(children: [
        widget.child,
        Positioned.fill(
          child: ColoredBox(
            color: Colors.black54,
            child: Center(
              child: Card(
                margin: const EdgeInsets.all(24),
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const Icon(Icons.system_update, size: 40),
                    const SizedBox(height: 12),
                    Text('Update required',
                        style: Theme.of(context).textTheme.titleLarge),
                    const SizedBox(height: 8),
                    Text('This version is no longer supported. '
                        'Install CLARION ${info.latest} to continue.',
                        textAlign: TextAlign.center),
                    const SizedBox(height: 16),
                    FilledButton(
                      onPressed: () => _open(info),
                      child: const Text('Download update'),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        ),
      ]);
    }

    if (_dismissed) return widget.child;
    return Column(children: [
      Material(
        color: Theme.of(context).colorScheme.primaryContainer,
        child: SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(children: [
              const Icon(Icons.system_update, size: 20),
              const SizedBox(width: 8),
              Expanded(child: Text('CLARION ${info.latest} is available')),
              TextButton(onPressed: () => _open(info), child: const Text('Update')),
              IconButton(
                tooltip: 'Dismiss',
                icon: const Icon(Icons.close, size: 18),
                onPressed: () => setState(() => _dismissed = true),
              ),
            ]),
          ),
        ),
      ),
      Expanded(child: MediaQuery.removePadding(context: context, removeTop: true, child: widget.child)),
    ]);
  }
}
