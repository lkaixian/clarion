/// A purely local (device-only) appointment reminder. The backend has no
/// appointments concept in this MVP — real bookings happen externally
/// (e.g. via MySejahtera, see the "Book via MySejahtera" button on the
/// Reminders screen); this just lets the patient set a local notification
/// for a date/time they already booked elsewhere.
class AppointmentReminder {
  final String id;
  final String title;
  final DateTime dateTime;

  const AppointmentReminder({required this.id, required this.title, required this.dateTime});

  factory AppointmentReminder.fromJson(Map<String, dynamic> json) => AppointmentReminder(
        id: json['id'] as String,
        title: json['title'] as String,
        dateTime: DateTime.parse(json['dateTime'] as String),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'dateTime': dateTime.toIso8601String(),
      };
}
