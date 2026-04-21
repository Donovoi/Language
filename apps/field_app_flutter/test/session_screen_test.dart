import 'package:field_app_flutter/features/session/session_screen.dart';
import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/models/speaker.dart';
import 'package:field_app_flutter/services/mock_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_support/fake_session_api.dart';

void main() {
  testWidgets('renders the seeded top speaker lane', (tester) async {
    final repository = MockRepository(
      initialSession: SessionStateModel.fallback(mode: SessionMode.focus),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: SessionScreen(
          repository: repository,
          autoLoad: false,
        ),
      ),
    );

    expect(find.text('Language Field Console'), findsOneWidget);
    expect(find.text('Focus mode'), findsOneWidget);
    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('Primary translation target'), findsOneWidget);
  });

  testWidgets('falls back to the first speaker when no top speaker is set',
      (tester) async {
    final repository = MockRepository(
      initialSession: const SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.focus,
        speakers: <Speaker>[
          Speaker(
            speakerId: 'speaker-a',
            displayName: 'Alice',
            languageCode: 'en',
            priority: 0.9,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.2,
            lastUpdatedUnixMs: 1,
          ),
          Speaker(
            speakerId: 'speaker-b',
            displayName: 'Bruno',
            languageCode: 'pt-BR',
            priority: 0.8,
            active: true,
            isLocked: false,
            frontFacing: false,
            persistenceBonus: 0.1,
            lastUpdatedUnixMs: 2,
          ),
        ],
        topSpeakerId: null,
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: SessionScreen(
          repository: repository,
          autoLoad: false,
        ),
      ),
    );

    expect(find.text('Primary translation target'), findsOneWidget);
    expect(find.text('Queued for translation mix'), findsOneWidget);
  });

  testWidgets('shows an empty state when no speaker lanes are available',
      (tester) async {
    final repository = MockRepository(
      initialSession: const SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.focus,
        speakers: <Speaker>[],
        topSpeakerId: null,
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: SessionScreen(
          repository: repository,
          autoLoad: false,
        ),
      ),
    );

    expect(find.text('No speaker lanes available yet.'), findsOneWidget);
    expect(
      find.text('Refresh the session or switch modes to load a scene.'),
      findsOneWidget,
    );
  });

  testWidgets('surfaces gateway errors after a failed refresh', (tester) async {
    final repository = MockRepository(
      api: FakeSessionApi(
        fetchSessionHandler: (_) async => throw Exception('offline'),
      ),
      initialSession: SessionStateModel.fallback(mode: SessionMode.crowd),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: SessionScreen(
          repository: repository,
          autoLoad: false,
        ),
      ),
    );

    await tester.tap(find.byTooltip('Refresh session'));
    await tester.pumpAndSettle();

    expect(
      find.text('Gateway unavailable. Showing local fallback scene.'),
      findsOneWidget,
    );
    expect(find.text('Crowd mode'), findsOneWidget);
  });
}
