import 'dart:math';

import 'package:flutter/rendering.dart';

import 'animador.dart';
import 'estado_rosto.dart';
import 'expressao.dart';

/// Desenha o rosto (dois olhos e uma boca, com brilho) a partir do
/// [AnimadorRosto]. Repinta a cada quadro do animador.
class PintorRosto extends CustomPainter {
  PintorRosto(this.animador) : super(repaint: animador);

  final AnimadorRosto animador;

  @override
  void paint(Canvas canvas, Size size) {
    final a = animador;
    final x = a.expressao;
    // Escala do rosto: deixa margem para a boca aberta e para a legenda,
    // em paisagem e em retrato. Um pouco acima do centro da tela.
    final s = min(size.width * 0.8, size.height * 1.3);
    final centro = size.center(Offset.zero) - Offset(0, 0.03 * s);

    // Respiração: sobe e desce bem devagar quando está parado.
    final parado =
        a.estado == EstadoRosto.ocioso || a.estado == EstadoRosto.desconectado;
    final respira = parado ? sin(a.tempo * 2 * pi / 4.5) * 0.006 * s : 0.0;

    final olharX = (x.olharX + a.olharX).clamp(-1.0, 1.0);
    final olharY = (x.olharY + a.olharY).clamp(-1.0, 1.0);
    final desvio = Offset(olharX * 0.07 * s, olharY * 0.05 * s);

    final cor = Color.lerp(a.cor, const Color(0xFFFFFFFF), 0.2)!;
    final brilho = Paint()
      ..color = cor.withValues(alpha: 0.5)
      ..maskFilter = MaskFilter.blur(BlurStyle.normal, s * 0.025);
    final solido = Paint()..color = cor;

    canvas
      ..save()
      ..translate(centro.dx, centro.dy + respira)
      ..rotate(x.inclinacao);

    for (final lado in const [-1.0, 1.0]) {
      final olho = _olho(Offset(lado * 0.19 * s, -0.07 * s) + desvio, lado, s);
      canvas
        ..drawPath(olho, brilho)
        ..drawPath(olho, solido);
    }

    // A boca acompanha o olhar só um pouco, para dar profundidade.
    final boca = _boca(Offset(desvio.dx * 0.45, 0.2 * s + desvio.dy * 0.4), s);
    final espessura = s * 0.022;
    canvas
      ..drawPath(boca, brilho)
      ..drawPath(
        boca,
        Paint.from(brilho)
          ..style = PaintingStyle.stroke
          ..strokeWidth = espessura
          ..strokeJoin = StrokeJoin.round,
      )
      ..drawPath(boca, solido)
      ..drawPath(
        boca,
        Paint.from(solido)
          ..style = PaintingStyle.stroke
          ..strokeWidth = espessura
          ..strokeJoin = StrokeJoin.round,
      )
      ..restore();

    _sinalNome(canvas, size, centro, s);
  }

  /// Sinal discreto de "ouvindo à espera do nome": um pontinho verde abaixo
  /// da boca, pulsando devagar, como a luz de um microfone ligado.
  void _sinalNome(Canvas canvas, Size size, Offset centro, double s) {
    final a = animador;
    if (a.sinalNome < 0.01) return;
    final pulso = 0.5 + 0.5 * sin(a.tempo * 2 * pi / 2.4);
    final alfa = a.sinalNome * (0.3 + 0.35 * pulso);
    final ponto = centro + Offset(0, 0.36 * s);
    final cor = EstadoRosto.ouvindo.cor;
    canvas
      ..drawCircle(
        ponto,
        0.016 * s,
        Paint()
          ..color = cor.withValues(alpha: alfa * 0.6)
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, 0.012 * s),
      )
      ..drawCircle(
        ponto,
        0.008 * s,
        Paint()..color = cor.withValues(alpha: alfa),
      );
  }

  /// Um olho: retângulo bem arredondado, recortado pelas pálpebras.
  /// [lado] é -1 para o olho da esquerda da tela e 1 para o da direita.
  Path _olho(Offset c, double lado, double s) {
    final x = animador.expressao;
    final w = 0.15 * s * x.largura;
    final abertura = x.abertura * (1 + 0.18 * animador.despertar);
    final h = max(0.23 * s * abertura * (1 - animador.piscada), 0.014 * s);
    final caixa = Rect.fromCenter(center: c, width: w, height: h);
    var olho = Path()
      ..addRRect(
        RRect.fromRectAndRadius(caixa, Radius.circular(min(w, h) * 0.45)),
      );

    final interno = c.dx - lado * w / 2; // lado do nariz
    final externo = c.dx + lado * w / 2;

    // Pálpebra superior inclinada: baixa de um lado e passa por cima do
    // canto do outro. Tudo acima da linha é recortado.
    Path? palpebra(double ladoBaixo, double ladoAlto, double quanto) {
      if (quanto <= 0.01) return null;
      final p1 = Offset(ladoBaixo, caixa.top + quanto * h * 0.7);
      final p2 = Offset(ladoAlto, caixa.top - h * 0.05);
      Offset em(double t) => p1 + (p2 - p1) * t;
      final i = em(-0.3), f = em(1.3);
      return Path()
        ..moveTo(i.dx, i.dy)
        ..lineTo(f.dx, f.dy)
        ..lineTo(f.dx, f.dy - 2 * h)
        ..lineTo(i.dx, i.dy - 2 * h)
        ..close();
    }

    for (final corte in [
      palpebra(interno, externo, x.palpebraInterna),
      palpebra(externo, interno, x.palpebraExterna),
    ]) {
      if (corte != null) {
        olho = Path.combine(PathOperation.difference, olho, corte);
      }
    }

    // Pálpebra inferior em arco: deixa o olho em "meia-lua" sorridente.
    if (x.palpebraInferior > 0.01) {
      final topo = caixa.bottom - x.palpebraInferior * h * 0.9;
      final arco = Path()
        ..addOval(Rect.fromLTWH(c.dx - 0.75 * w, topo, 1.5 * w, 1.6 * h));
      olho = Path.combine(PathOperation.difference, olho, arco);
    }
    return olho;
  }

  /// A boca: duas curvas entre os cantos. Fechada vira um traço curvo
  /// (sorriso ou tristeza); aberta, uma forma cheia que pode ficar redonda.
  Path _boca(Offset c, double s) {
    final Expressao x = animador.expressao;
    final w = 0.2 * s * x.larguraBoca;
    final abertura = (x.bocaAberta + animador.boca * (1 - x.bocaAberta * 0.5))
        .clamp(0.0, 1.0);
    final h = abertura * 0.1 * s;
    final curva = x.sorriso * 0.045 * s; // positivo: meio mais baixo
    final r = x.bocaRedonda;
    final k = 0.5 + 0.5 * r; // controles mais abertos deixam a boca redonda
    // Numa cúbica com os dois controles na mesma altura, o meio da curva
    // fica a 3/4 dessa altura.
    final cima = (curva - h * (0.35 + 0.15 * r)) / 0.75;
    final baixo = (curva + h * (0.65 + 0.15 * r)) / 0.75;
    final m = w / 2;
    return Path()
      ..moveTo(c.dx - m, c.dy)
      ..cubicTo(
        c.dx - m * k,
        c.dy + cima,
        c.dx + m * k,
        c.dy + cima,
        c.dx + m,
        c.dy,
      )
      ..cubicTo(
        c.dx + m * k,
        c.dy + baixo,
        c.dx - m * k,
        c.dy + baixo,
        c.dx - m,
        c.dy,
      )
      ..close();
  }

  @override
  bool shouldRepaint(PintorRosto antigo) => antigo.animador != animador;
}
