import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/card_scanner.dart';
import '../services/mykad_parser.dart';
import '../services/nric_camera.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/loading_view.dart';

enum _Phase { starting, live, review, problem }

/// Live NRIC check, like an eKYC ID step: a camera preview with a card-shaped
/// cut-out. While open it takes a picture about every 1.2 s, reads it on the
/// phone and, once the same number is read twice in a row (or the shutter is
/// pressed), shows the picture with the details to correct. Pops
/// `{'nric': ..., 'name': ...}` on "Use these details". The picture is never
/// uploaded or kept: its temp file is deleted after use.
class NricScanScreen extends StatefulWidget {
  const NricScanScreen({
    super.key,
    this.cameraFactory = DeviceNricCamera.new,
    this.ocr = readText,
    this.interval = const Duration(milliseconds: 1200),
    this.timeout = const Duration(seconds: 25),
  });

  final NricCamera Function() cameraFactory;
  final Future<OcrPage> Function(String path) ocr;
  final Duration interval;
  final Duration timeout;

  @override
  State<NricScanScreen> createState() => _NricScanScreenState();
}

class _NricScanScreenState extends State<NricScanScreen> with WidgetsBindingObserver {
  late final NricCamera _cam = widget.cameraFactory();
  final _stable = StableRead();
  final _nric = TextEditingController();
  final _name = TextEditingController();

