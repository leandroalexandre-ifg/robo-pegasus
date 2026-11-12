# App do Robô Pegasus

App Flutter (só Android) que mostra o rosto do robô e conversa com o servidor pelo protocolo de `docs/protocolo.md`.

**Fase 3:** rosto animado (olhos e boca) desenhado com `CustomPainter`, em tela cheia.

| Estado | Cor dos traços | Comportamento |
| --- | --- | --- |
| ocioso | azul | pisca e olha em volta; respira devagar |
| ouvindo | verde | olhos mais abertos, olhar para a frente |
| pensando | âmbar | olhos apertados, olhar para cima e para o lado |
| falando | roxo | a boca segue o volume (RMS) da voz, com ~50 ms de atraso |
| desconectado | cinza | olhos fechados, dormindo |

Emoções (mensagem `emotion`): `neutro`, `feliz` (olhos em meia-lua, sorriso), `triste` (pálpebras caídas por fora, boca para baixo), `surpreso` (olhos grandes, boca em "O"), `pensativo` (olhar para cima, cabeça inclinada) e `bravo` (pálpebras baixas do lado do nariz). A emoção volta a `neutro` num novo `listen_start` ou 10 s depois do ocioso.

- **Tocar** inicia a escuta. O servidor percebe sozinho (VAD) quando você parou de falar e responde; se ninguém falar em 8 s, o rosto volta ao ocioso. Tocar durante a escuta encerra antes, sem esperar o VAD.
- **Tocar enquanto ele pensa ou fala** envia `abort`, corta a voz na hora e volta a ouvir.
- **Toque longo** abre a configuração do servidor (endereço, token e identificação do tablet). Fica salva no tablet.
- Meio-duplex: o microfone só fica ligado enquanto está verde.

### Ativação por palavra (Fase 4b)

O modo vem do servidor (`PEGASUS_ATIVACAO`, campo `activation` do `hello`); o app não tem configuração própria para isso.

- **`toque`** (padrão): como acima.
- **`palavra`:** o microfone fica aberto o tempo todo e o servidor espera o nome: "Pegasus, que horas são?" já é a pergunta; só "Pegasus" faz o robô responder "Oi?" e ouvir a próxima fala. Outras falas são descartadas pelo servidor. Com o rosto ocioso, um **pontinho verde** pulsando abaixo da boca indica que ele está ouvindo à espera do nome.
- O toque continua valendo nos dois modos.
- Meio-duplex no modo `palavra`: o microfone fecha no primeiro `tts_start` e só reabre depois de tocar todo o áudio recebido, com 250 ms de folga, para o robô não ouvir a própria voz.

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

Para ver o rosto sem o servidor, o modo de demonstração percorre estados e emoções com uma voz falsa:

```bash
flutter run --profile --dart-define=PEGASUS_DEMO=true
```

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
  audio/                captura em blocos de 20 ms, reprodução PCM em fluxo
                        e envelope de volume para a boca
  demo.dart             modo de demonstração (PEGASUS_DEMO)
  rosto/                expressões, animador (piscar, olhar, boca) e pintor
  config/               endereço, token e diálogo de configuração
```

Observação: o `flutter_pcm_sound` 3.3.3 fixa `compileSdk 33`; o `android/build.gradle.kts` força 36 só para ele.
