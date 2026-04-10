import 'package:field_app_flutter/features/session/session_screen.dart';
import 'package:field_app_flutter/services/mock_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('renders mock speakers and updates mode selection', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: SessionScreen(repository: MockRepository()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('Language Field Console'), findsOneWidget);
    expect(find.text('Alex'), findsOneWidget);
    expect(find.text('Focus'), findsWidgets);

    await tester.tap(find.text('Locked').last);
    await tester.pumpAndSettle();

    expect(find.text('Mina'), findsOneWidget);
    expect(find.text('speaker-02'), findsOneWidget);
  });
}
