# Robô Pegasus

Repositório: https://github.com/leandroalexandre-ifg/robo-pegasus (branch principal: `main`). Pasta local: `Robo-Pegasus`.

Robô conversacional inspirado no Xiaozhi ESP32: um app Flutter num tablet Android mostra um rosto animado (olhos e boca) e conversa por voz em português. Toda a IA roda num servidor próprio com uma RTX 5090 (32 GB). O robô não tem movimento, motores nem sensores externos.

## Idioma e convenções

- Responda e escreva commits, comentários e documentação em **português do Brasil**.
- Nomes de variáveis, funções e classes podem ficar em inglês. Mensagens exibidas ao usuário ficam sempre em português.
- Use código aberto sempre que possível. Antes de adicionar um modelo, voz ou biblioteca, confira a licença e registre em `docs/licencas.md`.
- Commits pequenos e descritivos, um assunto por commit.

## Estrutura do repositório

```
servidor/                 Python: servidor de IA
  app/
    main.py               FastAPI + endpoint WebSocket
    pipeline/             vad.py, stt.py, llm.py, tts.py
    sessao.py             estado e histórico de cada robô
    persona/              prompt de sistema e personalidade
  docker/                 Dockerfile e docker-compose (vLLM + servidor)
  testes/
app/                      Flutter: app do tablet
  lib/
    main.dart
    conexao/              cliente WebSocket e protocolo
    audio/                captura, reprodução e cálculo de volume (RMS)
    rosto/                animação e máquina de estados
    config/               endereço do servidor e token
  assets/rive/
docs/
  protocolo.md            especificação das mensagens (fonte da verdade)
  plano.md                roteiro em fases
  licencas.md
```

## Arquitetura

```
Tablet (Flutter)  ──WebSocket wss──►  Servidor (RTX 5090)
  microfone  ── áudio PCM 16 kHz ──►  Silero VAD → faster-whisper → LLM (vLLM) → Piper TTS
  rosto      ◄── estado e emoção ───  LLM
  alto-falante ◄── áudio da resposta ─ Piper TTS
```

- O tablet só capta áudio, toca áudio e anima o rosto. Nenhuma lógica de IA roda no tablet.
- O servidor mantém uma sessão por robô e deve suportar vários tablets ao mesmo tempo.
- A resposta é transmitida em fluxo: o LLM gera texto, o servidor corta em frases e sintetiza a voz frase por frase.

## Servidor (`servidor/`)

| Função | Escolha |
| --- | --- |
| Detecção de fala | Silero VAD |
| Fala → texto | faster-whisper large-v3-turbo (plano B: Whisper via PyTorch) |
| LLM | Qwen3.8 27B quantizado em 4 bits, servido pelo vLLM (API compatível com OpenAI) |
| LLM alternativo (mais rápido) | Qwen 3.6 35B-A3B |
| Texto → fala | Piper, voz pt-BR |
| Orquestração | Python 3.12, FastAPI, asyncio |

**RTX 5090 (Blackwell):** exige driver NVIDIA recente e CUDA 12.8 ou superior. Use builds do PyTorch e do vLLM compatíveis com CUDA 12.8. Limite o vLLM com `--gpu-memory-utilization 0.6` para dividir a GPU com o Whisper.

Comandos (ajustar quando o projeto existir):

```bash
cd servidor
uv sync                                  # instala dependências
docker compose -f docker/docker-compose.yml up vllm   # sobe o LLM
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
uv run pytest
uv run ruff check . && uv run ruff format .
```

Regras do servidor:

- Tudo assíncrono. Nunca bloqueie o loop de eventos: rode Whisper e Piper em executor ou processo separado.
- O LLM é chamado pela API compatível com OpenAI do vLLM; não acople o código a um modelo específico. O nome do modelo vem de configuração.
- Configuração por variáveis de ambiente (`.env`, nunca commitado). Tokens dos tablets também.
- Registre o tempo de cada etapa (VAD, STT, primeira frase do LLM, primeira voz) em todo turno de conversa.

## App (`app/`)

Pacotes previstos: `web_socket_channel`, `record`, `flutter_pcm_sound` (ou `flutter_sound`), `audio_session`, `rive`, `flutter_riverpod`, `wakelock_plus`, `permission_handler`. Confirme a versão atual de cada um antes de adicionar.

```bash
cd app
flutter pub get
flutter run          # tablet conectado via USB ou Wi-Fi
flutter analyze
flutter test
```

Regras do app:

- Uma única tela: o rosto em tela cheia, sem botões visíveis. Tocar na tela inicia a escuta.
- Estados do rosto: `ocioso`, `ouvindo`, `pensando`, `falando`, `desconectado`, mais uma emoção sobreposta (`neutro`, `feliz`, `triste`, `surpreso`, `pensativo`, `bravo`).
- A boca segue o volume (RMS) do áudio tocado, suavizado, com cerca de 50 ms de atraso para compensar o alto-falante.
- **Meio-duplex:** o microfone fica desligado enquanto o robô fala, para ele não ouvir a própria voz.
- Reconexão automática com espera crescente quando a conexão cai.
- Só Android. Orientação travada e tela sempre ligada.

## Protocolo

A especificação completa fica em `docs/protocolo.md`, que é a fonte da verdade. Ao mudar o protocolo, atualize o documento, o servidor e o app no mesmo commit.

Resumo:

- Controle em JSON, áudio em quadros binários, na mesma conexão.
- Áudio de entrada: PCM 16 kHz, mono, 16 bits, blocos de 20 ms. Áudio de saída: PCM no formato nativo da voz (Piper: 22,05 kHz).
- Tablet → servidor: `hello`, `listen_start`, `listen_stop`, `abort`, áudio binário.
- Servidor → tablet: `state`, `stt`, `emotion`, `tts_start`, `tts_end`, áudio binário.
- `ping`/`pong` a cada 15 s.
- Emoções: o LLM usa a ferramenta `definir_emocao(emocao)`. O servidor converte em mensagem `emotion` e nunca envia marcações de emoção para a síntese de voz.

## Metas

- Até **1,5 s** entre o fim da fala do usuário e o primeiro som da resposta, na rede local.
- Respostas curtas: o prompt de sistema limita a resposta a poucas frases, em linguagem adequada ao público.

## Fase atual

**Fase 0, ambiente:** Ubuntu, driver, CUDA 12.8, Docker e vLLM rodando na RTX 5090. Pronto quando o PyTorch e o vLLM usarem a GPU e responderem a um teste.

Próximas fases: 1 pipeline no servidor · 2 app mínimo (primeira conversa completa) · 3 rosto · 4 conversa natural (palavra de ativação, interrupção, persona) · 5 robustez · 6 piloto. Detalhes em `docs/plano.md`.
