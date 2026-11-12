import 'package:flutter/painting.dart';

import '../conexao/protocolo.dart';

/// Estados do rosto. `desconectado` existe só no app.
enum EstadoRosto {
  ocioso(Color(0xFF4FA3E0)),
  ouvindo(Color(0xFF3FCF7A)),
  pensando(Color(0xFFF2B33D)),
  falando(Color(0xFFB06CE8)),
  desconectado(Color(0xFF5A5F66));

  const EstadoRosto(this.cor);

  /// Cor do círculo na versão mínima (Fase 2).
  final Color cor;
}

/// Decide o que o rosto mostra a partir do que o app sabe.
///
/// - [microfone]: o app está captando e enviando áudio.
/// - [aguardandoEscuta]: o app pediu `listen_start` e o servidor ainda não
///   confirmou com `state "ouvindo"`.
/// - [tocando]: ainda há áudio da resposta tocando ou na fila. O servidor
///   avisa `ocioso` quando termina de enviar, mas o tablet pode continuar
///   falando por alguns segundos.
EstadoRosto estadoExibido({
  required bool conectado,
  required bool microfone,
  required bool aguardandoEscuta,
  required bool tocando,
  required EstadoServidor servidor,
}) {
  if (!conectado) return EstadoRosto.desconectado;
  if (microfone) return EstadoRosto.ouvindo;
  if (aguardandoEscuta) return EstadoRosto.pensando;
  if (tocando) return EstadoRosto.falando;
  return switch (servidor) {
    EstadoServidor.ocioso => EstadoRosto.ocioso,
    // Microfone já desligado, à espera do `pensando` do servidor.
    EstadoServidor.ouvindo => EstadoRosto.pensando,
    EstadoServidor.pensando => EstadoRosto.pensando,
    EstadoServidor.falando => EstadoRosto.falando,
  };
}
