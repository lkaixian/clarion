import 'package:dio/dio.dart';

/// A friendly, UI-ready wrapper around whatever Dio throws.
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  ApiException(this.message, {this.statusCode});

  factory ApiException.fromDioException(DioException e) {
    final status = e.response?.statusCode;
    final data = e.response?.data;

    String detail = e.message ?? 'Network error';
    if (data is Map && data['detail'] != null) {
      detail = data['detail'].toString();
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
