import 'dart:ui' show lerpDouble;

import '../conexao/protocolo.dart';
import 'estado_rosto.dart';

/// Parâmetros do rosto, todos contínuos para poderem ser interpolados.
///
/// Distâncias são frações do tamanho do rosto; o pintor converte em pixels.
class Expressao {
  const Expressao({
    this.abertura = 1,
    this.largura = 1,
    this.palpebraInterna = 0,
    this.palpebraExterna = 0,
    this.palpebraInferior = 0,
    this.sorriso = 0.15,
    this.larguraBoca = 1,
    this.bocaAberta = 0,
    this.bocaRedonda = 0,
    this.olharX = 0,
    this.olharY = 0,
    this.inclinacao = 0,
  });

  /// Altura dos olhos (1 = normal; 0 = fechados).
  final double abertura;

  /// Largura dos olhos (1 = normal).
  final double largura;

  /// Pálpebra superior baixando do lado do nariz (bravo), 0 a 1.
  final double palpebraInterna;

  /// Pálpebra superior baixando do lado de fora (triste), 0 a 1.
  final double palpebraExterna;

  /// Pálpebra inferior subindo em arco (olhos sorrindo), 0 a 1.
  final double palpebraInferior;

  /// Curva da boca: 1 sorriso largo, -1 boca para baixo.
  final double sorriso;

  /// Largura da boca (1 = normal).
  final double larguraBoca;

  /// Abertura da boca sem voz (surpreso), 0 a 1. A voz abre além disso.
  final double bocaAberta;

  /// Quanto a boca fica redonda, em "O", 0 a 1.
  final double bocaRedonda;

  /// Direção do olhar própria da expressão, -1 a 1 (y positivo para baixo).
  final double olharX;
  final double olharY;

  /// Inclinação da cabeça, em radianos.
  final double inclinacao;

  static const neutra = Expressao();

  static Expressao daEmocao(Emocao emocao) => switch (emocao) {
    Emocao.neutro => neutra,
    Emocao.feliz => const Expressao(
      abertura: 0.95,
      palpebraInferior: 0.5,
      sorriso: 0.85,
      larguraBoca: 1.1,
    ),
    Emocao.triste => const Expressao(
      abertura: 0.8,
      palpebraExterna: 0.5,
      sorriso: -0.6,
      larguraBoca: 0.85,
      olharY: 0.35,
      inclinacao: -0.04,
    ),
    Emocao.surpreso => const Expressao(
      abertura: 1.25,
      largura: 1.05,
      sorriso: 0,
      larguraBoca: 0.55,
      bocaAberta: 0.55,
      bocaRedonda: 1,
    ),
    Emocao.pensativo => const Expressao(
      abertura: 0.8,
      palpebraExterna: 0.2,
      sorriso: -0.1,
      larguraBoca: 0.65,
      olharX: -0.55,
      olharY: -0.5,
      inclinacao: 0.06,
    ),
    Emocao.bravo => const Expressao(
      abertura: 0.85,
      palpebraInterna: 0.55,
      sorriso: -0.45,
      larguraBoca: 0.8,
    ),
  };

  /// Expressão-alvo para o estado com a emoção sobreposta.
  ///
  /// [esperandoNome] (modo palavra, ocioso com o microfone aberto) deixa o
  /// rosto relaxado, com as pálpebras um pouco baixas, para contrastar com o
  /// rosto atento de quando está conversando.
  static Expressao para(
    EstadoRosto estado,
    Emocao emocao, {
    bool esperandoNome = false,
  }) {
    final base = daEmocao(emocao);
    return switch (estado) {
      EstadoRosto.ocioso when esperandoNome => base.copiar(
        abertura: base.abertura * 0.88,
      ),
      EstadoRosto.ocioso || EstadoRosto.falando => base,
      // Atento (conversando): olhos mais abertos e largos, voltados para
      // quem fala.
      EstadoRosto.ouvindo => base.copiar(
        abertura: base.abertura * 1.15,
        largura: base.largura * 1.04,
        olharX: base.olharX * 0.2,
        olharY: base.olharY * 0.2,
      ),
      // Olha para cima e para o lado, com os olhos meio apertados.
      EstadoRosto.pensando => base.copiar(
        abertura: base.abertura * 0.85,
        larguraBoca: base.larguraBoca * 0.8,
        olharX: base.olharX == 0 ? 0.55 : base.olharX,
        olharY: base.olharY == 0 ? -0.55 : base.olharY,
        inclinacao: base.inclinacao == 0 ? -0.05 : base.inclinacao,
      ),
      // Dormindo: olhos fechados, boca pequena, sem emoção.
      EstadoRosto.desconectado => const Expressao(
        abertura: 0.06,
        sorriso: 0,
        larguraBoca: 0.5,
        olharY: 0.3,
      ),
    };
  }

  Expressao copiar({
    double? abertura,
    double? largura,
    double? larguraBoca,
    double? olharX,
    double? olharY,
    double? inclinacao,
  }) => Expressao(
    abertura: abertura ?? this.abertura,
    largura: largura ?? this.largura,
    palpebraInterna: palpebraInterna,
    palpebraExterna: palpebraExterna,
    palpebraInferior: palpebraInferior,
    sorriso: sorriso,
    larguraBoca: larguraBoca ?? this.larguraBoca,
    bocaAberta: bocaAberta,
    bocaRedonda: bocaRedonda,
    olharX: olharX ?? this.olharX,
    olharY: olharY ?? this.olharY,
    inclinacao: inclinacao ?? this.inclinacao,
  );

  static Expressao lerp(Expressao a, Expressao b, double t) {
    double l(double x, double y) => lerpDouble(x, y, t)!;
    return Expressao(
      abertura: l(a.abertura, b.abertura),
      largura: l(a.largura, b.largura),
      palpebraInterna: l(a.palpebraInterna, b.palpebraInterna),
      palpebraExterna: l(a.palpebraExterna, b.palpebraExterna),
      palpebraInferior: l(a.palpebraInferior, b.palpebraInferior),
      sorriso: l(a.sorriso, b.sorriso),
      larguraBoca: l(a.larguraBoca, b.larguraBoca),
      bocaAberta: l(a.bocaAberta, b.bocaAberta),
      bocaRedonda: l(a.bocaRedonda, b.bocaRedonda),
      olharX: l(a.olharX, b.olharX),
      olharY: l(a.olharY, b.olharY),
      inclinacao: l(a.inclinacao, b.inclinacao),
    );
  }
}
