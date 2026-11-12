import 'package:shared_preferences/shared_preferences.dart';

/// Endereço do servidor, token e identificação do tablet.
///
/// Os valores padrão vêm de `--dart-define` na compilação
/// (`PEGASUS_URL`, `PEGASUS_TOKEN`, `PEGASUS_DEVICE_ID`) e podem ser trocados
/// no próprio tablet (toque longo na tela); a escolha fica salva.
class Config {
  const Config({
    required this.url,
    required this.token,
    required this.deviceId,
  });

  final String url;
  final String token;
  final String deviceId;

  static const padrao = Config(
    url: String.fromEnvironment(
      'PEGASUS_URL',
      defaultValue: 'ws://192.168.0.10:8000/ws',
    ),
    token: String.fromEnvironment('PEGASUS_TOKEN'),
    deviceId: String.fromEnvironment(
      'PEGASUS_DEVICE_ID',
      defaultValue: 'tablet-01',
    ),
  );

  static const _chaveUrl = 'servidor_url';
  static const _chaveToken = 'servidor_token';
  static const _chaveDevice = 'device_id';

  static Future<Config> carregar() async {
    final prefs = SharedPreferencesAsync();
    return Config(
      url: await prefs.getString(_chaveUrl) ?? padrao.url,
      token: await prefs.getString(_chaveToken) ?? padrao.token,
      deviceId: await prefs.getString(_chaveDevice) ?? padrao.deviceId,
    );
  }

  Future<void> salvar() async {
    final prefs = SharedPreferencesAsync();
    await prefs.setString(_chaveUrl, url);
    await prefs.setString(_chaveToken, token);
    await prefs.setString(_chaveDevice, deviceId);
  }

  /// Mensagem de erro em português, ou `null` se o endereço for válido.
  static String? validarUrl(String url) {
    final uri = Uri.tryParse(url.trim());
    if (uri == null || !(uri.scheme == 'ws' || uri.scheme == 'wss')) {
      return 'Use um endereço ws:// ou wss://';
    }
    if (uri.host.isEmpty) return 'Falta o endereço do servidor';
    return null;
  }
}
