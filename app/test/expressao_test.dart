import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/conexao/protocolo.dart';
import 'package:robo_pegasus/rosto/estado_rosto.dart';
import 'package:robo_pegasus/rosto/expressao.dart';

void main() {
  test('cada emoção tem uma expressão própria', () {
    final vistas = <String>{};
    for (final e in Emocao.values) {
      final x = Expressao.daEmocao(e);
      vistas.add(
        '${x.abertura} ${x.sorriso} ${x.palpebraInterna} '
        '${x.palpebraExterna} ${x.palpebraInferior} ${x.bocaRedonda}',
      );
    }
    expect(vistas.length, Emocao.values.length);
  });

  test('feliz sorri e triste não', () {
    expect(Expressao.daEmocao(Emocao.feliz).sorriso, greaterThan(0.5));
    expect(Expressao.daEmocao(Emocao.triste).sorriso, lessThan(0));
  });

  test('desconectado fecha os olhos e ignora a emoção', () {
    final x = Expressao.para(EstadoRosto.desconectado, Emocao.feliz);
    expect(x.abertura, lessThan(0.1));
    expect(x.sorriso, 0);
  });

  test('pensando olha para cima, ouvindo olha para a frente', () {
    expect(
      Expressao.para(EstadoRosto.pensando, Emocao.neutro).olharY,
      lessThan(0),
    );
    final ouvindo = Expressao.para(EstadoRosto.ouvindo, Emocao.pensativo);
    expect(ouvindo.olharX.abs(), lessThan(0.2));
    expect(
      ouvindo.abertura,
      greaterThan(Expressao.daEmocao(Emocao.pensativo).abertura),
    );
  });

  test('lerp vai de uma expressão à outra', () {
    const a = Expressao(sorriso: 0, abertura: 1);
    const b = Expressao(sorriso: 1, abertura: 0);
    expect(Expressao.lerp(a, b, 0).sorriso, 0);
    expect(Expressao.lerp(a, b, 1).abertura, 0);
    expect(Expressao.lerp(a, b, 0.5).sorriso, closeTo(0.5, 1e-9));
  });

  test('esperando o nome é relaxado; conversando é atento', () {
    final esperando = Expressao.para(
      EstadoRosto.ocioso,
      Emocao.neutro,
      esperandoNome: true,
    );
    final ocioso = Expressao.para(EstadoRosto.ocioso, Emocao.neutro);
    final ouvindo = Expressao.para(
      EstadoRosto.ouvindo,
      Emocao.neutro,
      esperandoNome: true, // não muda a escuta
    );
    expect(esperando.abertura, lessThan(ocioso.abertura));
    expect(ouvindo.abertura, greaterThan(ocioso.abertura));
    expect(ouvindo.largura, greaterThan(ocioso.largura));
  });
}
