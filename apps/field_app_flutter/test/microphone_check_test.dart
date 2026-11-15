import 'dart:async';
import 'dart:typed_data';

import 'package:field_app_flutter/features/audio/microphone_check_screen.dart';
import 'package:field_app_flutter/services/microphone_check.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

Map<Object?, Object?> response(List<int> values, {bool silenced = false}) {
  final bytes = ByteData(values.length * 2);
  for (var i = 0; i < values.length; i++) {
    bytes.setInt16(i * 2, values[i], Endian.little);
  }
  return {
    'pcm': bytes.buffer.asUint8List(),
    'sampleRate': 16000,
    'frames': values.length,
    'elapsedMs': 3000,
    'inputType': 15,
    'inputName': 'Test mic',
    'silenced': silenced,
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'PCM metrics account for signed samples, digital silence and clipping',
    () {
      final loud = MicrophoneClip.fromMap(response([-32768, 32767]));
      expect(loud.peakDbfs, 0);
      expect(loud.rmsDbfs, closeTo(0, 0.001));
      expect(loud.clippedFraction, 1);
      final quiet = MicrophoneClip.fromMap(response([0, 0]));
      expect(quiet.hasSignal, isFalse);
      expect(quiet.rmsDbfs, -120);
      expect(
        MicrophoneClip.fromMap(response([1000, -1000], silenced: true))
            .hasSignal,
        isFalse,
      );
      loud.discard();
      expect(loud.pcm.every((value) => value == 0), isTrue);
      expect(
        () => MicrophoneClip.fromMap(response([1])..['frames'] = 2),
        throwsFormatException,
      );
    },
  );

  test('native read-only PCM is copied into owned, discardable memory', () {
    final values = response([1024, -1024]);
    values['pcm'] = (values['pcm'] as Uint8List).asUnmodifiableView();
    final clip = MicrophoneClip.fromMap(values);
    clip.discard();
    expect(clip.pcm.every((value) => value == 0), isTrue);
  });

  Future<void> mount(
    WidgetTester tester,
    Future<Object?> Function(MethodCall) handler,
  ) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(MicrophoneCheck.channel, handler);
    await tester.pumpWidget(const MaterialApp(home: MicrophoneCheckScreen()));
    await tester.pumpAndSettle();
  }

  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(MicrophoneCheck.channel, null),
  );

  testWidgets('permission denial never starts capture', (tester) async {
    final calls = <String>[];
    await mount(tester, (call) async {
      calls.add(call.method);
      return call.method == 'clear' ? null : false;
    });
    await tester.tap(find.text('Enable microphone'));
    await tester.pumpAndSettle();
    expect(find.textContaining('permission was denied'), findsOneWidget);
    expect(calls, isNot(contains('capture')));
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('discard invalidates a late capture result and never autoplays', (
    tester,
  ) async {
    final pending = Completer<Object?>();
    final calls = <String>[];
    await mount(tester, (call) async {
      calls.add(call.method);
      if (call.method == 'permissionStatus') return true;
      if (call.method == 'capture') return pending.future;
      return null;
    });
    await tester.tap(find.text('Record 3 seconds'));
    await tester.pump();
    await tester.tap(find.text('Stop and discard'));
    await tester.pumpAndSettle();
    final late = response([1024, -1024]);
    pending.complete(late);
    await tester.pumpAndSettle();
    expect(find.text('Clip discarded.'), findsOneWidget);
    expect(calls, isNot(contains('play')));
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('backgrounding discards captured audio and disables playback', (
    tester,
  ) async {
    await mount(tester, (call) async {
      if (call.method == 'permissionStatus') return true;
      if (call.method == 'capture') return response([1024, -1024]);
      return null;
    });
    await tester.tap(find.text('Record 3 seconds'));
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Play clip'),
          )
          .onPressed,
      isNotNull,
    );
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    await tester.pumpAndSettle();
    expect(
      tester
          .widget<OutlinedButton>(
            find.widgetWithText(OutlinedButton, 'Play clip'),
          )
          .onPressed,
      isNull,
    );
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
