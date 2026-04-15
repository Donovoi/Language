import 'dart:convert';
import 'dart:io';

class ApiClient {
  ApiClient({Uri? baseUri}) : _baseUri = baseUri ?? Uri.parse('http://127.0.0.1:8000');

  final Uri _baseUri;

  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, String>? queryParameters,
  }) async {
    final client = HttpClient();
    try {
      final request = await client.getUrl(
        _baseUri.replace(path: path, queryParameters: queryParameters),
      );
      final response = await request.close();
      final body = await response.transform(utf8.decoder).join();

      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('Request failed with status ${response.statusCode}', uri: request.uri);
      }

      return jsonDecode(body) as Map<String, dynamic>;
    } finally {
      client.close(force: true);
    }
  }
}
