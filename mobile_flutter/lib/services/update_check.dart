import 'package:package_info_plus/package_info_plus.dart';

import '../config/app_config.dart';
import 'api_client.dart';

/// Result of comparing this build against `GET /app/version`.
class UpdateInfo {
  const UpdateInfo({
    required this.latest,
    required this.required,
    required this.downloadUrl,
  });

  final String latest;

  /// Running build is below the server's `min_supported` -- block, don't nag.
  final bool required;
  final Uri downloadUrl;
}

/// Compares dotted versions numerically ("1.10.0" > "1.9.0"). Non-numeric
/// parts count as 0; a build suffix ("+5") is ignored.
int compareVersions(String a, String b) {
  List<int> parts(String v) => v
      .split('+')
      .first
      .split('.')
      .map((p) => int.tryParse(p.trim()) ?? 0)
      .toList();
  final x = parts(a), y = parts(b);
  for (var i = 0; i < (x.length > y.length ? x.length : y.length); i++) {
    final d = (i < x.length ? x[i] : 0) - (i < y.length ? y[i] : 0);
    if (d != 0) return d;
  }
  return 0;
}

/// Returns update details when a newer build exists, else null. Never throws:
/// an offline launch or API outage must not get in the user's way.
Future<UpdateInfo?> checkForUpdate(ApiClient api, AppConfig config) async {
  try {
    final current = (await PackageInfo.fromPlatform()).version;
    final data = await api.getAppVersion();
    final latest = (data['latest'] as String?) ?? '';
    final min = (data['min_supported'] as String?) ?? '';
    final isRequired = min.isNotEmpty && compareVersions(current, min) < 0;
    if (!isRequired && (latest.isEmpty || compareVersions(current, latest) >= 0)) {
      return null;
    }
    final raw = (data['download_url'] as String?) ?? '/get-app';
    final origin = Uri.parse(config.baseUrl);
    final target = Uri.parse(raw);
    return UpdateInfo(
      latest: latest,
      required: isRequired,
      downloadUrl: target.hasScheme
          ? target
          : origin.replace(path: raw, query: '', fragment: ''),
    );
  } catch (_) {
    return null;
  }
}
