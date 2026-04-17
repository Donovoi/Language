import 'package:field_app_flutter/features/session/session_screen.dart';
import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/services/mock_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

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
}
