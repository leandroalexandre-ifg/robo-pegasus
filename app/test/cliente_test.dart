import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/config/config.dart';
import 'package:robo_pegasus/conexao/cliente.dart';
import 'package:robo_pegasus/conexao/protocolo.dart';

/// Servidor WebSocket local que recebe o `hello` e fecha com [codigo].
/// [conexoes] conta as tentativas do cliente.
class _Servidor {
  _Servidor._(this._http);

  final HttpServer _http;
  int conexoes = 0;
  int codigo = 1000;

  static Future<_Servidor> subir() async {
    final s = _Servidor._(await HttpServer.bind('127.0.0.1', 0));
    s._http.listen((pedido) async {
      s.conexoes++;
      final ws = await WebSocketTransformer.upgrade(pedido);
      await ws.first; // o hello
      await ws.close(s.codigo);
    });
    return s;
  }

  Config get config => Config(
    url: 'ws://127.0.0.1:${_http.port}/ws',
    token: 't',
    deviceId: 'teste',
  );

  Future<void> descer() => _http.close(force: true);
}

void main() {
  late _Servidor servidor;
  late Cliente cliente;

  setUp(() async => servidor = await _Servidor.subir());
  tearDown(() async {
    await cliente.parar();
    await servidor.descer();
  });

  Future<void> esperar(int ms) =>
      Future<void>.delayed(Duration(milliseconds: ms));

  test('queda comum: reconecta sozinho', () async {
    cliente = Cliente(servidor.config)..iniciar();
    await esperar(2500); // 1ª tentativa, espera de 1 s, 2ª tentativa
    expect(servidor.conexoes, greaterThanOrEqualTo(2));
    expect(cliente.motivo.value, 'Conexão perdida');
  });

  for (final (codigo, texto) in [
    (fechaOutroAparelho, 'Conectado em outro aparelho'),
    (fechaToken, 'Token inválido'),
  ]) {
    test('$codigo: não reconecta sozinho, só a pedido', () async {
      servidor.codigo = codigo;
      cliente = Cliente(servidor.config)..iniciar();
      await esperar(2500);
      expect(servidor.conexoes, 1);
      expect(cliente.motivo.value, texto);

      cliente.trocarConfig(servidor.config); // toque na tela
      await esperar(500);
      expect(servidor.conexoes, 2);
    });
  }
}
