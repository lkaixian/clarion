import 'audit_log_entry.dart' show parseServerTime;

/// One item of `GET /notifications`.
class AppNotification {
  const AppNotification({
    required this.id,
    required this.title,
    this.body,
    this.link,
    this.urgent = false,
    this.createdAt,
    this.read = false,
  });

  final String id;
  final String title;
  final String? body;
  final String? link;
  final bool urgent;
  final DateTime? createdAt;
  final bool read;

  /// An absolute https link (e.g. a maps URL for a card scan) opens outside
  /// the app; anything else is an in-app route this app does not handle.
  bool get isExternalLink => link != null && link!.startsWith('https://');

  factory AppNotification.fromJson(Map<String, dynamic> j) => AppNotification(
        id: j['id'] as String? ?? '',
        title: j['title'] as String? ?? '',
        body: j['body'] as String?,
        link: j['link'] as String?,
        urgent: j['urgent'] as bool? ?? false,
        createdAt: parseServerTime(j['created_at'] as String? ?? ''),
        read: j['read_at'] != null,
      );
}
