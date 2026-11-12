import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import 'audio/captura.dart';
import 'audio/reproducao.dart';
import 'config/config.dart';
import 'conexao/cliente.dart';
import 'conexao/protocolo.dart';
import 'rosto/estado_rosto.dart';

/// Junta conexão, microfone e alto-falante e decide o estado do rosto.
///
/// Dois modos de ativação, conforme o `hello` do servidor:
///
/// - `toque`: um toque inicia a escuta; o servidor decide o fim da fala pelo
///   VAD e manda `pensando` (ou `ocioso`, se ninguém falou). O microfone só
///   fica ligado durante a escuta.
/// - `palavra`: o microfone fica aberto o tempo todo e o servidor espera o
///   nome "Pegasus". O toque continua valendo.
///
/// Meio-duplex nos dois: enquanto o robô fala, o microfone está desligado.
/// Tocar enquanto o robô pensa ou fala envia `abort` e volta a ouvir.
class Robo {
  Robo(this._config) : _cliente = Cliente(_config);

  Config _config;
  final Cliente _cliente;
  final _captura = Captura();
  final _reproducao = Reproducao();
  final _assinaturas = <StreamSubscription<Object>>[];

  EstadoServidor _servidor = EstadoServidor.ocioso;

  /// Pedimos `listen_start` e o servidor ainda não respondeu `ouvindo`.
  /// Enquanto isso, o áudio que chega é resto do turno interrompido e é
  /// descartado, e estados antigos não desligam o microfone.
  bool _aguardandoEscuta = false;

  /// Modo `palavra`: o microfone fechou no primeiro `tts_start` e só reabre
  /// depois de tocar todo o áudio recebido, mais uma pequena folga para o
  /// fim do som sair do alto-falante.
  bool _vozDoRobo = false;
  Timer? _timerReabrir;
  static const _caudaVoz = Duration(milliseconds: 250);

  final estado = ValueNotifier<EstadoRosto>(EstadoRosto.desconectado);

  /// Emoção sobreposta ao estado. Volta a `neutro` num novo `listen_start`
  /// ou depois de [_duracaoEmocao] com o rosto ocioso (fala já tocada).
  final emocao = ValueNotifier<Emocao>(Emocao.neutro);
  Timer? _timerEmocao;
  static const _duracaoEmocao = Duration(seconds: 10);

  /// Modo `palavra`, rosto ocioso e microfone aberto: o robô está ouvindo à
  /// espera do nome. O rosto mostra um sinal discreto.
  final esperandoNome = ValueNotifier<bool>(false);

  /// Texto discreto no rodapé: o que foi entendido, erro ou motivo da queda.
  final legenda = ValueNotifier<String?>(null);

  Config get config => _config;

  bool get _continuo => _cliente.ativacao == Ativacao.palavra;

  /// Volume da voz que está tocando (RMS, 0 a 1), para a boca do rosto.
  double nivelVoz() => _reproducao.nivel();

  Future<void> iniciar() async {
    unawaited(WakelockPlus.enable());
    _cliente.conectado.addListener(_aoMudarConexao);
    _cliente.motivo.addListener(_atualizar);
    _reproducao.tocando.addListener(_atualizar);
    _assinaturas
      ..add(_cliente.mensagens.listen(_aoMensagem))
      ..add(_cliente.audio.listen(_aoAudio));
    _cliente.iniciar();
    await _captura.pedirPermissao();
  }

  Future<void> trocarConfig(Config config) async {
    _config = config;
    await config.salvar();
    _cliente.trocarConfig(config);
  }

  /// Toque na tela: inicia a escuta. Se o robô estiver pensando ou falando,
  /// envia `abort` e começa a ouvir. Durante a escuta, um toque encerra a
  /// fala antes do VAD (`listen_stop`).
  Future<void> aoTocar() async {
    if (!_cliente.conectado.value) {
      _cliente.trocarConfig(_config); // tenta de novo agora
      return;
    }
    if (_escutando) {
      // No modo contínuo o microfone segue aberto depois do listen_stop.
      if (!_continuo) await _pararMicrofone();
      _cliente.enviarTexto(listenStop());
      return;
    }
    final ocupado =
        _servidor == EstadoServidor.pensando ||
        _servidor == EstadoServidor.falando ||
        _reproducao.tocando.value;
    _reproducao.descartar();
    // O `ocioso` que responde ao abort chega antes do `ouvindo` e é
    // ignorado porque já estamos aguardando a escuta.
    if (ocupado) _cliente.enviarTexto(abort());
    _aguardandoEscuta = true;
    legenda.value = null;
    _timerEmocao?.cancel();
    emocao.value = Emocao.neutro;
    _timerReabrir?.cancel();
    _vozDoRobo = false;
    _cliente.enviarTexto(listenStart());
    final ok = await _captura.iniciar(_cliente.enviarAudio);
    if (!ok) {
      _cliente.enviarTexto(abort());
      legenda.value = 'Sem permissão para usar o microfone';
    }
    _atualizar();
  }