  _Phase _phase = _Phase.starting;
  NricCameraProblem _problem = NricCameraProblem.failed;
  Timer? _loop;
  Timer? _deadline;
  bool _camReady = false;
  bool _busy = false; // a capture + OCR pass is running
  bool _torch = false;
  bool _timedOut = false;
  bool _sawNric = false;
  Size _area = Size.zero;
  String? _photoPath;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _start();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _stopLoop();
    _discardPhoto();
    _cam.dispose();
    _nric.dispose();
    _name.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      if (_phase != _Phase.review && !_camReady) _start();
    } else if (_camReady) {
      // Paused or hidden: stop reading and release the camera.
      _stopLoop();
      _camReady = false;
      _torch = false;
      _cam.dispose();
      if (mounted && _phase != _Phase.review) setState(() => _phase = _Phase.starting);
    }
  }

  Future<void> _start() async {
    if (mounted) setState(() => _phase = _Phase.starting);
    try {
      await _cam.start();
      if (!mounted) return;
      _camReady = true;
      setState(() => _phase = _Phase.live);
      _beginLoop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _problem = e is NricCameraException ? e.problem : NricCameraProblem.failed;
        _phase = _Phase.problem;
      });
    }
  }

  void _beginLoop() {
    _stopLoop();
    _stable.reset();
    _sawNric = false;
    _timedOut = false;
    _loop = Timer.periodic(widget.interval, (_) => _tick());
    _deadline = Timer(widget.timeout, () {
      _loop?.cancel();
      if (mounted) setState(() => _timedOut = true);
    });
  }

  void _stopLoop() {
    _loop?.cancel();
    _deadline?.cancel();
    _loop = null;
    _deadline = null;
  }

  /// Rect of the card frame as fractions of the camera image.
  Rect get _fraction => _area.isEmpty
      ? const Rect.fromLTWH(0, 0, 1, 1)
      : screenRectToImageFraction(cardFrameRect(_area), _area, _cam.aspectRatio);

  Future<MyKadFields> _read(String path) async {
    final page = await widget.ocr(path);
    return parseMyKadText(ocrTextInFrame(page, _fraction));
  }

  Future<void> _tick() async {
    if (_busy || _phase != _Phase.live || !_camReady) return;
    _busy = true;
    String? path;
    try {
      path = await _cam.capture();
      final fields = await _read(path);
      if (!mounted || _phase != _Phase.live || _loop == null) {
        _delete(path);
        return;
      }
      if (_stable.push(fields.nric)) {
        _showReview(path, fields);
        path = null;
      } else {
        setState(() => _sawNric = fields.nric != null);
      }
    } catch (_) {
      // One failed pass is fine; the next tick tries again.
    } finally {
      if (path != null) _delete(path);
      _busy = false;
    }
  }

  Future<void> _shutter() async {
    _stopLoop();
    for (var i = 0; _busy && i < 60; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    if (!mounted || _busy) return;
    _busy = true;
    try {
      final path = await _cam.capture();
      var fields = const MyKadFields();
      try {
        fields = await _read(path);
      } catch (_) {
        // Review still opens with empty fields to type into.
      }
      if (mounted) {
        _showReview(path, fields);
      } else {
        _delete(path);
      }
    } catch (_) {
      if (mounted) _beginLoop();
    } finally {
      _busy = false;
    }
  }

  void _showReview(String path, MyKadFields fields) {
    _stopLoop();
    _photoPath = path;
    _nric.text = fields.nric ?? '';
    _name.text = fields.name ?? '';
    setState(() => _phase = _Phase.review);
  }

  void _delete(String path) {
    try {
      File(path).deleteSync();
    } catch (_) {}
  }

  void _discardPhoto() {
    final p = _photoPath;
    _photoPath = null;
    if (p != null) _delete(p);
  }

  Future<void> _retake() async {
    _discardPhoto();
    if (_camReady) {
      setState(() => _phase = _Phase.live);
      _beginLoop();
    } else {
      await _start();
    }
  }

  void _use() {
    _discardPhoto();
    Navigator.of(context).pop(<String, String>{'nric': _nric.text.trim(), 'name': _name.text.trim()});
  }

  Future<void> _toggleTorch() async {
    try {
      await _cam.setTorch(!_torch);
      if (mounted) setState(() => _torch = !_torch);
    } catch (_) {
      if (mounted) context.snack(AppLocalizations.of(context).nricScanTorchFailed);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return switch (_phase) {
      _Phase.review => _buildReview(l10n),
      _Phase.problem => _buildProblem(l10n),
      _ => _buildLive(l10n),
    };
  }

  Widget _buildLive(AppLocalizations l10n) {
    final live = _phase == _Phase.live;
    final status = _timedOut
        ? l10n.nricScanTimeout
        : (_sawNric ? l10n.nricScanHold : l10n.nricScanLooking);
    return Scaffold(
      backgroundColor: Colors.black,
      extendBodyBehindAppBar: true,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
        elevation: 0,
        title: Text(l10n.nricScanTitle),
        actions: [
          if (live)
            IconButton(
              tooltip: l10n.nricScanTorch,
              onPressed: _toggleTorch,
              icon: Icon(_torch ? Icons.flashlight_on : Icons.flashlight_off),
            ),
        ],
      ),
      body: LayoutBuilder(
        builder: (context, box) {
          _area = Size(box.maxWidth, box.maxHeight);
          final frame = cardFrameRect(_area);
          return Stack(
            fit: StackFit.expand,
            children: [
              if (live)
                ClipRect(
                  child: FittedBox(
                    fit: BoxFit.cover,
                    child: SizedBox(
                      width: _cam.aspectRatio * 1000,
                      height: 1000,
                      child: _cam.preview(),
                    ),
                  ),
                )
              else
                const LoadingView(),
              IgnorePointer(child: CustomPaint(painter: _FramePainter(frame))),
              Positioned(
                left: 16,
                right: 16,
                top: frame.top - 64,
                child: _Pill(l10n.nricScanHint),
              ),
              if (live)
                Positioned(
                  left: 16,
                  right: 16,
                  top: frame.bottom + 16,
                  child: Semantics(liveRegion: true, child: _Pill(status)),
                ),
              if (live)
                Positioned(
                  bottom: 32,
                  left: 0,
                  right: 0,
                  child: Center(
                    child: IconButton.filled(
                      tooltip: l10n.nricScanShutter,
                      iconSize: 36,
                      style: IconButton.styleFrom(
                        backgroundColor: Colors.white,
                        foregroundColor: Colors.black,
                        minimumSize: const Size(72, 72),
                      ),
                      onPressed: _shutter,
                      icon: const Icon(Icons.camera_alt),
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildProblem(AppLocalizations l10n) {
    final p = context.palette;
    final text = switch (_problem) {
      NricCameraProblem.permission => l10n.nricScanPermission,
      NricCameraProblem.none => l10n.nricScanNoCamera,
      NricCameraProblem.failed => l10n.nricScanCameraFailed,
    };
    return Scaffold(
      appBar: AppBar(title: Text(l10n.nricScanTitle)),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.no_photography_outlined, size: 48, color: p.textMuted),
              const SizedBox(height: 16),
              Text(text, textAlign: TextAlign.center, style: TextStyle(color: p.textBody, height: 1.4)),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(),
                child: Text(l10n.nricScanTypeInstead),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildReview(AppLocalizations l10n) {
    final p = context.palette;
    final path = _photoPath;
    return Scaffold(
      appBar: AppBar(title: Text(l10n.nricScanReviewTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (path != null)
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 220),
                  child: Image.file(
                    File(path),
                    fit: BoxFit.contain,
                    errorBuilder: (_, _, _) => const SizedBox.shrink(),
                  ),
                ),
              ),
            const SizedBox(height: 12),
            Text(l10n.nricScanReviewHint, style: TextStyle(fontSize: 13, color: p.textBody)),
            const SizedBox(height: 4),
            Text(l10n.selfRegisterScanPrivacy, style: TextStyle(fontSize: 12, color: p.textMuted)),
            const SizedBox(height: 16),
            TextField(
              controller: _nric,
              autocorrect: false,
              decoration: InputDecoration(labelText: l10n.nricLabel),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _name,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(labelText: l10n.fullNameLabel),
            ),
            const SizedBox(height: 20),
            FilledButton(onPressed: _use, child: Text(l10n.nricScanUse)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _retake, child: Text(l10n.nricScanRetake)),
          ],
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(color: Colors.black.withValues(alpha: 0.7), borderRadius: BorderRadius.circular(12)),
          child: Text(text, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white, fontSize: 14)),
        ),
      );
}

/// Dimmed overlay with a card-shaped cut-out and corner brackets.
class _FramePainter extends CustomPainter {
  const _FramePainter(this.frame);
  final Rect frame;

  @override
  void paint(Canvas canvas, Size size) {
    final hole = RRect.fromRectAndRadius(frame, const Radius.circular(12));
    final dim = Path.combine(
      PathOperation.difference,
      Path()..addRect(Offset.zero & size),
      Path()..addRRect(hole),
    );
    canvas.drawPath(dim, Paint()..color = Colors.black.withValues(alpha: 0.55));

    final line = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round;
    const len = 28.0;
    for (final (corner, dx, dy) in [
      (frame.topLeft, 1.0, 1.0),
      (frame.topRight, -1.0, 1.0),
      (frame.bottomLeft, 1.0, -1.0),
      (frame.bottomRight, -1.0, -1.0),
    ]) {
      canvas.drawLine(corner, corner + Offset(dx * len, 0), line);
      canvas.drawLine(corner, corner + Offset(0, dy * len), line);
    }
  }

  @override
  bool shouldRepaint(_FramePainter old) => old.frame != frame;
}
