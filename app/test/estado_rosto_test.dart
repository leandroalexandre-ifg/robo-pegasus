import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/conexao/protocolo.dart';
import 'package:robo_pegasus/rosto/estado_rosto.dart';

EstadoRosto _exibido({
  bool conectado = true,
  bool microfone = false,
  bool aguardandoEscuta = false,
  bool tocando = false,
  EstadoServidor servidor = EstadoServidor.ocioso,
}) => estadoExibido(
  conectado: conectado,
  microfone: microfone,
  aguardandoEscuta: aguardandoEscuta,
  tocando: tocando,
  servidor: servidor,
);

void main() {
  test('sem conexão é desconectado, mesmo tocando', () {
    expect(_exibido(conectado: false, tocando: true), EstadoRosto.desconectado);
  });

  test('servidor de linguagem fora do ar é desconectado', () {
    expect(
      _exibido(microfone: true, servidor: EstadoServidor.desconectado),
      EstadoRosto.desconectado,
    );
  });

  test('microfone ligado é ouvindo, antes da confirmação do servidor', () {
    expect(
      _exibido(
        microfone: true,
        aguardandoEscuta: true,
        servidor: EstadoServidor.falando,
      ),
      EstadoRosto.ouvindo,
    );
  });

  test('continua falando enquanto toca, mesmo com o servidor ocioso', () {
    expect(_exibido(tocando: true), EstadoRosto.falando);
  });

  test('escuta encerrada à espera do servidor é pensando', () {
    expect(_exibido(servidor: EstadoServidor.ouvindo), EstadoRosto.pensando);
    expect(_exibido(aguardandoEscuta: true), EstadoRosto.pensando);
  });

  test('segue o servidor nos demais casos', () {
    expect(_exibido(), EstadoRosto.ocioso);
    expect(_exibido(servidor: EstadoServidor.pensando), EstadoRosto.pensando);
    expect(_exibido(servidor: EstadoServidor.falando), EstadoRosto.falando);
  });
}
