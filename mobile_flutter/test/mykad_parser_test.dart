import 'package:flutter_test/flutter_test.dart';

import 'package:mobile_flutter/services/mykad_parser.dart';

void main() {
  test('finds the number and a two-line name below it (synthetic text)', () {
    const text = 'KAD PENGENALAN\nMALAYSIA\n900101-01-1234\nAMINAH BINTI\nABDUL TEST\n'
        'NO 12 JALAN CONTOH\n81300 SKUDAI\nJOHOR\nISLAM\nPEREMPUAN\nWARGANEGARA';
    final f = parseMyKadText(text);
    expect(f.nric, '900101-01-1234');
    expect(f.name, 'AMINAH BINTI ABDUL TEST');
  });

  test('accepts the number without dashes or with spaces', () {
    expect(parseMyKadText('900101 01 1234\nALI BIN ABU').nric, '900101-01-1234');
    expect(parseMyKadText('900101011234\nALI BIN ABU').name, 'ALI BIN ABU');
  });

  test('name printed above the number is still found', () {
    final f = parseMyKadText('ALI BIN ABU\n900101-01-1234\nJALAN CONTOH');
    expect(f.name, 'ALI BIN ABU');
  });

  test('hologram noise lines around the real name are ignored', () {
    const text = 'KAD PENGENALAN\n900101-01-1234\nWMACAYSAKERA AS AYSAKEHRIAAS\n'
        'LARM KAI XIAN\nAKERAJAA\nJALAN CONTOH';
    final f = parseMyKadText(text);
    expect(f.nric, '900101-01-1234');
    expect(f.name, 'LARM KAI XIAN');
  });

  test('noise yields nothing rather than a wrong guess', () {
    final f = parseMyKadText('1x3 ;; ~~\n..\n12');
    expect(f.isEmpty, isTrue);
  });
}
