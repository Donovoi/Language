import 'dart:convert';

import 'package:field_app_flutter/features/audio/microphone_check_screen.dart';
import 'package:field_app_flutter/services/microphone_check.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const microphone = MicrophoneCheck();
  const physical = bool.fromEnvironment('FIELD_APP_PHYSICAL_AUDIO');

  testWidgets('bounded native capture, playback, cancellation and clearing', (
    tester,
  ) async {
    await tester.pumpWidget(const MaterialApp(home: MicrophoneCheckScreen()));
    await tester.pumpAndSettle();
    addTearDown(microphone.clear);
    // The runner revokes permission before launch, then grants only at this marker.
    expect(await microphone.permissionStatus(), isFalse);
    await expectLater(
      microphone.capture(),
      throwsA(
        isA<PlatformException>().having(
          (error) => error.code,
          'code',
          'permission',
        ),
      ),
    );
    // ignore: avoid_print
    print('AUDIO_PERMISSION_WAIT');
    final deadline = DateTime.now().add(const Duration(seconds: 30));
    while (!await microphone.permissionStatus() &&
        DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    expect(await microphone.permissionStatus(), isTrue);
    await expectLater(
      microphone.capture(durationMs: 5001),
      throwsA(
        isA<PlatformException>().having(
          (error) => error.code,
          'code',
          'duration',
        ),
      ),
    );
    await expectLater(
      microphone.play(),
      throwsA(
        isA<PlatformException>().having((error) => error.code, 'code', 'empty'),
      ),
    );

    // No fixture or mocked platform channel supplies these PCM samples.
    // ignore: avoid_print
    print('AUDIO_CAPTURE_START');
    final clip = await microphone.capture();
    expect(clip.frames, 48000);
    expect(clip.elapsedMs, inInclusiveRange(2500, 5000));
    expect(clip.rmsDbfs.isFinite && clip.peakDbfs.isFinite, isTrue);
    if (physical) {
      expect(
        clip.silenced,
        isFalse,
        reason: 'Android silenced this microphone client.',
      );
      expect(
        clip.inputType,
        isNotNull,
        reason: 'No active input route reported.',
      );
      expect(
        clip.hasSignal,
        isTrue,
        reason: 'No room signal; this is not a passing physical capture.',
      );
    }
    final playback = await microphone.play();
    expect(playback['playedFrames'] as int, greaterThanOrEqualTo(clip.frames));
    if (physical) expect(playback['outputType'], isNotNull);
    // Only numeric/route diagnostics leave the device; never print or save raw PCM.
    // ignore: avoid_print
    print(
      'AUDIO_METRICS ${jsonEncode({'physical_device': physical, 'frames': clip.frames, 'sample_rate': clip.sampleRate, 'elapsed_ms': clip.elapsedMs, 'rms_dbfs': clip.rmsDbfs, 'peak_dbfs': clip.peakDbfs, 'nonzero_fraction': clip.nonzeroFraction, 'clipped_fraction': clip.clippedFraction, 'silenced': clip.silenced, 'input_type': clip.inputType, 'played_frames': playback['playedFrames'], 'output_type': playback['outputType'], 'stimulus': 'uncontrolled_room_sound', 'acoustic_quality_verified': false, 'release_audio_evidence': false})}',
    );
    clip.discard();
    final playing = microphone.play();
    final playbackCancelled = expectLater(
      playing,
      throwsA(
        isA<PlatformException>().having(
          (error) => error.code,
          'code',
          'cancelled',
        ),
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final playbackStopping = Stopwatch()..start();
    await microphone.clear();
    await playbackCancelled;
    expect(playbackStopping.elapsedMilliseconds, lessThan(1000));
    await expectLater(
      microphone.play(),
      throwsA(
        isA<PlatformException>().having((error) => error.code, 'code', 'empty'),
      ),
    );

    // Exercise stop/retry repeatedly so late completion cannot restore an old clip.
    for (var i = 0; i < 3; i++) {
      final capture = microphone.capture();
      final cancelled = expectLater(
        capture,
        throwsA(
          isA<PlatformException>().having(
            (error) => error.code,
            'code',
            'cancelled',
          ),
        ),
      );
      await Future<void>.delayed(const Duration(milliseconds: 150));
      await expectLater(
        microphone.capture(),
        throwsA(
          isA<PlatformException>().having(
            (error) => error.code,
            'code',
            'busy',
          ),
        ),
      );
      final stopping = Stopwatch()..start();
      await microphone.clear();
      await cancelled;
      expect(stopping.elapsedMilliseconds, lessThan(1000));
      await expectLater(
        microphone.play(),
        throwsA(
          isA<PlatformException>().having(
            (error) => error.code,
            'code',
            'empty',
          ),
        ),
      );
    }

    // Runner backgrounds the real Activity here; this tests native onPause,
    // independently of Flutter's widget lifecycle cleanup.
    await tester.pumpWidget(const SizedBox.shrink());
    await microphone.clear();
    final backgroundCapture = microphone.capture();
    final backgroundCancelled = expectLater(
      backgroundCapture,
      throwsA(
        isA<PlatformException>().having(
          (error) => error.code,
          'code',
          'cancelled',
        ),
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 150));
    // ignore: avoid_print
    print('AUDIO_BACKGROUND_WAIT');
    await backgroundCancelled.timeout(const Duration(seconds: 10));
    // ignore: avoid_print
    print('AUDIO_BACKGROUND_CANCELLED');
    final resumeDeadline = DateTime.now().add(const Duration(seconds: 10));
    while (true) {
      try {
        await microphone.play();
        fail('Background cancellation retained a playable clip.');
      } on PlatformException catch (error) {
        if (error.code == 'empty') break;
        expect(error.code, 'background');
        expect(DateTime.now().isBefore(resumeDeadline), isTrue);
        await Future<void>.delayed(const Duration(milliseconds: 100));
      }
    }
    expect(tester.takeException(), isNull);
  });
}
