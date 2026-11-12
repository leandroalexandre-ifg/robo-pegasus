import 'dart:async';
import 'dart:typed_data';

import 'package:record/record.dart';

import '../conexao/protocolo.dart';

/// Capta o microfone em PCM 16 kHz mono e entrega blocos de 20 ms (640 bytes).
class Captura {
  final _gravador = AudioRecorder();
  StreamSubscription<Uint8List>? _assinatura;
  final _sobra = BytesBuilder(copy: false);

  bool _querAtiva = false;

  /// Verdadeiro do pedido de [iniciar] até [parar].
  bool get ativa => _querAtiva;

  /// Pede a permissão do microfone, se ainda não foi dada.
  Future<bool> pedirPermissao() => _gravador.hasPermission();

  /// Começa a captar. [aoBloco] recebe cada bloco de 20 ms.
  Future<bool> iniciar(void Function(Uint8List bloco) aoBloco) async {
    if (_querAtiva) return true;
    _querAtiva = true;
    if (!await _gravador.hasPermission()) {
      _querAtiva = false;
      return false;
    }
    _sobra.clear();
    final fluxo = await _gravador.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: taxaEntrada,
        numChannels: 1,
        androidConfig: AndroidRecordConfig(
          audioSource: AndroidAudioSource.voiceRecognition,
        ),
      ),
    );
    if (!_querAtiva) {
      // parar() foi chamado enquanto o microfone abria.
      await _gravador.stop();
      return false;
    }
    _assinatura = fluxo.listen((dados) {
      _sobra.add(dados);
      if (_sobra.length < bytesPorBloco) return;
      final tudo = _sobra.takeBytes();
      final inteiros = tudo.length ~/ bytesPorBloco * bytesPorBloco;
      for (var i = 0; i < inteiros; i += bytesPorBloco) {
        aoBloco(Uint8List.sublistView(tudo, i, i + bytesPorBloco));
      }
      if (inteiros < tudo.length) {
        _sobra.add(Uint8List.sublistView(tudo, inteiros));
      }
    });
    return true;
  }

  /// Para de captar e descarta o pedaço de bloco que sobrou.
  Future<void> parar() async {
    _querAtiva = false;
    final assinatura = _assinatura;
    if (assinatura == null) return;
    _assinatura = null;
    await assinatura.cancel();
    await _gravador.stop();
    _sobra.clear();
  }

  Future<void> liberar() async {
    await parar();
    await _gravador.dispose();
  }
}
