import 'package:dio/dio.dart';

/// A friendly, UI-ready wrapper around whatever Dio throws.
final _isoUtc = RegExp(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z');

/// "...Try again after 2026-10-10T08:25:40Z." -> "...after 4:25 PM (in 4 minutes)."
/// in the device's own timezone, 12-hour clock.
String _friendlyDetail(String text) {
  text = text.replaceAll('Value error, ', '');
  return text.replaceAllMapped(_isoUtc, (m) {
    final when = DateTime.tryParse(m.group(0)!)?.toLocal();
    if (when == null) return m.group(0)!;
    final h = when.hour % 12 == 0 ? 12 : when.hour % 12;
    final clock = '$h:${when.minute.toString().padLeft(2, '0')} ${when.hour < 12 ? 'AM' : 'PM'}';
    final mins = (when.difference(DateTime.now()).inSeconds / 60).ceil();
    if (mins <= 0) return clock;
    return mins <= 1 ? '$clock (in under a minute)' : '$clock (in $mins minutes)';
  });
}

class ApiException implements Exception {
  final String message;
  final int? statusCode;

  /// The raw decoded JSON response body, when the backend returned one and
  /// it was shaped as a `Map` (e.g. `{"detail": "...", "next_step": "...",
  /// "photo_attempts_remaining": 3}`). Most call sites only need
  /// [message]/[statusCode] and can ignore this — it exists for the
  /// self-service registration photo-verification step
  /// (`ApiClient.selfRegisterVerifyPhotos`), where a failure response
  /// carries extra structured fields (`next_step`,
  /// `photo_attempts_remaining`) the UI needs beyond just a display
  /// string, and there was previously no way for a caller to reach them.
  /// `null` for non-Map bodies or when there's no response at all (e.g. a
  /// connection error).
  final Map<String, dynamic>? data;

  /// True only when the failure was "no usable network path" (timeout,
  /// connection error, or a caller-imposed cancel) -- NOT for a bad
  /// certificate or any real HTTP answer. The offline-tag fallback keys on
  /// this so a TLS/pinning failure can never be used to force it.
  final bool isUnreachable;

  ApiException(this.message, {this.statusCode, this.data, this.isUnreachable = false});

  /// Shown instead of interpolating a raw/unexpectedly-shaped backend
  /// `detail` value (e.g. a List — either a FastAPI 422 validation-error
  /// list, or the known backend bug where a password-validation error was
  /// returned as a raw JSON array instead of a string) directly into the
  /// UI. Defense in depth: this hardening is kept even after that backend
  /// bug is fixed, since any future endpoint could make the same mistake.
  static const _genericDetailFallback = 'Something went wrong. Please try again.';

  factory ApiException.fromDioException(DioException e) {
    final status = e.response?.statusCode;
    final data = e.response?.data;
    final responseData = data is Map<String, dynamic> ? data : null;

    String detail = e.message ?? 'Network error';
    final rawDetail = data is Map ? data['detail'] : null;
    if (rawDetail is String) {
      if (rawDetail.trim().isNotEmpty) detail = rawDetail;
    } else if (rawDetail is List) {
      // Try to salvage a readable message from a FastAPI-shaped validation
      // error list (`[{"loc": [...], "msg": "...", "type": "..."}, ...]`)
      // before giving up and falling back to something generic — never
      // just `.toString()` the raw list into the UI.
      final msgs = rawDetail
          .whereType<Map>()
          .map((item) => item['msg'])
          .whereType<String>()
          .where((s) => s.trim().isNotEmpty)
          .toList();
      detail = msgs.isNotEmpty ? msgs.join('\n') : _genericDetailFallback;
    } else if (rawDetail != null) {
      // Any other unexpected shape (number, bool, nested object, ...).
      detail = _genericDetailFallback;
    }

    detail = _friendlyDetail(detail);

    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return ApiException(
          'The server took too long to respond. Check the API base URL in '
          'Settings and that the backend is reachable.',
          statusCode: status,
          isUnreachable: true,
        );
      case DioExceptionType.cancel:
        return ApiException('The request was cancelled.', statusCode: status, isUnreachable: true);
      case DioExceptionType.connectionError:
        return ApiException(
          'Could not reach the backend. Check the API base URL in Settings '
          '(currently pointing somewhere unreachable) and your network connection.',
          statusCode: status,
          isUnreachable: true,
        );
      default:
        if (status == 401) {
          return ApiException('Your session has expired. Please sign in again.',
              statusCode: status, data: responseData);
        }
        if (status == 403) {
          return ApiException(detail.isNotEmpty ? detail : 'Not authorized to view this.',
              statusCode: status, data: responseData);
        }
        if (status == 404) {
          return ApiException(detail.isNotEmpty ? detail : 'Not found.',
              statusCode: status, data: responseData);
        }
        return ApiException(detail, statusCode: status, data: responseData);
    }
  }

  @override
  String toString() => message;
}
