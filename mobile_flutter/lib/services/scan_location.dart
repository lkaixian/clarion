import 'package:geolocator/geolocator.dart';

/// A position the scanner's phone reports with a scan.
class ScanFix {
  const ScanFix(this.lat, this.lng, this.at, {this.accuracyM});
  final double lat;
  final double lng;
  final DateTime at;
  final double? accuracyM;

  /// The server rejects non-finite, out-of-range and (0,0) positions with a 422,
  /// which would fail the whole scan, so anything doubtful is never sent.
  bool get isValid =>
      lat.isFinite && lng.isFinite && lat.abs() <= 90 && lng.abs() <= 180 && !(lat == 0 && lng == 0);

  bool isYoungerThan(Duration d, [DateTime? now]) => (now ?? DateTime.now()).difference(at) < d;

  Map<String, dynamic> toJson() => {
        'lat': lat,
        'lng': lng,
        if (accuracyM != null && accuracyM!.isFinite && accuracyM! >= 0) 'accuracy_m': accuracyM,
      };
}

enum LocPermission { granted, denied, deniedForever, serviceOff }

/// What the scanner screen needs from the phone's location stack, so tests
/// never touch geolocator. Implementations must not throw.
abstract class ScanLocationSource {
  /// Current permission / service state, without prompting.
  Future<LocPermission> checkPermission();

  /// Prompts the user if the permission is still undecided.
  Future<LocPermission> requestPermission();

  /// The OS's cached position, instantly (null when there is none).
  Future<ScanFix?> lastKnown();

  /// A fresh position (~8 s at most; null on timeout or any failure).
  Future<ScanFix?> current();
}

class GeolocatorScanLocationSource implements ScanLocationSource {
  const GeolocatorScanLocationSource();

  static ScanFix _fix(Position p) => ScanFix(p.latitude, p.longitude, p.timestamp, accuracyM: p.accuracy);

  static LocPermission _map(LocationPermission p) => switch (p) {
        LocationPermission.always || LocationPermission.whileInUse => LocPermission.granted,
        LocationPermission.deniedForever => LocPermission.deniedForever,
        _ => LocPermission.denied,
      };

  @override
  Future<LocPermission> checkPermission() async {
    try {
      final p = _map(await Geolocator.checkPermission());
      if (p == LocPermission.granted && !await Geolocator.isLocationServiceEnabled()) {
        return LocPermission.serviceOff;
      }
      return p;
    } catch (_) {
      return LocPermission.serviceOff;
    }
  }

  @override
  Future<LocPermission> requestPermission() async {
    try {
      if (await Geolocator.checkPermission() == LocationPermission.denied) {
        await Geolocator.requestPermission();
      }
    } catch (_) {}
    return checkPermission();
  }

  @override
  Future<ScanFix?> lastKnown() async {
    try {
      final p = await Geolocator.getLastKnownPosition();
      return p == null ? null : _fix(p);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<ScanFix?> current() async {
    try {
      final p = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 8),
        ),
      );
      return _fix(p);
    } catch (_) {
      return null;
    }
  }
}
