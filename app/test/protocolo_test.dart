import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/conexao/protocolo.dart';

void main() {
  test('bloco de 20 ms a 16 kHz tem 640 bytes', () {
    expect(bytesPorBloco, 640);
  });

  test('hello do tablet segue docs/protocolo.md', () {
    final json = jsonDecode(helloTablet(token: 'abc', deviceId: 'tablet-01'));
    expect(json, {
      'type': 'hello',
      'version': 1,
      'token': 'abc',
      'device_id': 'tablet-01',
      'audio': {
        'format': 'pcm_s16le',
        'sample_rate': 16000,
        'channels': 1,
        'frame_ms': 20,
      },
    });
  });

  test('hello do servidor traz a taxa de saída', () {
    final msg = MensagemServidor.decodificar(
      '{"type":"hello","version":1,"session_id":"3f2c9a7e",'
      '"audio":{"format":"pcm_s16le","sample_rate":22050,"channels":1}}',
    );
    expect(msg, isA<HelloServidor>());
    expect((msg as HelloServidor).taxaSaida, 22050);
    expect(msg.sessionId, '3f2c9a7e');
  });

  test('state, stt, tts_start, tts_end e error', () {
    final estado = MensagemServidor.decodificar(
      '{"type":"state","state":"pensando"}',
    );
    expect((estado as Estado).estado, EstadoServidor.pensando);

    final stt = MensagemServidor.decodificar('{"type":"stt","text":"Olá"}');
    expect((stt as Stt).texto, 'Olá');

    final tts = MensagemServidor.decodificar(
      '{"type":"tts_start","text":"Oi!","sample_rate":22050}',
    );
    expect((tts as TtsStart).taxa, 22050);
    expect(tts.texto, 'Oi!');

    expect(MensagemServidor.decodificar('{"type":"tts_end"}'), isA<TtsEnd>());

    final erro = MensagemServidor.decodificar(
      '{"type":"error","message":"Falhou."}',
    );
    expect((erro as Erro).mensagem, 'Falhou.');
  });

  test('emotion com cada emoção', () {
    for (final e in Emocao.values) {
      final msg = MensagemServidor.decodificar(
        '{"type":"emotion","emotion":"${e.name}"}',
      );
      expect((msg as MudaEmocao).emocao, e);
    }
  });

  test('tipos, estados e campos desconhecidos são ignorados', () {
    expect(
      MensagemServidor.decodificar('{"type":"emotion","emotion":"eufórico"}'),
      isNull,
    );
    expect(MensagemServidor.decodificar('{"type":"novidade"}'), isNull);
    expect(
      MensagemServidor.decodificar('{"type":"state","state":"dormindo"}'),
      isNull,
    );
    final msg = MensagemServidor.decodificar('{"type":"tts_end","extra":1}');
    expect(msg, isA<TtsEnd>());
  });

  test('JSON que não é objeto é erro de formato', () {
    expect(() => MensagemServidor.decodificar('[1,2]'), throwsFormatException);
  });
}
