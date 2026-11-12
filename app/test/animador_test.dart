import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/audio/volume.dart';
import 'package:robo_pegasus/conexao/protocolo.dart';
import 'package:robo_pegasus/rosto/animador.dart';
import 'package:robo_pegasus/rosto/estado_rosto.dart';
import 'package:robo_pegasus/rosto/expressao.dart';

const _dt = 1 / 60;

/// Roda [segundos] a 60 quadros por segundo, chamando [aCada] em cada quadro.
void _rodar(AnimadorRosto a, double segundos, [void Function()? aCada]) {
  for (var i = 0; i < segundos / _dt; i++) {
    a.avancar(_dt);
    aCada?.call();
  }
}

void main() {
  test('pisca de tempos em tempos, de forma irregular', () {
    final a = AnimadorRosto(aleatorio: Random(1))..estado = EstadoRosto.ocioso;
    var piscadas = 0;
    var fechado = false;
    _rodar(a, 60, () {
      if (a.piscada > 0.9 && !fechado) piscadas++;
      fechado = a.piscada > 0.9;
    });
    // Uma a cada 2 a 6 s, com algumas duplas.
    expect(piscadas, inInclusiveRange(10, 35));
  });

  test('desconectado não pisca', () {
    final a = AnimadorRosto(aleatorio: Random(2));
    var maior = 0.0;
    _rodar(a, 20, () => maior = max(maior, a.piscada));
    expect(maior, 0);
  });

  test('o olhar vagueia no ocioso e fica perto do centro ouvindo', () {
    final a = AnimadorRosto(aleatorio: Random(3))..estado = EstadoRosto.ocioso;
    var maior = 0.0;
    _rodar(a, 20, () => maior = max(maior, a.olharX.abs()));
    expect(maior, greaterThan(0.4));

    a.estado = EstadoRosto.ouvindo;
    _rodar(a, 1);
    maior = 0;
    _rodar(a, 20, () => maior = max(maior, a.olharX.abs()));
    expect(maior, lessThan(0.15));
  });

  test('a boca segue a voz só falando', () {
    const rms = 0.1; // -20 dBFS
    final a = AnimadorRosto(aleatorio: Random(4), nivelVoz: () => rms)
      ..estado = EstadoRosto.ouvindo;
    _rodar(a, 1);
    expect(a.boca, 0);

    a.estado = EstadoRosto.falando;
    _rodar(a, 0.5);
    expect(a.boca, closeTo(aberturaPorRms(rms), 0.01));

    a.estado = EstadoRosto.ocioso;
    _rodar(a, 0.5);
    expect(a.boca, lessThan(0.01));
  });

  test('a expressão chega à da emoção', () {
    final a = AnimadorRosto(aleatorio: Random(5))
      ..estado = EstadoRosto.ocioso
      ..emocao = Emocao.feliz;
    _rodar(a, 2);
    expect(
      a.expressao.sorriso,
      closeTo(Expressao.daEmocao(Emocao.feliz).sorriso, 0.01),
    );
    expect(a.cor.toARGB32(), EstadoRosto.ocioso.cor.toARGB32());
  });

  test('sinal de espera do nome só aparece ocioso e some suave', () {
    final a = AnimadorRosto(aleatorio: Random(4))
      ..estado = EstadoRosto.ocioso
      ..esperandoNome = true;
    _rodar(a, 2);
    expect(a.sinalNome, greaterThan(0.95));

    a.estado = EstadoRosto.falando; // o robô fala: o sinal sai
    a.avancar(_dt);
    expect(a.sinalNome, greaterThan(0.9)); // sem sumir de repente
    _rodar(a, 2);
    expect(a.sinalNome, lessThan(0.05));

    a
      ..estado = EstadoRosto.ocioso
      ..esperandoNome = false; // modo toque
    _rodar(a, 2);
    expect(a.sinalNome, lessThan(0.05));
  });
}
