import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/painting.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';

/// Credit-card / MyKad aspect ratio (width / height).
const double kCardAspect = 1.586;

/// One OCR text block with its bounding box in image pixels.
class OcrBlock {
  const OcrBlock(this.text, this.box);
  final String text;
  final Rect box;
}

/// OCR output for one picture. [size] is the (upright) image size in pixels.
class OcrPage {
  const OcrPage(this.blocks, this.size);
  final List<OcrBlock> blocks;
  final Size size;
  String get text => blocks.map((b) => b.text).join('\n');
}

/// On-device OCR (ML Kit, bundled Latin model): the photo is read on the phone and is never
/// uploaded. The result only pre-fills form fields; the server re-checks everything.
Future<OcrPage> readText(String imagePath) async {
  final recognizer = TextRecognizer(script: TextRecognitionScript.latin);
  try {
    final result = await recognizer.processImage(InputImage.fromFilePath(imagePath));
    return OcrPage([for (final b in result.blocks) OcrBlock(b.text, b.boundingBox)], await _imageSize(imagePath));
  } finally {
    await recognizer.close();
  }
}

Future<Size> _imageSize(String path) async {
  final codec = await ui.instantiateImageCodec(await File(path).readAsBytes());
  try {
    final image = (await codec.getNextFrame()).image;
    final size = Size(image.width.toDouble(), image.height.toDouble());
    image.dispose();
    return size;
  } finally {
    codec.dispose();
  }
}

/// The card-shaped cut-out: 88% of the width, centred in [area].
Rect cardFrameRect(Size area) {
  final w = area.width * 0.88;
  final h = w / kCardAspect;
  return Rect.fromLTWH((area.width - w) / 2, (area.height - h) / 2, w, h);
}

/// Maps [r] (screen coordinates inside [screen]) to fractions of the camera
/// image, when that image (width / height = [imageAspect]) is drawn with
/// `BoxFit.cover` over the whole [screen].
Rect screenRectToImageFraction(Rect r, Size screen, double imageAspect) {
  final scale = math.max(screen.width / imageAspect, screen.height); // image height 1 -> pixels
  final shown = Size(imageAspect * scale, scale);
  final dx = (screen.width - shown.width) / 2;
  final dy = (screen.height - shown.height) / 2;
  return Rect.fromLTRB(
    (r.left - dx) / shown.width,
    (r.top - dy) / shown.height,
    (r.right - dx) / shown.width,
    (r.bottom - dy) / shown.height,
  );
}

/// Text of the blocks whose centre lies inside [fraction] (image fractions).
/// Falls back to all text when the size is unknown or nothing is inside.
String ocrTextInFrame(OcrPage page, Rect fraction) {
  final s = page.size;
  if (s.isEmpty) return page.text;
  final inside = page.blocks.where((b) {
    final c = b.box.center;
    return fraction.contains(Offset(c.dx / s.width, c.dy / s.height));
  });
  return inside.isEmpty ? page.text : inside.map((b) => b.text).join('\n');
}

/// "Same NRIC read in 2 consecutive passes" rule.
class StableRead {
  String? _last;

  /// Feed one pass's result (null = nothing read). True when this value
  /// equals the previous pass's non-null value.
  bool push(String? value) {
    if (value == null) {
      _last = null;
      return false;
    }
    final same = value == _last;
    _last = value;
    return same;
  }

  void reset() => _last = null;
}
