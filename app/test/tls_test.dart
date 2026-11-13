import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:robo_pegasus/conexao/tls.dart';

void main() {
  test('a CA embutida é um PEM aceito pelo SecurityContext', () {
    final pem = File('assets/certs/scitechear-root-ca.crt').readAsBytesSync();
    expect(() => Tls.contextoCom(pem), returnsNormally);
  });

  test('um PEM inválido falha na hora, não na conexão', () {
    expect(
      () => Tls.contextoCom('não é um certificado'.codeUnits),
      throwsA(isA<TlsException>()),
    );
  });
}
