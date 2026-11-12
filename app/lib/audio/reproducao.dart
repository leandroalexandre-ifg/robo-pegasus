import 'dart:collection';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';

/// Toca em fluxo o PCM 16 bits mono que chega do servidor.
///
/// O servidor manda cada frase mais depressa do que ela toca, então o áudio
/// fica numa fila aqui no Dart e só uns 200 ms vão para o tocador nativo.
/// Assim [descartar] corta a fala quase na hora quando o robô é interrompido.
class Reproducao {
  final _fila = Queue<Uint8List>();
  int _taxa = 0;
  bool _ociosoNativo = true;
  int? _byteSolto; // metade de amostra que chegou num bloco ímpar

  /// Verdadeiro enquanto há áudio tocando ou esperando na fila.
  final tocando = ValueNotifier<bool>(false);

  /// Prepara o tocador para a taxa do servidor. Pode ser chamado de novo
  /// quando a taxa muda (no `hello` ou no `tts_start`).
  Future<void> preparar(int taxa) async {
    if (taxa == _taxa) return;
    descartar();
    if (_taxa != 0) await FlutterPcmSound.release();
    _taxa = taxa;
    await FlutterPcmSound.setLogLevel(LogLevel.error);
    await FlutterPcmSound.setup(sampleRate: taxa, channelCount: 1);
    await FlutterPcmSound.setFeedThreshold(
      _quadros(const Duration(milliseconds: 100)),
    );
    FlutterPcmSound.setFeedCallback(_aoPedirMais);
    _ociosoNativo = true;
  }

  /// Põe um bloco de PCM na fila e começa a tocar se estava parado.
  void tocar(Uint8List pcm) {
    if (_taxa == 0 || pcm.isEmpty) return;
    var dados = pcm;
    if (_byteSolto != null) {
      dados = Uint8List(pcm.length + 1)
        ..[0] = _byteSolto!
        ..setRange(1, pcm.length + 1, pcm);
      _byteSolto = null;
    }
    if (dados.length.isOdd) {
      _byteSolto = dados.last;
      dados = Uint8List.sublistView(dados, 0, dados.length - 1);
    }
    if (dados.isEmpty) return;
    _fila.add(dados);
    tocando.value = true;
    if (_ociosoNativo) _alimentar();
  }

  /// Joga fora o áudio que ainda não foi para o tocador.
  void descartar() {
    _fila.clear();
    _byteSolto = null;
    if (_ociosoNativo) tocando.value = false;
  }

  Future<void> liberar() async {
    descartar();
    FlutterPcmSound.setFeedCallback(null);
    if (_taxa != 0) await FlutterPcmSound.release();
    _taxa = 0;
  }

  void _aoPedirMais(int quadrosRestantes) {
    if (_fila.isNotEmpty) {
      _alimentar();
    } else if (quadrosRestantes == 0) {
      _ociosoNativo = true;
      tocando.value = false;
    }
  }

  /// Manda uns 200 ms da fila para o tocador nativo.
  void _alimentar() {
    if (_fila.isEmpty) return;
    final alvo = _quadros(const Duration(milliseconds: 200)) * 2;
    final lote = BytesBuilder(copy: false);
    while (_fila.isNotEmpty && lote.length < alvo) {
      final bloco = _fila.removeFirst();
      lote.add(bloco);
    }
    _ociosoNativo = false;
    // Cópia com buffer do tamanho exato: o plugin envia `bytes.buffer` inteiro
    // e ignoraria o deslocamento e o tamanho de uma view.
    final bytes = Uint8List.fromList(lote.takeBytes());
    FlutterPcmSound.feed(PcmArrayInt16(bytes: bytes.buffer.asByteData()));
  }

  int _quadros(Duration d) => _taxa * d.inMilliseconds ~/ 1000;
}
