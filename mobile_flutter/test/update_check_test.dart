import 'package:flutter_test/flutter_test.dart';
import 'package:mobile_flutter/services/update_check.dart';

void main() {
  test('compareVersions is numeric, not lexical', () {
    expect(compareVersions('1.10.0', '1.9.0'), greaterThan(0));
    expect(compareVersions('1.3.0', '1.3.0'), 0);
    expect(compareVersions('1.3.0+5', '1.3.0'), 0);
    expect(compareVersions('1.3', '1.3.1'), lessThan(0));
    expect(compareVersions('2.0.0', '10.0.0'), lessThan(0));
  });
}
