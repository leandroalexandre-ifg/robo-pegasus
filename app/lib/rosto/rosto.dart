import 'package:flutter/material.dart';

import 'estado_rosto.dart';

/// Versão mínima do rosto (Fase 2): um círculo que muda de cor por estado.
/// Os olhos e a boca animados chegam na Fase 3.
class Rosto extends StatelessWidget {
  const Rosto({super.key, required this.estado, this.legenda});

  final EstadoRosto estado;
  final String? legenda;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, restricoes) {
        final lado = restricoes.biggest.shortestSide * 0.6;
        return Stack(
          alignment: Alignment.center,
          children: [
            AnimatedContainer(
              duration: const Duration(milliseconds: 250),
              curve: Curves.easeOut,
              width: lado,
              height: lado,
              decoration: BoxDecoration(
                color: estado.cor,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: estado.cor.withValues(alpha: 0.45),
                    blurRadius: lado * 0.25,
                  ),
                ],
              ),
            ),
            Positioned(
              left: 24,
              right: 24,
              bottom: 24,
              child: Text(
                legenda ?? '',
                textAlign: TextAlign.center,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Colors.white38, fontSize: 18),
              ),
            ),
          ],
        );
      },
    );
  }
}
