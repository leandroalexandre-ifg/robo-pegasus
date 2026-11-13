import 'dart:io';

import 'package:flutter/services.dart' show rootBundle;

/// Confiança TLS do app para o `wss://`: as raízes públicas **mais** a CA
/// interna (Caddy) que assina o certificado do servidor, a mesma do
/// SciTech Ear.
///
/// O `dart:io` não consulta o armazenamento de CAs do Android: usa o seu
/// próprio conjunto de raízes. Sem isto, o `wss://` do servidor falha no
/// handshake, e instalar a CA no tablet não adiantaria. Pelo mesmo motivo
/// não há `network_security_config.xml`: ele vale para a pilha de rede Java,
/// que o `web_socket_channel` não usa.
///
/// O `ws://` do túnel de desenvolvimento não passa por aqui.
class Tls {
  Tls._();

  static const _caAsset = 'assets/certs/scitechear-root-ca.crt';

  static SecurityContext? _contexto;

  /// Carrega a CA embutida. Chamado uma vez em `main()`, antes de conectar.
  ///
  /// `withTrustedRoots: true` mantém as raízes públicas: a CA interna é
  /// somada a elas. Uma falha aqui (asset fora da build ou PEM inválido)
  /// sobe de propósito, em vez de virar um erro de rede disfarçado depois.
  static Future<void> iniciar() async {
    if (_contexto != null) return;
    final ca = await rootBundle.load(_caAsset);
    _contexto = contextoCom(ca.buffer.asUint8List());
  }

  /// Contexto com as raízes públicas e a CA em [pem].
  static SecurityContext contextoCom(List<int> pem) =>
      SecurityContext(withTrustedRoots: true)..setTrustedCertificatesBytes(pem);

  /// Um `HttpClient` novo que confia na CA interna, para o
  /// `customClient` do WebSocket. Novo a cada conexão porque o WebSocket
  /// fica dono dele; o que se compartilha é o [SecurityContext].
  static HttpClient novoCliente() => HttpClient(context: _contexto);
}
