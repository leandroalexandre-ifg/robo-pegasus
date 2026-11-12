# App do Robô Pegasus

App Flutter (só Android) que mostra o rosto do robô e conversa com o servidor pelo protocolo de `docs/protocolo.md`.

**Fase 2, versão mínima:** um círculo em tela cheia que muda de cor por estado.

| Estado | Cor |
| --- | --- |
| ocioso | azul |
| ouvindo | verde |
| pensando | âmbar |
| falando | roxo |
| desconectado | cinza |

- **Tocar** inicia a escuta; tocar de novo encerra e o robô responde. Tocar enquanto ele pensa ou fala interrompe e começa a ouvir.
- **Toque longo** abre a configuração do servidor (endereço, token e identificação do tablet). Fica salva no tablet.
- Meio-duplex: o microfone só fica ligado enquanto está verde.

## Rodar

```bash
flutter pub get
flutter run \
  --dart-define=PEGASUS_URL=ws://IP_DO_MAC:8000/ws \
  --dart-define=PEGASUS_TOKEN=token-do-tablet \
  --dart-define=PEGASUS_DEVICE_ID=tablet-01
flutter analyze
flutter test
```

Os `--dart-define` só dão os valores iniciais; depois de salvar pelo toque longo, vale o que está no tablet.

Durante o desenvolvimento, o tablet chega ao servidor por um túnel aberto no Mac. O servidor do Pegasus escuta em `127.0.0.1:8100` lá:

```bash
ssh -N -L 0.0.0.0:8000:localhost:8100 USUARIO@SERVIDOR_NUMBERS
```

## Estrutura

```
lib/
  main.dart             tela única, tela cheia e paisagem
  robo.dart             junta conexão, microfone e alto-falante; decide o estado
  conexao/              protocolo v1 e cliente WebSocket com reconexão
  audio/                captura em blocos de 20 ms e reprodução PCM em fluxo
  rosto/                estados e o círculo (o rosto animado vem na Fase 3)
  config/               endereço, token e diálogo de configuração
```

Observação: o `flutter_pcm_sound` 3.3.3 fixa `compileSdk 33`; o `android/build.gradle.kts` força 36 só para ele.
