import 'package:field_app_flutter/features/session/session_screen.dart';
import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/services/api_client.dart';
import 'package:field_app_flutter/services/mock_repository.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

// Run through scripts/smoke_android.py: this test mutates its disposable gateway.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('gateway connection, controls, and streamed captions',
      (tester) async {
    const endpoint = String.fromEnvironment('FIELD_APP_API_BASE_URL');
    expect(endpoint, isNotEmpty,
        reason: 'Use the isolated Android smoke runner.');
    final api = ApiClient();
    final repository = MockRepository(api: api);
    addTearDown(repository.dispose);

    await api.resetSession(SessionMode.focus);
    await tester
        .pumpWidget(MaterialApp(home: SessionScreen(repository: repository)));
    await waitFor(
        tester, () => !repository.isLoading && repository.isStreaming);
    expect(repository.errorMessage, isNull);
    expect(find.text('Live updates connected'), findsOneWidget);

    await tester.tap(find.widgetWithText(ChoiceChip, 'Crowd'));
    await waitFor(
        tester,
        () =>
            !repository.isLoading &&
            repository.session.mode == SessionMode.crowd);
    expect((await api.fetchSession()).mode, SessionMode.crowd);
    expect(find.text('Crowd mode'), findsOneWidget);

    final speaker = repository.session.speakers.first;
    final lock = find.byTooltip('Lock speaker ${speaker.displayName}');
    await tester.ensureVisible(lock);
    await tester.tap(lock);
    await waitFor(
        tester,
        () =>
            !repository.isLoading &&
            repository.session.speakers
                .firstWhere((item) => item.speakerId == speaker.speakerId)
                .isLocked);
    expect(
        (await api.fetchSession())
            .speakers
            .firstWhere((item) => item.speakerId == speaker.speakerId)
            .isLocked,
        isTrue);
    await tester.tap(find.byTooltip('Unlock speaker ${speaker.displayName}'));
    await waitFor(
        tester,
        () =>
            !repository.isLoading &&
            !repository.session.speakers
                .firstWhere((item) => item.speakerId == speaker.speakerId)
                .isLocked);

    // Start from another client, so the console can only learn about new captions
    // over SSE. A local fallback or an optimistic "connected" badge cannot pass.
    final captions = repository.session.speakers
        .map((item) => item.translatedCaption)
        .toList();
    await api.startMockLiveIngest(mode: SessionMode.crowd, intervalMs: 200);
    try {
      await waitFor(
          tester,
          () => repository.session.speakers.any((item) =>
              item.translatedCaption != null &&
              !captions.contains(item.translatedCaption)));
      expect(repository.errorMessage, isNull);
      expect(repository.isStreaming, isTrue);
    } finally {
      await api.stopMockLiveIngest();
    }

    await tester.tap(find.byTooltip('Reset session'));
    await waitFor(tester, () => !repository.isLoading);
    expect(repository.errorMessage, isNull);
    expect((await api.fetchSession()).speakers.every((item) => !item.isLocked),
        isTrue);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}

Future<void> waitFor(WidgetTester tester, bool Function() ready) async {
  final deadline = DateTime.now().add(const Duration(seconds: 20));
  do {
    await tester.pump(const Duration(milliseconds: 100));
    if (ready()) return;
  } while (DateTime.now().isBefore(deadline));
  fail('Timed out waiting for the gateway-backed console.');
}
