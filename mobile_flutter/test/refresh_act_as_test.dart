// Plain test() file: no widget binding, so a real loopback HttpServer works.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class MemStorage extends TokenStorage {
  final m = <String, Object?>{};
  @override
  Future<void> saveToken(String t) async => m['token'] = t;
  @override
  Future<String?> readToken() async => m['token'] as String?;
  @override
  Future<void> saveRefreshToken(String t) async => m['refresh'] = t;
  @override
  Future<String?> readRefreshToken() async => m['refresh'] as String?;
  @override
  Future<void> saveUser(Map<String, dynamic> u) async => m['user'] = u;
  @override
  Future<String?> readActivePatient() async => m['active'] as String?;
}

void main() {
  test('refresh sends act_as for the active profile', () async {
    SharedPreferences.setMockInitialValues({});
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    Map<String, dynamic>? refreshBody;
    server.listen((req) async {
      final body = await utf8.decoder.bind(req).join();
      req.response.headers.contentType = ContentType.json;
      if (req.uri.path == '/auth/refresh') {
        refreshBody = jsonDecode(body) as Map<String, dynamic>;
        req.response.write(jsonEncode({'access_token': 'new', 'refresh_token': 'r2'}));
      } else if (req.headers.value('authorization') == 'Bearer new') {
        req.response.write(jsonEncode({'active_patient_id': 'kid', 'profiles': []}));
      } else {
        req.response.statusCode = 401;
        req.response.write(jsonEncode({'detail': 'expired'}));
      }
      await req.response.close();
    });
    final config = AppConfig();
    await config.setBaseUrl('http://127.0.0.1:${server.port}');
    final storage = MemStorage()
      ..m['token'] = 'old'
      ..m['refresh'] = 'r1'
      ..m['active'] = 'kid';
    final api = ApiClient(config: config, tokenStorage: storage);

    await api.getProfiles();
    expect(refreshBody, {'refresh_token': 'r1', 'act_as': 'kid'});
    expect(storage.m['token'], 'new');

    // Own profile: no act_as.
    storage.m['active'] = null;
    storage.m['token'] = 'old';
    await api.getProfiles();
    expect(refreshBody!.containsKey('act_as'), isFalse);
  });
}
