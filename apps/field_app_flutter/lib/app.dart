import 'package:flutter/material.dart';

import 'features/session/session_screen.dart';
import 'services/mock_repository.dart';

class FieldApp extends StatelessWidget {
  const FieldApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Language Field Console',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF7C8CFF),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF10131A),
        useMaterial3: true,
      ),
      home: SessionScreen(repository: MockRepository()),
    );
  }
}
