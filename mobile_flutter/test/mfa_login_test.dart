import 'package:flutter_test/flutter_test.dart';

import 'package:mobile_flutter/config/app_config.dart';
import 'package:mobile_flutter/providers/auth_provider.dart';
import 'package:mobile_flutter/services/api_client.dart';
import 'package:mobile_flutter/services/api_exception.dart';
import 'package:mobile_flutter/services/token_storage.dart';

class MemoryStorage extends TokenStorage {
  String? token;
  @override
  Future<void> saveToken(String t) async => token = t;
  @override
  Future<void> saveRefreshToken(String t) async {}
  @override
  Future<void> saveUser(Map<String, dynamic> u) async {}
  @override
  Future<String?> readToken() async => token;
  @override
  Future<void> saveActivePatient(String? id) async {}
}

const _session = {
  'access_token': 'a',
  'refresh_token': 'r',
  'user': {'id': 'u1', 'email': 'p@x.test', 'full_name': 'P', 'role': 'patient'},
};

class FakeApi extends ApiClient {
  FakeApi() : super(config: AppConfig(), tokenStorage: TokenStorage());

  Map<String, dynamic> loginResponse = {
    'mfa_required': true,
    'mfa_token': 'chal',
    'email_available': true,
    'email_hint': 'p***@x.test',
  };
  final calls = <String>[];
  ApiException? authError;

  @override
  Future<Map<String, dynamic>> login(String email, String password) async => loginResponse;

  @override
  Future<Map<String, dynamic>> verifyMfa(String t, String code) async {
    calls.add('totp:$code');
    if (authError != null) throw authError!;
    return _session;
  }

  @override
  Future<Map<String, dynamic>> sendMfaEmailCode(String t) async {
    calls.add('send');
    return {'status': 'ok', 'email_hint': 'p***@x.test'};
  }

  @override
  Future<Map<String, dynamic>> verifyMfaEmail(String t, String code) async {
    calls.add('email:$code');
    return _session;
  }
}

void main() {
  late FakeApi api;
  late AuthProvider auth;

  setUp(() {
    api = FakeApi();
    auth = AuthProvider(api: api, tokenStorage: MemoryStorage());
  });

  test('password step with a second factor shows the code step, not a failure', () async {
    expect(await auth.login('p', 'pw'), isFalse);
    expect(auth.awaitingMfa, isTrue);
    expect(auth.mfaEmailAvailable, isTrue);
    expect(auth.error, isNull);
  });

  test('authenticator code signs in', () async {
    await auth.login('p', 'pw');
    expect(await auth.verifyMfa('123456'), isTrue);
    expect(auth.isAuthenticated, isTrue);
    expect(auth.awaitingMfa, isFalse);
  });

  test('a refused code keeps the challenge and flags codeRejected', () async {
    await auth.login('p', 'pw');
    api.authError = ApiException('Invalid code', statusCode: 401);
    expect(await auth.verifyMfa('000000'), isFalse);
    expect(auth.awaitingMfa, isTrue);
    expect(auth.codeRejected, isTrue);
  });

  test('emailing a code switches the next verify to the email endpoint', () async {
    await auth.login('p', 'pw');
    expect(await auth.sendMfaEmail(), isTrue);
    expect(auth.mfaEmailSent, isTrue);
    expect(await auth.verifyMfa('654321'), isTrue);
    expect(api.calls, ['send', 'email:654321']);
  });

  test('account that has no authenticator yet can finish with the email code', () async {
    api.loginResponse = {
      'mfa_required': true,
      'mfa_enrol': true,
      'mfa_token': 'chal',
      'email_available': true,
      'email_hint': 'p***@x.test',
    };
    await auth.login('p', 'pw');
    expect(auth.awaitingMfa, isTrue);
    expect(auth.mfaAuthenticatorOk, isFalse);
  });

  test('enrolment required and no email option still points to the web console', () async {
    api.loginResponse = {'mfa_required': true, 'mfa_enrol': true, 'mfa_token': 'chal'};
    await auth.login('p', 'pw');
    expect(auth.awaitingMfa, isFalse);
    expect(auth.error, contains('web console'));
  });
}
