import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'config/config.dart';
import 'config/tela_config.dart';
import 'robo.dart';
import 'rosto/estado_rosto.dart';
import 'rosto/rosto.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.landscapeLeft,
    DeviceOrientation.landscapeRight,
  ]);
  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  final robo = Robo(await Config.carregar());
  runApp(AppPegasus(robo: robo));
  await robo.iniciar();
}

class AppPegasus extends StatelessWidget {
  const AppPegasus({super.key, required this.robo});

  final Robo robo;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Pegasus',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: Colors.black,
        colorSchemeSeed: EstadoRosto.ocioso.cor,
      ),
      home: TelaRosto(robo: robo),
    );
  }
}

/// A única tela: o rosto em tela cheia. Tocar inicia ou encerra a escuta;
/// toque longo abre a configuração do servidor.
class TelaRosto extends StatelessWidget {
  const TelaRosto({super.key, required this.robo});

  final Robo robo;

  Future<void> _configurar(BuildContext context) async {
    final nova = await editarConfig(context, robo.config);
    if (nova != null) await robo.trocarConfig(nova);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: robo.aoTocar,
        onLongPress: () => _configurar(context),
        child: ListenableBuilder(
          listenable: Listenable.merge([
            robo.estado,
            robo.emocao,
            robo.legenda,
          ]),
          builder: (context, _) => Rosto(
            estado: robo.estado.value,
            emocao: robo.emocao.value,
            nivelVoz: robo.nivelVoz,
            legenda: robo.legenda.value,
          ),
        ),
      ),
    );
  }
}
