import 'dart:async';
import 'dart:io' show TlsException;
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config/config.dart';
import 'protocolo.dart';
import 'tls.dart';

/// Cliente WebSocket do robô: faz o `hello`, mantém o `ping` e reconecta
/// sozinho com espera crescente quando a conexão cai.
class Cliente {
  Cliente(this._config);

  Config _config;
  IOWebSocketChannel? _canal;
  Timer? _timerPing;
  bool _parado = true;
  Completer<void>? _espera;

  final _mensagens = StreamController<MensagemServidor>.broadcast();
  final _audio = StreamController<Uint8List>.broadcast();

  /// Verdadeiro depois que o servidor respondeu o `hello`.
  final conectado = ValueNotifier<bool>(false);

  /// Último motivo de desconexão, em português, para exibir no rosto.
  final motivo = ValueNotifier<String?>(null);

  /// Taxa do áudio que o servidor envia, informada no `hello`.
  int taxaSaida = 22050;

  /// Modo de ativação informado no `hello` da sessão atual.
  Ativacao ativacao = Ativacao.toque;

  Stream<MensagemServidor> get mensagens => _mensagens.stream;
  Stream<Uint8List> get audio => _audio.stream;

  static const _esperaMinima = Duration(seconds: 1);
  static const _esperaMaxima = Duration(seconds: 30);
  static const _limiteHello = Duration(seconds: 10);

  void iniciar() {
    if (!_parado) return;
    _parado = false;
    unawaited(_laco());
  }

  /// Troca o endereço ou o token e reconecta na hora.
  void trocarConfig(Config config) {
    _config = config;
    unawaited(_canal?.sink.close(1000));
    _acordar();
  }

  Future<void> parar() async {
    _parado = true;
    _acordar();
    await _canal?.sink.close(1000);
  }

  void enviarTexto(String json) {
    if (conectado.value) _canal?.sink.add(json);
  }

  void enviarAudio(Uint8List pcm) {
    if (conectado.value) _canal?.sink.add(pcm);
  }

  Future<void> _laco() async {
    var espera = _esperaMinima;
    while (!_parado) {
      final recebeuHello = await _conectarUmaVez();
      if (_parado) break;
      if (recebeuHello) espera = _esperaMinima;
      await _aguardar(espera);
      espera = Duration(
        milliseconds: min(
          espera.inMilliseconds * 2,
          _esperaMaxima.inMilliseconds,
        ),
      );
    }
  }

  /// Abre uma conexão e só retorna quando ela fecha. Devolve se o `hello` do
  /// servidor chegou, para zerar a espera da reconexão.
  Future<bool> _conectarUmaVez() async {
    final fim = Completer<void>();
    var recebeuHello = false;
    final IOWebSocketChannel canal;
    try {
      // O customClient leva a CA interna para o wss://; no ws:// do túnel
      // ele é só um HttpClient comum.
      canal = IOWebSocketChannel.connect(
        Uri.parse(_config.url.trim()),
        connectTimeout: const Duration(seconds: 5),
        customClient: Tls.novoCliente(),
      );
      _canal = canal;
      await canal.ready;
    } catch (e) {
      debugPrint('[Cliente] falha ao conectar em ${_config.url}: $e');
      final interna = e is WebSocketChannelException ? e.inner : e;
      motivo.value = interna is TlsException || e is TlsException
          ? 'Certificado do servidor não aceito'
          : 'Servidor não encontrado';
      _canal = null;
      return false;
    }

    final limite = Timer(_limiteHello, () {
      if (!recebeuHello) unawaited(canal.sink.close(1000));
    });

    final assinatura = canal.stream.listen(
      (quadro) {
        if (quadro is String) {
          final MensagemServidor? msg;
          try {
            msg = MensagemServidor.decodificar(quadro);
          } on FormatException catch (e) {
            debugPrint('[Cliente] JSON inválido do servidor: $e');
            return;
          }
          if (msg is HelloServidor) {
            recebeuHello = true;
            taxaSaida = msg.taxaSaida;
            ativacao = msg.ativacao;
            motivo.value = null;
            conectado.value = true;
            _iniciarPing();
            debugPrint(
              '[Cliente] sessão ${msg.sessionId}, saída ${msg.taxaSaida} Hz, '
              'ativação ${msg.ativacao.name}',
            );
          }
          if (msg != null) _mensagens.add(msg);
        } else if (quadro is List<int>) {
          _audio.add(quadro is Uint8List ? quadro : Uint8List.fromList(quadro));
        }
      },
      onError: (Object e) => debugPrint('[Cliente] erro na conexão: $e'),
      onDone: () {
        if (!fim.isCompleted) fim.complete();
      },
      cancelOnError: true,
    );

    canal.sink.add(
      helloTablet(token: _config.token, deviceId: _config.deviceId),
    );
    await fim.future;

    limite.cancel();
    await assinatura.cancel();
    _timerPing?.cancel();
    _canal = null;
    conectado.value = false;
    motivo.value = switch (canal.closeCode) {
      fechaToken => 'Token inválido',
      fechaProtocolo => 'Erro de protocolo',
      fechaTempo => 'Tempo esgotado',
      _ => 'Conexão perdida',
    };
    debugPrint(
      '[Cliente] conexão fechada (${canal.closeCode} ${canal.closeReason})',
    );
    return recebeuHello;
  }

  void _iniciarPing() {
    _timerPing?.cancel();
    _timerPing = Timer.periodic(intervaloPing, (_) => enviarTexto(ping()));
  }

  Future<void> _aguardar(Duration tempo) {
    final espera = _espera = Completer<void>();
    final timer = Timer(tempo, _acordar);
    return espera.future.whenComplete(timer.cancel);
  }

  void _acordar() {
    final espera = _espera;
    if (espera != null && !espera.isCompleted) espera.complete();
  }
}
