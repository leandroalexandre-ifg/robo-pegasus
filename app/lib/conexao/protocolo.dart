import 'dart:convert';

/// Mensagens do protocolo tablet ↔ servidor, versão 1.
///
/// A fonte da verdade é `docs/protocolo.md`. Ao mudar o protocolo, atualize o
/// documento, o servidor e este arquivo no mesmo commit.
const versaoProtocolo = 1;

/// Áudio enviado pelo tablet: PCM 16 bits little-endian, mono, 16 kHz.
const taxaEntrada = 16000;
const msPorBloco = 20;
const bytesPorBloco = taxaEntrada * msPorBloco ~/ 1000 * 2; // 640

/// Intervalo do `ping`.
const intervaloPing = Duration(seconds: 15);

/// Códigos de fechamento enviados pelo servidor.
const fechaProtocolo = 4000;
const fechaToken = 4001;
const fechaTempo = 4008;

/// Estados enviados pelo servidor em `state`.
///
/// `desconectado` vindo do servidor: a conexão está de pé, mas o servidor de
/// linguagem (vLLM) está fora do ar e o robô não escuta.
enum EstadoServidor { ocioso, ouvindo, pensando, falando, desconectado }

/// Emoções enviadas pelo servidor em `emotion`.
enum Emocao { neutro, feliz, triste, surpreso, pensativo, bravo }

/// Como a escuta começa (campo `activation` do `hello` do servidor).
/// - [toque]: só com `listen_start`.
/// - [palavra]: escuta contínua; o servidor espera o nome "Pegasus".
enum Ativacao { toque, palavra }

String helloTablet({required String token, required String deviceId}) =>
    jsonEncode({
      'type': 'hello',
      'version': versaoProtocolo,
      'token': token,
      'device_id': deviceId,
      'audio': {
        'format': 'pcm_s16le',
        'sample_rate': taxaEntrada,
        'channels': 1,
        'frame_ms': msPorBloco,
      },
    });

String listenStart() => jsonEncode({'type': 'listen_start'});
String listenStop() => jsonEncode({'type': 'listen_stop'});
String abort() => jsonEncode({'type': 'abort'});
String ping() =>
    jsonEncode({'type': 'ping', 't': DateTime.now().millisecondsSinceEpoch});

/// Mensagem de controle recebida do servidor.
sealed class MensagemServidor {
  const MensagemServidor();

  /// Interpreta um quadro de texto. Devolve `null` para tipos desconhecidos,
  /// que devem ser ignorados.
  static MensagemServidor? decodificar(String texto) {
    final json = jsonDecode(texto);
    if (json is! Map<String, dynamic>) {
      throw const FormatException('mensagem não é um objeto JSON');
    }
    switch (json['type']) {
      case 'hello':
        final audio = json['audio'];
        final taxa = audio is Map ? audio['sample_rate'] : null;
        return HelloServidor(
          sessionId: '${json['session_id'] ?? ''}',
          taxaSaida: taxa is int ? taxa : 22050,
          ativacao: json['activation'] == 'palavra'
              ? Ativacao.palavra
              : Ativacao.toque,
        );
      case 'state':
        final nome = json['state'];
        for (final e in EstadoServidor.values) {
          if (e.name == nome) return Estado(e);
        }
        return null;
      case 'stt':
        return Stt('${json['text'] ?? ''}');
      case 'tts_start':
        final taxa = json['sample_rate'];
        return TtsStart(
          texto: '${json['text'] ?? ''}',
          taxa: taxa is int ? taxa : null,
        );
      case 'tts_end':
        return const TtsEnd();
      case 'pong':
        return const Pong();
      case 'emotion':
        final nome = json['emotion'];
        for (final e in Emocao.values) {
          if (e.name == nome) return MudaEmocao(e);
        }
        return null;
      case 'error':
        return Erro('${json['message'] ?? 'Erro no servidor.'}');
      default:
        return null;
    }
  }
}

class HelloServidor extends MensagemServidor {
  const HelloServidor({
    required this.sessionId,
    required this.taxaSaida,
    this.ativacao = Ativacao.toque,
  });
  final String sessionId;
  final int taxaSaida;

  /// Sem o campo (servidor antigo) ou com valor desconhecido, vale `toque`.
  final Ativacao ativacao;
}

class Estado extends MensagemServidor {
  const Estado(this.estado);
  final EstadoServidor estado;
}

class Stt extends MensagemServidor {
  const Stt(this.texto);
  final String texto;
}

class TtsStart extends MensagemServidor {
  const TtsStart({required this.texto, this.taxa});
  final String texto;
  final int? taxa;
}

class TtsEnd extends MensagemServidor {
  const TtsEnd();
}

class Pong extends MensagemServidor {
  const Pong();
}

class Erro extends MensagemServidor {
  const Erro(this.mensagem);
  final String mensagem;
}

class MudaEmocao extends MensagemServidor {
  const MudaEmocao(this.emocao);
  final Emocao emocao;
}
