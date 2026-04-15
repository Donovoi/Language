import 'package:flutter/material.dart';

import 'features/session/session_screen.dart';

class FieldApp extends StatelessWidget {
  const FieldApp({super.key});

  @override
  Widget build(BuildContext context) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF5B8CFF),
      brightness: Brightness.dark,
    );

    return MaterialApp(
      title: 'Language Field App',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: colorScheme,
        scaffoldBackgroundColor: const Color(0xFF101418),
        cardTheme: CardThemeData(
          color: const Color(0xFF171D23),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        ),
      ),
      home: const SessionScreen(),
    );
  }
}
