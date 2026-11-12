import 'dart:math';
import 'dart:ui' show Color;

import 'package:flutter/foundation.dart';

import '../audio/volume.dart';
import '../conexao/protocolo.dart';
import 'estado_rosto.dart';
import 'expressao.dart';

/// Move o rosto quadro a quadro: transição entre expressões, piscar, olhar
/// e boca. Não desenha nada; o pintor lê os valores daqui.
class AnimadorRosto extends ChangeNotifier {
  AnimadorRosto({Random? aleatorio, double Function()? nivelVoz})
    : _rnd = aleatorio ?? Random(),
      _nivelVoz = nivelVoz ?? (() => 0) {
    _proximaPiscada = _intervaloPiscada();
  }

  final Random _rnd;
  final double Function() _nivelVoz;

  EstadoRosto _estado = EstadoRosto.desconectado;
  Emocao _emocao = Emocao.neutro;
  Expressao _alvo = Expressao.para(EstadoRosto.desconectado, Emocao.neutro);

  /// Expressão atual, a caminho de [Expressao.para] do estado e da emoção.
  Expressao expressao = Expressao.para(EstadoRosto.desconectado, Emocao.neutro);

  /// Cor dos traços, a caminho da cor do estado.
  Color cor = EstadoRosto.desconectado.cor;

  /// Pálpebras numa piscada: 0 abertas, 1 fechadas.
  double piscada = 0;

  /// Olhar além do que a expressão define (vaguear e microssacadas).
  double olharX = 0;
  double olharY = 0;

  /// Abertura da boca pela voz, 0 a 1, já suavizada.
  double boca = 0;

  /// Segundos desde o início, para movimentos lentos (respiração).
  double tempo = 0;

  /// Sinal de "ouvindo à espera do nome", 0 a 1, com entrada e saída suaves.
  double sinalNome = 0;

  /// Liga o sinal de "ouvindo à espera do nome" (modo palavra).
  bool esperandoNome = false;

  EstadoRosto get estado => _estado;
  Emocao get emocao => _emocao;

  set estado(EstadoRosto e) {
    if (e == _estado) return;
    final anterior = _estado;
    _estado = e;
    _alvo = Expressao.para(_estado, _emocao);
    // Uma piscada ao começar a ouvir ou ao acordar parece natural.
    if (e == EstadoRosto.ouvindo || anterior == EstadoRosto.desconectado) {
      _proximaPiscada = tempo + 0.05;
    }
    _proximoOlhar = tempo;
  }

  set emocao(Emocao e) {
    if (e == _emocao) return;
    _emocao = e;
    _alvo = Expressao.para(_estado, _emocao);
  }

  // Piscar.
  static const _fecha = 0.07, _segura = 0.03, _abre = 0.12;
  double _proximaPiscada = 0;
  double? _inicioPiscada;

  // Olhar.
  double _alvoOlharX = 0, _alvoOlharY = 0, _proximoOlhar = 0;

  /// Avança [dt] segundos.
  void avancar(double dt) {
    if (dt <= 0) return;
    dt = min(dt, 0.1); // depois de uma pausa, não pular
    tempo += dt;
    expressao = Expressao.lerp(expressao, _alvo, _passo(dt, 0.15));
    cor = Color.lerp(cor, _estado.cor, _passo(dt, 0.25))!;
    final alvoSinal = esperandoNome && _estado == EstadoRosto.ocioso ? 1 : 0;
    sinalNome += (alvoSinal - sinalNome) * _passo(dt, 0.4);
    _animarPiscada();
    _animarOlhar(dt);
    _animarBoca(dt);
    notifyListeners();
  }

  void _animarPiscada() {
    if (_estado == EstadoRosto.desconectado) {
      piscada = 0;
      _inicioPiscada = null;
      return;
    }
    final inicio = _inicioPiscada;
    if (inicio == null) {
      if (tempo >= _proximaPiscada) _inicioPiscada = tempo;
      piscada = 0;
      return;
    }
    final t = tempo - inicio;
    if (t < _fecha) {
      piscada = t / _fecha;
    } else if (t < _fecha + _segura) {
      piscada = 1;
    } else if (t < _fecha + _segura + _abre) {
      piscada = 1 - (t - _fecha - _segura) / _abre;
    } else {
      piscada = 0;
      _inicioPiscada = null;
      // De vez em quando, uma piscada dupla.
      _proximaPiscada = _rnd.nextDouble() < 0.2
          ? tempo + 0.12
          : _intervaloPiscada();
    }
  }

  double _intervaloPiscada() => tempo + 2 + _rnd.nextDouble() * 4;

  void _animarOlhar(double dt) {
    if (tempo >= _proximoOlhar) _escolherOlhar();
    // Sacada: movimento rápido até o alvo.
    final k = _passo(dt, 0.05);
    olharX += (_alvoOlharX - olharX) * k;
    olharY += (_alvoOlharY - olharY) * k;
  }

  void _escolherOlhar() {
    double faixa(double a) => (_rnd.nextDouble() * 2 - 1) * a;
    final antesX = _alvoOlharX, antesY = _alvoOlharY;
    switch (_estado) {
      case EstadoRosto.ocioso:
        // Vagueia: às vezes volta ao centro, às vezes olha em volta.
        if (_rnd.nextDouble() < 0.35) {
          _alvoOlharX = faixa(0.1);
          _alvoOlharY = faixa(0.08);
        } else {
          _alvoOlharX = faixa(0.8);
          _alvoOlharY = faixa(0.5);
        }
        _proximoOlhar = tempo + 1 + _rnd.nextDouble() * 2.5;
      case EstadoRosto.ouvindo || EstadoRosto.falando:
        // Atento: só microssacadas perto do centro.
        _alvoOlharX = faixa(0.12);
        _alvoOlharY = faixa(0.08);
        _proximoOlhar = tempo + 0.8 + _rnd.nextDouble() * 1.2;
      case EstadoRosto.pensando:
        _alvoOlharX = faixa(0.15);
        _alvoOlharY = faixa(0.1);
        _proximoOlhar = tempo + 0.6 + _rnd.nextDouble();
      case EstadoRosto.desconectado:
        _alvoOlharX = 0;
        _alvoOlharY = 0;
        _proximoOlhar = tempo + 1;
    }
    // Uma sacada grande às vezes vem com uma piscada.
    final salto = (_alvoOlharX - antesX).abs() + (_alvoOlharY - antesY).abs();
    if (salto > 0.6 && _inicioPiscada == null && _rnd.nextDouble() < 0.3) {
      _proximaPiscada = tempo;
    }
  }

  void _animarBoca(double dt) {
    final alvo = _estado == EstadoRosto.falando
        ? aberturaPorRms(_nivelVoz())
        : 0.0;
    // Abre depressa e fecha um pouco mais devagar, como uma boca de verdade.
    boca += (alvo - boca) * _passo(dt, alvo > boca ? 0.03 : 0.08);
  }

  /// Fração do caminho a andar em [dt] numa aproximação exponencial com
  /// constante de tempo [tau].
  static double _passo(double dt, double tau) => 1 - exp(-dt / tau);
}
