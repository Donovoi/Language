import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/services.dart';

class MicrophoneClip {
  MicrophoneClip.fromMap(Map<Object?, Object?> values)
    : pcm = Uint8List.fromList(values['pcm'] as Uint8List),
      sampleRate = values['sampleRate'] as int,
      frames = values['frames'] as int,
      elapsedMs = values['elapsedMs'] as int,
      inputType = values['inputType'] as int?,
      inputName = values['inputName'] as String? ?? 'Unknown input',
      silenced = values['silenced'] as bool {
    if (sampleRate != 16000 ||
        frames <= 0 ||
        frames > 80000 ||
        pcm.length != frames * 2) {
      discard();
      throw const FormatException('Invalid microphone PCM response.');
    }
    final samples = ByteData.sublistView(pcm);
    var sumSquares = 0.0;
    var peak = 0;
    var nonzero = 0;
    var clipped = 0;
    for (var i = 0; i < frames; i++) {
      final value = samples.getInt16(i * 2, Endian.little).abs();
      sumSquares += value * value;
      peak = math.max(peak, value);
      if (value != 0) nonzero++;
      if (value >= 32767) clipped++;
    }
    rmsDbfs = _dbfs(math.sqrt(sumSquares / frames) / 32768);
    peakDbfs = _dbfs(peak / 32768);
    nonzeroFraction = nonzero / frames;
    clippedFraction = clipped / frames;
  }

  final Uint8List pcm;
  final int sampleRate;
  final int frames;
  final int elapsedMs;
  final int? inputType;
  final String inputName;
  final bool silenced;
  late final double rmsDbfs;
  late final double peakDbfs;
  late final double nonzeroFraction;
  late final double clippedFraction;

  bool get hasSignal => !silenced && nonzeroFraction > 0 && rmsDbfs > -90;
  double get seconds => frames / sampleRate;
  void discard() => pcm.fillRange(0, pcm.length, 0);

  static double _dbfs(double amplitude) => amplitude > 0
      ? math.max(-120, 20 * math.log(amplitude) / math.ln10)
      : -120;
}

class MicrophoneCheck {
  const MicrophoneCheck();
  static const channel = MethodChannel('language/microphone_check');

  Future<bool> permissionStatus() async =>
      await channel.invokeMethod<bool>('permissionStatus') ?? false;
  Future<bool> requestPermission() async =>
      await channel.invokeMethod<bool>('requestPermission') ?? false;
  Future<MicrophoneClip> capture({int durationMs = 3000}) async =>
      MicrophoneClip.fromMap(
        (await channel.invokeMapMethod<Object?, Object?>('capture', {
          'durationMs': durationMs,
        }))!,
      );
  Future<Map<Object?, Object?>> play() async =>
      (await channel.invokeMapMethod<Object?, Object?>('play'))!;
  Future<void> clear() => channel.invokeMethod<void>('clear');
}
