import 'dart:collection';
import 'dart:math';
import 'dart:typed_data';

/// Volume (RMS) do áudio da resposta ao longo do tempo, para a boca.
///
/// Cada lote entregue ao tocador é dividido em janelas de 20 ms e agendado
/// para o instante em que vai tocar. [nivel] devolve o RMS que está saindo
/// do alto-falante agora, com [atraso] extra para compensar a latência dele.
class EnvelopeVoz {
  EnvelopeVoz({
    this.atraso = const Duration(milliseconds: 50),
    this.janela = const Duration(milliseconds: 20),
  });

  final Duration atraso;
  final Duration janela;
  final _pontos = Queue<_Ponto>();

  /// Agenda o PCM 16 bits mono [pcm], que começa a tocar em [inicio].
  void agendar(Uint8List pcm, int taxa, Duration inicio) {
    final dados = ByteData.sublistView(pcm);
    final total = pcm.length ~/ 2;
    final porJanela = max(1, taxa * janela.inMicroseconds ~/ 1000000);
    for (var i = 0; i < total; i += porJanela) {
      final n = min(porJanela, total - i);
      var soma = 0.0;
      for (var j = i; j < i + n; j++) {
        final a = dados.getInt16(j * 2, Endian.little) / 32768.0;
        soma += a * a;
      }
      _pontos.add(
        _Ponto(
          inicioUs: inicio.inMicroseconds + i * 1000000 ~/ taxa,
          fimUs: inicio.inMicroseconds + (i + n) * 1000000 ~/ taxa,
          rms: sqrt(soma / n),
        ),
      );
    }
  }

  /// RMS (0 a 1) que deve aparecer na boca em [agora].
  double nivel(Duration agora) {
    final t = agora.inMicroseconds - atraso.inMicroseconds;
    while (_pontos.isNotEmpty && _pontos.first.fimUs <= t) {
      _pontos.removeFirst();
    }
    if (_pontos.isEmpty || _pontos.first.inicioUs > t) return 0;
    return _pontos.first.rms;
  }

  void limpar() => _pontos.clear();
}

class _Ponto {
  const _Ponto({
    required this.inicioUs,
    required this.fimUs,
    required this.rms,
  });
  final int inicioUs;
  final int fimUs;
  final double rms;
}

/// Converte o RMS em abertura da boca (0 a 1), em escala de decibéis:
/// -45 dBFS ou menos fecha; -12 dBFS ou mais abre tudo.
double aberturaPorRms(double rms) {
  if (rms <= 0) return 0;
  final db = 20 * log(rms) / ln10;
  return ((db + 45) / 33).clamp(0.0, 1.0);
}
