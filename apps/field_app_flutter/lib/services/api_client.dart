import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/session_state.dart';

abstract class SessionApi {
  Future<SessionStateModel> fetchSession({SessionMode? mode});
  Future<SessionStateModel> fetchMockScene(SessionMode mode);
}

class ApiClient implements SessionApi {
  ApiClient({String? baseUrl}) : _baseUrl = baseUrl ?? _defaultBaseUrl();

  final String _baseUrl;

  @override
  Future<SessionStateModel> fetchSession({SessionMode? mode}) async {
    final query = <String, String>{};
    if (mode != null) {
      query['mode'] = mode.apiValue;
    }
    final response = await _readJson(
      Uri.parse('$_baseUrl/v1/session').replace(queryParameters: query.isEmpty ? null : query),
    );
    return SessionStateModel.fromJson(response);
  }

  @override
  Future<SessionStateModel> fetchMockScene(SessionMode mode) async {
    final response = await _readJson(
      Uri.parse('$_baseUrl/v1/mock/scene').replace(queryParameters: <String, String>{'mode': mode.apiValue}),
    );
    return SessionStateModel.fromJson(response['session'] as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> _readJson(Uri uri) async {
    final client = HttpClient();
    try {
      final request = await client.getUrl(uri);
      final response = await request.close();
      final payload = await response.transform(utf8.decoder).join();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('Request failed with status ${response.statusCode}', uri: uri);
      }
      return jsonDecode(payload) as Map<String, dynamic>;
    } finally {
      client.close(force: true);
    }
  }

  static String _defaultBaseUrl() {
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }
}
