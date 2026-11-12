import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../conexao/protocolo.dart';
import 'animador.dart';
import 'estado_rosto.dart';
import 'pintor_rosto.dart';

/// O rosto animado em tela cheia: olhos e boca desenhados quadro a quadro,
/// com a legenda discreta no rodapé.
class Rosto extends StatefulWidget {
  const Rosto({
    super.key,
    required this.estado,
    this.emocao = Emocao.neutro,
    this.nivelVoz,
    this.legenda,
  });

  final EstadoRosto estado;
  final Emocao emocao;

  /// Volume da voz que está tocando (RMS, 0 a 1), lido a cada quadro.
  final double Function()? nivelVoz;
  final String? legenda;

  @override
  State<Rosto> createState() => _RostoState();
}

class _RostoState extends State<Rosto> with SingleTickerProviderStateMixin {
  late final AnimadorRosto _animador = AnimadorRosto(
    nivelVoz: () => widget.nivelVoz?.call() ?? 0,
  );
  late final Ticker _ticker = createTicker(_aoQuadro);
  Duration _ultimo = Duration.zero;

  @override
  void initState() {
    super.initState();
    _animador
      ..estado = widget.estado
      ..emocao = widget.emocao;
    _ticker.start();
  }

  @override
  void didUpdateWidget(Rosto antigo) {
    super.didUpdateWidget(antigo);
    _animador
      ..estado = widget.estado
      ..emocao = widget.emocao;
  }

  void _aoQuadro(Duration agora) {
    final dt = (agora - _ultimo).inMicroseconds / 1e6;
    _ultimo = agora;
    _animador.avancar(dt);
  }

  @override
  void dispose() {
    _ticker.dispose();
    _animador.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        RepaintBoundary(child: CustomPaint(painter: PintorRosto(_animador))),
        Positioned(
          left: 24,
          right: 24,
          bottom: 24,
          child: Text(
            widget.legenda ?? '',
            textAlign: TextAlign.center,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Colors.white38, fontSize: 18),
          ),
        ),
      ],
    );
  }
}
