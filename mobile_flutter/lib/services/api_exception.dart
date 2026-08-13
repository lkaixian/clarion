import 'package:dio/dio.dart';

/// A friendly, UI-ready wrapper around whatever Dio throws.
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  ApiException(this.message, {this.statusCode});

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

    switch (e.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return ApiException(
          'The server took too long to respond. Check the API base URL in '
          'Settings and that the backend is reachable.',
          statusCode: status,
        );
      case DioExceptionType.connectionError:
        return ApiException(
          'Could not reach the backend. Check the API base URL in Settings '
          '(currently pointing somewhere unreachable) and your network connection.',
          statusCode: status,
        );
      default:
        if (status == 401) {
          return ApiException('Your session has expired. Please sign in again.', statusCode: status);
        }
        if (status == 403) {
          return ApiException(detail.isNotEmpty ? detail : 'Not authorized to view this.', statusCode: status);
        }
        if (status == 404) {
          return ApiException(detail.isNotEmpty ? detail : 'Not found.', statusCode: status);
        }
        return ApiException(detail, statusCode: status);
    }
  }

  @override
  String toString() => message;
}
