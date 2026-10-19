import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:mobile_flutter/l10n/generated/app_localizations.dart';
import 'package:mobile_flutter/screens/nric_scan_screen.dart';
import 'package:mobile_flutter/services/card_scanner.dart';
import 'package:mobile_flutter/services/nric_camera.dart';

class FakeCamera implements NricCamera {
  FakeCamera({this.problem});
  final NricCameraProblem? problem;
  int captures = 0;
  bool disposed = false;

  @override
  Future<void> start() async {
    if (problem != null) throw NricCameraException(problem!);
  }

  @override
  Widget preview() => const SizedBox.expand();

  @override
  double get aspectRatio => 0.75;

  @override
  Future<String> capture() async => 'fake-${captures++}.jpg';

  @override
  Future<void> setTorch(bool on) async {}

  @override
  Future<void> dispose() async => disposed = true;
}

Future<Map<String, String>?> pumpScan(
  WidgetTester tester, {
  required NricCamera Function() camera,
  required Future<OcrPage> Function(String) ocr,
  Duration timeout = const Duration(seconds: 25),
}) async {
  Map<String, String>? result;
  await tester.pumpWidget(
    MaterialApp(
      locale: const Locale('en'),
      supportedLocales: const [Locale('en')],
      localizationsDelegates: const [
        AppLocalizations.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () async {
              result = await Navigator.of(context).push<Map<String, String>>(MaterialPageRoute(
                builder: (_) => NricScanScreen(
                  cameraFactory: camera,
                  ocr: ocr,
                  interval: const Duration(milliseconds: 100),
                  timeout: timeout,
                ),
              ));
            },
            child: const Text('open'),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pump();
  await tester.pump();
  return result;
}

void main() {
  group('pure helpers', () {
    test('card frame is 88% wide, card shaped and centred', () {
      final r = cardFrameRect(const Size(400, 800));
      expect(r.width, closeTo(352, 0.01));
      expect(r.width / r.height, closeTo(kCardAspect, 0.001));
      expect(r.center, const Offset(200, 400));
    });

    test('screen to image fraction with BoxFit.cover', () {
      // Image 3:4 shown full-width on a 400x800 screen: image is 400x533 scaled
      // up to cover the height => 600x800, so 100px is cropped each side.
      final f = screenRectToImageFraction(const Rect.fromLTWH(0, 0, 400, 800), const Size(400, 800), 0.75);
      expect(f.left, closeTo(1 / 6, 0.001));
      expect(f.right, closeTo(5 / 6, 0.001));
      expect(f.top, closeTo(0, 0.001));
      expect(f.bottom, closeTo(1, 0.001));
      // Same aspect as the screen: fractions equal screen fractions.
      final g = screenRectToImageFraction(const Rect.fromLTWH(40, 80, 200, 160), const Size(400, 800), 0.5);
      expect(g.left, closeTo(0.1, 0.001));
      expect(g.top, closeTo(0.1, 0.001));
      expect(g.width, closeTo(0.5, 0.001));
    });

    test('only blocks centred inside the frame are used, else all text', () {
      const page = OcrPage(
        [
          OcrBlock('OUTSIDE NOISE', Rect.fromLTWH(0, 0, 100, 50)),
          OcrBlock('900101-01-1234', Rect.fromLTWH(400, 450, 200, 40)),
        ],
        Size(1000, 1000),
      );
      expect(ocrTextInFrame(page, const Rect.fromLTRB(0.2, 0.3, 0.8, 0.7)), '900101-01-1234');
      // Nothing inside: fall back to everything.
      expect(ocrTextInFrame(page, const Rect.fromLTRB(0.9, 0.9, 1, 1)), contains('OUTSIDE NOISE'));
      // Unknown image size: everything.
      expect(ocrTextInFrame(const OcrPage([OcrBlock('A', Rect.zero)], Size.zero), Rect.zero), 'A');
    });

    test('same NRIC in 2 consecutive passes is stable; a gap or change resets', () {
      final s = StableRead();
      expect(s.push('900101-01-1234'), isFalse);
      expect(s.push('900101-01-1234'), isTrue);

      final t = StableRead();
      expect(t.push('900101-01-1234'), isFalse);
      expect(t.push(null), isFalse);
      expect(t.push('900101-01-1234'), isFalse);
      expect(t.push('900101-01-1235'), isFalse);
      expect(t.push('900101-01-1235'), isTrue);
    });
  });

  group('scan screen', () {
    testWidgets('auto-captures on the second identical read and returns the edited details', (tester) async {
      final cam = FakeCamera();
      var calls = 0;
      Future<OcrPage> ocr(String path) async {
        calls++;
        return const OcrPage([OcrBlock('900101-01-1234\nALI BIN ABU', Rect.zero)], Size.zero);
      }

      await pumpScan(tester, camera: () => cam, ocr: ocr);
      expect(find.text('Fit the front of your NRIC inside the frame'), findsOneWidget);
      expect(find.text('Looking for the card…'), findsOneWidget);

      await tester.pump(const Duration(milliseconds: 100));
      await tester.pump();
      expect(find.text('Hold steady'), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pump();

      expect(calls, 2);
      expect(find.text('Use these details'), findsOneWidget);
      expect(find.widgetWithText(TextField, '900101-01-1234'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'ALI BIN ABU'), findsOneWidget);

      await tester.tap(find.text('Retake'));
      await tester.pump();
      expect(find.text('Use these details'), findsNothing);
      expect(find.text('Looking for the card…'), findsOneWidget);

      await tester.pumpWidget(const SizedBox());
      expect(cam.disposed, isTrue);
    });

    testWidgets('manual shutter goes to review with whatever was read', (tester) async {
      final cam = FakeCamera();
      await pumpScan(
        tester,
        camera: () => cam,
        ocr: (_) async => const OcrPage([], Size.zero),
      );
      await tester.tap(find.byTooltip('Take picture'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('Use these details'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('times out with a message and the shutter stays available', (tester) async {
      final cam = FakeCamera();
      await pumpScan(
        tester,
        camera: () => cam,
        ocr: (_) async => const OcrPage([], Size.zero),
        timeout: const Duration(milliseconds: 450),
      );
      await tester.pump(const Duration(milliseconds: 500));
      await tester.pump();
      expect(find.textContaining('Could not read the card'), findsOneWidget);
      expect(find.byTooltip('Take picture'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('permission denied explains and offers to type instead', (tester) async {
      await pumpScan(
        tester,
        camera: () => FakeCamera(problem: NricCameraProblem.permission),
        ocr: (_) async => const OcrPage([], Size.zero),
      );
      await tester.pump();
      expect(find.textContaining('Camera access is off'), findsOneWidget);
      expect(find.text('Type my details instead'), findsOneWidget);
    });
  });
}
