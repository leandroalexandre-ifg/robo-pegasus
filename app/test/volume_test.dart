import 'dart:math';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/audio/volume.dart';

/// PCM com [ms] milissegundos de amplitude constante [amp] (0 a 1).
Uint8List _pcm(int taxa, int ms, double amp) {
  final n = taxa * ms ~/ 1000;
  final d = ByteData(n * 2);
  for (var i = 0; i < n; i++) {
    d.setInt16(i * 2, (amp * 32767).round(), Endian.little);
  }
  return d.buffer.asUint8List();
}

void main() {
  const taxa = 16000;
  const ms = Duration(milliseconds: 1);

  test('o nível aparece só depois do início mais o atraso', () {
    final env = EnvelopeVoz()..agendar(_pcm(taxa, 100, 0.5), taxa, ms * 1000);
    expect(env.nivel(ms * 1040), 0); // antes de 1000 + 50 ms
    expect(env.nivel(ms * 1060), closeTo(0.5, 0.001));
  });

  test('segue lotes seguidos e zera depois do fim', () {
    final env = EnvelopeVoz()
      ..agendar(_pcm(taxa, 100, 0.2), taxa, Duration.zero)
      ..agendar(_pcm(taxa, 100, 0.8), taxa, ms * 100);
    expect(env.nivel(ms * 90), closeTo(0.2, 0.001));
    expect(env.nivel(ms * 190), closeTo(0.8, 0.001));
    expect(env.nivel(ms * 260), 0);
  });

  test('limpar descarta o que estava agendado', () {
    final env = EnvelopeVoz()
      ..agendar(_pcm(taxa, 100, 0.5), taxa, Duration.zero);
    env.limpar();
    expect(env.nivel(ms * 80), 0);
  });

  test('abertura em decibéis', () {
    expect(aberturaPorRms(0), 0);
    expect(aberturaPorRms(pow(10, -50 / 20).toDouble()), 0);
    expect(aberturaPorRms(pow(10, -12 / 20).toDouble()), closeTo(1, 1e-9));
    expect(aberturaPorRms(pow(10, -28.5 / 20).toDouble()), closeTo(0.5, 1e-9));
  });
}
