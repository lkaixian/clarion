import 'package:camera/camera.dart';
import 'package:flutter/widgets.dart';

enum NricCameraProblem { permission, none, failed }

class NricCameraException implements Exception {
  const NricCameraException(this.problem);
  final NricCameraProblem problem;
}

/// What the live NRIC scan screen needs from a camera. A seam so the screen
/// can be widget-tested with a fake (the real one needs a device).
abstract class NricCamera {
  /// Opens the back camera. Throws [NricCameraException].
  Future<void> start();
  Widget preview();

  /// Upright preview width / height.
  double get aspectRatio;

  /// Takes a still picture and returns its temp file path.
  Future<String> capture();
  Future<void> setTorch(bool on);
  Future<void> dispose();
}

class DeviceNricCamera implements NricCamera {
  CameraController? _controller;

  @override
  Future<void> start() async {
    final List<CameraDescription> cameras;
    try {
      cameras = await availableCameras();
    } on CameraException {
      throw const NricCameraException(NricCameraProblem.failed);
    }
    if (cameras.isEmpty) throw const NricCameraException(NricCameraProblem.none);
    final back = cameras.firstWhere(
      (c) => c.lensDirection == CameraLensDirection.back,
      orElse: () => cameras.first,
    );
    final controller = CameraController(back, ResolutionPreset.medium, enableAudio: false);
    _controller = controller;
    try {
      await controller.initialize();
      await controller.setFlashMode(FlashMode.off);
    } on CameraException catch (e) {
      _controller = null;
      await controller.dispose();
      throw NricCameraException(
        e.code.startsWith('CameraAccess') ? NricCameraProblem.permission : NricCameraProblem.failed,
      );
    }
  }

  @override
  Widget preview() => CameraPreview(_controller!);

  @override
  double get aspectRatio {
    final a = _controller?.value.aspectRatio ?? 0.75;
    return a > 1 ? 1 / a : a; // portrait
  }

  @override
  Future<String> capture() async => (await _controller!.takePicture()).path;

  @override
  Future<void> setTorch(bool on) => _controller!.setFlashMode(on ? FlashMode.torch : FlashMode.off);

  @override
  Future<void> dispose() async {
    final c = _controller;
    _controller = null;
    await c?.dispose();
  }
}
