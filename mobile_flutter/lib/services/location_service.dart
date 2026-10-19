import 'package:geolocator/geolocator.dart';

/// Why the phone's position could not be read. The booking screen maps each
/// to a plain message and always leaves typed search available.
enum LocationFailure { denied, deniedForever, serviceOff, unavailable }

class LocationException implements Exception {
  const LocationException(this.failure);
  final LocationFailure failure;
}

class LocationFix {
  const LocationFix(this.latitude, this.longitude);
  final double latitude;
  final double longitude;
}

/// Reads the current position once. Throws [LocationException] on any
/// failure. Coarse accuracy is enough to sort hospitals by distance.
typedef LocateFn = Future<LocationFix> Function();

Future<LocationFix> locateWithGeolocator() async {
  try {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const LocationException(LocationFailure.serviceOff);
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.deniedForever) {
      throw const LocationException(LocationFailure.deniedForever);
    }
    if (permission == LocationPermission.denied) {
      throw const LocationException(LocationFailure.denied);
    }
    final pos = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.low,
        timeLimit: Duration(seconds: 15),
      ),
    );
    return LocationFix(pos.latitude, pos.longitude);
  } on LocationException {
    rethrow;
  } catch (_) {
    throw const LocationException(LocationFailure.unavailable);
  }
}
