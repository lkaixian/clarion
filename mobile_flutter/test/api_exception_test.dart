import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile_flutter/services/api_exception.dart';

DioException _bad(int status, Object? body) {
  final req = RequestOptions(path: '/x');
  return DioException.badResponse(
    statusCode: status,
    requestOptions: req,
    response: Response(requestOptions: req, statusCode: status, data: body),
  );
}

void main() {
  test('a JSON error inside a bytes (PDF) response keeps the server message', () {
    final body = utf8.encode(jsonEncode({'detail': 'Visit summary not available'}));
    final e = ApiException.fromDioException(_bad(404, body));
    expect(e.message, 'Visit summary not available');
    expect(e.statusCode, 404);
  });

  test('an undecodable 4xx body never shows the raw Dio "bad syntax" text', () {
    final e = ApiException.fromDioException(_bad(400, <int>[0xff, 0xfe]));
    expect(e.message, isNot(contains('bad syntax')));
    expect(e.message, contains('400'));
  });
}
