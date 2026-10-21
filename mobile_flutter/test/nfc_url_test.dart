import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:nfc_manager/ndef_record.dart';

import 'package:mobile_flutter/screens/scan_hub_screen.dart';
import 'package:mobile_flutter/services/nfc_service.dart';

void main() {
  group('parseClarionQr', () {
    test('new link, any host, trailing slash, query and fragment', () {
      for (final u in [
        'https://clarion.larmkx.com/e/abc123',
        'http://other.example/e/abc123/',
        'https://x.test/e/abc123?utm=1#top',
      ]) {
        final p = parseClarionQr(u);
        expect(p?.kind, QrKind.emergency, reason: u);
        expect(p?.token, 'abc123', reason: u);
      }
    });
    test('legacy prefix still works', () {
      expect(parseClarionQr('CLARION-EMERGENCY:xyz')?.token, 'xyz');
      expect(parseClarionQr('CLARION-STATION:s1')?.kind, QrKind.checkin);
    });
    test('junk is rejected', () {
      for (final u in [
        '',
        'abc',
        'ftp://x.test/e/abc',
        'https://x.test/e/',
        'https://x.test/e',
        'https://x.test/e/a/b',
        'https://x.test/other/abc',
        'CLARION-EMERGENCY:',
      ]) {
        expect(parseClarionQr(u), isNull, reason: u);
      }
    });
    test('/e/n/x, encoded dots and empty refs are rejected', () {
      for (final u in [
        'https://x.test/e/n/04a1b2c3',
        'https://x.test/e/n/x',
        'https://x.test/e/%2e%2e',
        'https://x.test/e/',
        'https://x.test/e/a%20b',
      ]) {
        expect(parseClarionQr(u), isNull, reason: u);
      }
    });
  });

  group('isValidPublicUrl', () {
    test('accepts the server link', () {
      expect(NfcService.isValidPublicUrl('https://h.test/e/AbC_-123'), isTrue);
    });
    test('rejects everything else', () {
      for (final u in [
        'http://h.test/e/AbC_-123',
        'https://user@h.test/e/AbC_-123',
        'https://h.test/e/AbC_-123?x=1',
        'https://h.test/e/AbC_-123#f',
        'https://h.test/e/AbC_-123/',
        'https://h.test/x/AbC_-123',
        'https://h.test/e/n/AbC_-123',
        'https://h.test/e/short',
        'https://h.test/e/${'a' * 65}',
        'junk',
        '',
      ]) {
        expect(NfcService.isValidPublicUrl(u), isFalse, reason: u);
      }
    });
  });

  group('tag records', () {
    const blob = 'C1.1.abcdef';

    test('https URI record uses prefix 0x04', () {
      final r = NfcService.buildUriRecord('https://h.test/e/AbC_-123');
      expect(r.typeNameFormat, TypeNameFormat.wellKnown);
      expect(r.type, [0x55]);
      expect(r.payload.first, 0x04);
      expect(utf8.decode(r.payload.sublist(1)), 'h.test/e/AbC_-123');
    });
    test('http uses 0x03, other schemes 0x00 + full URL', () {
      expect(NfcService.buildUriRecord('http://h.test/x').payload.first, 0x03);
      final o = NfcService.buildUriRecord('tel:123');
      expect(o.payload.first, 0x00);
      expect(utf8.decode(o.payload.sublist(1)), 'tel:123');
    });
    test('URI first, then launch marker, then text; size includes the URI', () {
      final url = NfcService.buildTagRecords(blob, publicUrl: 'https://h.test/e/AbC_-123');
      expect(url.length, 3);
      expect(url[0].type, [0x55]);
      expect(utf8.decode(url[1].type), 'application/vnd.clarion');
      expect(url[2].type, [0x54]);
      final plain = NfcService.buildTagRecords(blob);
      expect(plain.length, 2);
      expect(utf8.decode(plain[0].type), 'application/vnd.clarion');
      expect(NdefMessage(records: url).byteLength, greaterThan(NdefMessage(records: plain).byteLength));
    });
    test('reader skips the URI record and finds the text', () {
      final msg = NdefMessage(records: NfcService.buildTagRecords(blob, publicUrl: 'https://h.test/e/AbC_-123'));
      expect(NfcService.extractTextRecord(msg), blob);
    });
  });
}
