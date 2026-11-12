import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import 'conexao/protocolo.dart';
import 'rosto/estado_rosto.dart';
import 'rosto/rosto.dart';

/// Liga com `--dart-define=PEGASUS_DEMO=true`: o rosto percorre os estados
/// e as emoções sozinho, sem servidor, com uma "voz" falsa para a boca.
const modoDemo = bool.fromEnvironment('PEGASUS_DEMO');

class TelaDemo extends StatefulWidget {
  const TelaDemo({super.key});

  @override
  State<TelaDemo> createState() => _TelaDemoState();
}

class _TelaDemoState extends State<TelaDemo> {
  static const _roteiro = [
    (EstadoRosto.ocioso, 5),
    (EstadoRosto.ouvindo, 3),
    (EstadoRosto.pensando, 3),
    (EstadoRosto.falando, 5),
  ];

  final _relogio = Stopwatch()..start();
  late final Timer _timer;
  int _passo = 0;
  int _emocao = 0;
  bool _desconectado = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(milliseconds: 100), (_) => _tique());
  }

  double _inicioPasso = 0;

  double get _agora => _relogio.elapsedMicroseconds / 1e6;

  void _tique() {
    final duracao = _desconectado ? 4 : _roteiro[_passo].$2;
    if (_agora - _inicioPasso < duracao) return;
    setState(() {
      _inicioPasso = _agora;
      if (_desconectado) {
        _desconectado = false;
        _passo = 0;
      } else if (_passo == _roteiro.length - 1) {
        // Fim de uma volta: próxima emoção; depois da última, "dorme".
        _passo = 0;
        _emocao++;
        if (_emocao == Emocao.values.length) {
          _emocao = 0;
          _desconectado = true;
        }
      } else {
        _passo++;
      }
    });
  }

  /// Sílabas de ~180 ms com pausas entre palavras, a -15 a -25 dBFS.
  double _vozFalsa() {
    final t = _agora;
    final palavra = (t * 1.6).floor();
    if (sin(palavra * 12.9898) > 0.6) return 0; // pausa
    final silaba = 0.5 + 0.5 * sin(t * 2 * pi * 5.5);
    return 0.03 + 0.15 * silaba * silaba;
  }

  @override
  void dispose() {
    _timer.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final estado = _desconectado
        ? EstadoRosto.desconectado
        : _roteiro[_passo].$1;
    final emocao = Emocao.values[_emocao];
    return Scaffold(
      body: Rosto(
        estado: estado,
        emocao: emocao,
        nivelVoz: _vozFalsa,
        legenda: 'Demonstração: ${estado.name} · ${emocao.name}',
      ),
    );
  }
}