  Future<void> liberar() async {
    _timerEmocao?.cancel();
    _timerReabrir?.cancel();
    for (final a in _assinaturas) {
      await a.cancel();
    }
    await _cliente.parar();
    await _captura.liberar();
    await _reproducao.liberar();
    unawaited(WakelockPlus.disable());
  }

  Future<void> _aoMudarConexao() async {
    if (_cliente.conectado.value) {
      legenda.value = null;
      await _reproducao.preparar(_cliente.taxaSaida);
      if (_continuo) await _abrirMicrofone();
    } else {
      _servidor = EstadoServidor.ocioso;
      _aguardandoEscuta = false;
      _vozDoRobo = false;
      _timerReabrir?.cancel();
      _reproducao.descartar();
      await _captura.parar();
    }
    _atualizar();
  }

  void _aoMensagem(MensagemServidor msg) {
    switch (msg) {
      case Estado(:final estado):
        _servidor = estado;
        if (estado == EstadoServidor.ouvindo) {
          _aguardandoEscuta = false;
        } else if (!_continuo && !_aguardandoEscuta && _captura.ativa) {
          // O servidor saiu da escuta (pensando, ou ocioso após abort).
          unawaited(_pararMicrofone());
        }
      case Stt(:final texto):
        legenda.value = texto.isEmpty ? 'Não entendi' : texto;
      case TtsStart(:final taxa):
        // Resto do turno interrompido: o áudio dele será descartado.
        if (_aguardandoEscuta) break;
        if (taxa != null) unawaited(_reproducao.preparar(taxa));
        if (_continuo && !_vozDoRobo) {
          // Meio-duplex: fecha o microfone antes do primeiro som, para o
          // robô não ouvir a própria voz (que também diz "Pegasus").
          _vozDoRobo = true;
          _timerReabrir?.cancel();
          unawaited(_pararMicrofone());
        }
      case Erro(:final mensagem):
        legenda.value = mensagem;
      case MudaEmocao(emocao: final e):
        emocao.value = e;
      case HelloServidor() || TtsEnd() || Pong():
        break;
    }
    _atualizar();
  }

  void _aoAudio(Uint8List pcm) {
    if (_aguardandoEscuta) return;
    // No modo toque, microfone ligado quer dizer que o usuário interrompeu.
    if (!_continuo && _captura.ativa) return;
    _reproducao.tocar(pcm);
  }

  /// O usuário está falando para o robô (não só o microfone aberto à espera
  /// do nome).
  bool get _escutando => _continuo
      ? !_vozDoRobo &&
            (_aguardandoEscuta || _servidor == EstadoServidor.ouvindo)
      : _captura.ativa;

  Future<void> _abrirMicrofone() async {
    final ok = await _captura.iniciar(_cliente.enviarAudio);
    if (!ok && _cliente.conectado.value) {
      legenda.value = 'Sem permissão para usar o microfone';
    }
    _atualizar();
  }

  Future<void> _pararMicrofone() async {
    await _captura.parar();
    _atualizar();
  }

  /// Modo `palavra`: reabre o microfone quando a voz do robô terminou de
  /// tocar e o servidor já saiu da fala (`ocioso` ou `ouvindo`).
  void _talvezReabrir() {
    final pode =
        _continuo &&
        _vozDoRobo &&
        _cliente.conectado.value &&
        !_reproducao.tocando.value &&
        (_servidor == EstadoServidor.ocioso ||
            _servidor == EstadoServidor.ouvindo);
    if (!pode) {
      _timerReabrir?.cancel();
      _timerReabrir = null;
      return;
    }
    _timerReabrir ??= Timer(_caudaVoz, () {
      _timerReabrir = null;
      _vozDoRobo = false;
      unawaited(_abrirMicrofone());
    });
  }

  void _atualizar() {
    final anterior = estado.value;
    _talvezReabrir();
    estado.value = estadoExibido(
      conectado: _cliente.conectado.value,
      microfone: _escutando,
      aguardandoEscuta: _aguardandoEscuta,
      tocando: _reproducao.tocando.value,
      servidor: _servidor,
    );
    esperandoNome.value =
        _continuo && estado.value == EstadoRosto.ocioso && _captura.ativa;
    if (!_cliente.conectado.value && _cliente.motivo.value != null) {
      legenda.value = _cliente.motivo.value;
    }
    // A emoção some um tempo depois de o rosto ficar ocioso, isto é, depois
    // que a fala terminou de tocar (não no `ocioso` do servidor, que chega
    // enquanto o áudio ainda toca).
    if (estado.value != anterior) {
      _timerEmocao?.cancel();
      if (estado.value == EstadoRosto.ocioso) {
        _timerEmocao = Timer(_duracaoEmocao, () {
          emocao.value = Emocao.neutro;
        });
      }
    }
  }
}
