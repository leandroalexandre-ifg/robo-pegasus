# Robô Pegasus

Repositório: https://github.com/leandroalexandre-ifg/robo-pegasus (branch principal: `main`). Pasta local: `Robo-Pegasus`.

Robô conversacional inspirado no Xiaozhi ESP32: um app Flutter num tablet Android mostra um rosto animado (olhos e boca) e conversa por voz em português. Toda a IA roda num servidor próprio com uma RTX 5090 (32 GB). O robô não tem movimento, motores nem sensores externos.

## Idioma e convenções

- Responda e escreva commits, comentários e documentação em **português do Brasil**.
- Nomes de variáveis, funções e classes podem ficar em inglês. Mensagens exibidas ao usuário ficam sempre em português.
- Use código aberto sempre que possível. Antes de adicionar um modelo, voz ou biblioteca, confira a licença e registre em `docs/licencas.md`.
- Commits pequenos e descritivos, um assunto por commit.

## Ambiente de desenvolvimento

- **Estação de trabalho:** MacBook. O app Flutter é desenvolvido e testado aqui, com o tablet ligado ao Mac.
- **Servidor de IA:** servidor do núcleo NumbERS, no datacenter do IFG, com a RTX 5090. O código de `servidor/` roda e é testado lá, acessado por SSH.
- **Fluxo:** o código vai do Mac para o servidor pelo GitHub (`git push` no Mac, `git pull` no servidor). Nunca edite direto no servidor sem commitar.
- **GPU compartilhada:** o servidor atende outros projetos. Antes de subir o vLLM, confira o uso com `nvidia-smi` e nunca mexa em driver, CUDA ou configurações globais do sistema.
- **Durante o desenvolvimento, o tablet acessa o servidor por um túnel SSH aberto no Mac:**

```bash
ssh -N -L 0.0.0.0:8100:localhost:8100 USUARIO@SERVIDOR_NUMBERS
```

  O tablet, na mesma rede Wi-Fi do Mac, conecta em `ws://IP_DO_MAC:8100/ws`.
- **Acesso publicado:** o Pegasus está em `wss://…/pegasus/ws`, pelo Caddy do SciTech Ear (`tls internal`; rota adicionada no commit `7115a75` do repositório do SciTech Ear), que encaminha para a API (porta 8100). O app confia na CA interna do Caddy (asset embutido). A configuração do Caddy pertence ao SciTech Ear: não alterar daqui.

## Implantação no servidor (Fase 0 concluída)

- Código em `/data/projects/leandro/robo-pegasus`, ambiente em `.venv` (criado com `uv`, **sem pip**: instale pacotes com `~/.local/bin/uv pip install --python .venv ...`).
- Modelos em `modelos/` (`HF_HOME`). Configuração em `~/.config/robo-pegasus/pegasus.env` (modo 600; nunca imprimir).
- Modelo: `cyankiwi/Qwen3.8-27B-AWQ-INT4` (~20 GB na GPU; multimodal, arquitetura híbrida com Gated DeltaNet).
- vLLM 0.33 + torch 2.14 (CUDA 13.0) na **GPU1** (`CUDA_VISIBLE_DEVICES=1`), com `--gpu-memory-utilization 0.85 --max-model-len 8192 --max-num-seqs 8`. Sem o `--max-num-seqs 8`, o perfil de CUDA graphs pede 13 GB extras e dá falta de memória. Usa ~26 GB da GPU1, sobrando ~6 GB.
- Cache de prefixo: o serviço usa `--prefix-match-unit 16`. Com o modelo híbrido, o bloco de cache é de 832 tokens e o estado das camadas Gated DeltaNet só é guardado no fim de cada pedido; por isso a API (`app/aquecimento.py`) manda a cada 60 s um pedido só com o trecho fixo do prompt. Sem isso, a taxa de acerto era 0% e o 1º token levava ~220 ms em vez de ~50 ms.
- Ferramentas (emoção): o serviço também usa `--enable-auto-tool-choice --tool-call-parser qwen3_coder`, porque o template do Qwen3.8 emite chamadas em XML (`<function=...>`). Sem isso o vLLM recusa requisições com `tools`.
- A **GPU0** tem processos residentes do SciTech Ear (`scitechear-api` e `scitechear-worker`, ~3,7 GB). Não usar a GPU0 e não mexer nesses processos.
- Serviços `pegasus-llm.service` (vLLM), `pegasus-api.service` (API) e `pegasus-busca.service` (SearXNG em Docker), no systemd --user, sem `[Install]` (não iniciam com o sistema; limite de 3 tentativas em 10 min). Cópias em `servidor/systemd/`. Ligar/desligar todos juntos: `pegasus-ligar` e `pegasus-desligar` (`servidor/scripts/`, com link em `~/.local/bin`). Estado: `pegasus-status`.
- O `pegasus.env` define `CUDA_HOME` e `PATH` apontando para o `nvcc` do venv e `VLLM_USE_FLASHINFER_SAMPLER=0`: a compilação JIT do FlashInfer falha (nvcc 13.5 com cabeçalhos 13.0), então o amostrador do FlashInfer fica desligado.
- O Qwen3 responde com `<think>` por padrão. Para o robô, desligue o modo de raciocínio na chamada (`"chat_template_kwargs": {"enable_thinking": false}`), por latência.
- Não tocar no SciTech Ear (unidades `scitechear-*`, checkout, Caddy em uso, Ollama, `.env`). Sem sudo.
- Nunca ler `/proc/PID/environ` de nenhum processo, nem dos do Pegasus. Para confirmar a configuração em uso, use os logs (`journalctl --user -u pegasus-api`) ou um endpoint de status.

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

**RTX 5090 (Blackwell):** a configuração que funciona está em "Implantação no servidor". O vLLM ocupa ~26 GB da GPU1 e sobram ~6 GB; decidir na Fase 1 se o Whisper fica nessa folga ou em outro lugar.

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

## Ferramentas de internet do LLM

- `PEGASUS_FERRAMENTAS=data_hora,clima,wikipedia,busca_web` (vazio desliga). Código em `servidor/app/ferramentas/`.
- `data_hora` não é ferramenta: a fala atual vai ao LLM com `[agora: …]` na frente (fuso `PEGASUS_FUSO`), sem rodada extra.
- `clima` (Open-Meteo, cidade padrão `PEGASUS_CIDADE=Goiânia`), `wikipedia` (pt.wikipedia) e `busca_web` (SearXNG local) são oferecidas na requisição da fala. Ao chamar uma, o robô diz "Deixa eu ver…" (já sintetizada), consulta com limite (clima 2,5 s, wikipedia 2 s, busca 3 s; 4 s no total) e responde numa segunda requisição **sem ferramentas**, começando pela fonte ("Segundo a Wikipédia, …", via `continue_final_message`).
- Busca obrigatória: se a fala tem termo de tempo ou atualidade (`ferramentas/atualidade.py`: atual, placar, resultado, preço, notícia; e último, hoje, agora, "quem é o/a" fora de conversa pessoal), a requisição vai com `tool_choice` nomeado para a `busca_web`. Hora, data, clima e contas ficam de fora.
- Divergência: depois da busca, um pedido curto (saída restrita a `concordam`/`divergem`, ~70 ms) roda em paralelo com a resposta; se divergem, o robô diz "Encontrei informações diferentes sobre isso na internet, então não posso afirmar." Custa ~100 ms na resposta com busca.
- A voz lê o texto normalizado por `pipeline/voz.py` (moeda, %, °C, horas, datas, ordinais, números por extenso; "Pégasus"); o tablet e a memória recebem o texto do LLM.
- Nenhuma ferramenta aceita URL do modelo. O texto externo é limpo (`limpeza.py`) e vai entre `DADOS EXTERNOS` e `FIM DOS DADOS EXTERNOS`; não entra na memória nem no registro (só nome, ok, ms e caracteres).
- SearXNG: `pegasus-busca.service` (Docker, imagem fixada pelo digest, só `127.0.0.1:8104`, sem root, sem GPU, SafeSearch estrito, DuckDuckGo/Brave/Bing/Wikipedia). Segredo em `~/.config/robo-pegasus/searxng.env`. O daemon Docker é compartilhado: só mexa no contêiner `pegasus-searxng`.
- User-Agent `RoboPegasus/0.1 (+URL do repositório)`, sem e-mail.

## App (`app/`)

**Estado: pronto (Fases 3 a 5).** Não tratar como pendência:

- Rosto animado completo em `app/lib/rosto/` (estados, emoções, boca pelo RMS, piscar).
- Modo palavra: escuta contínua em ocioso com meio-duplex, sinal discreto de "à espera do nome", rosto desperta ao ouvir o nome (commits `7c7b19e`, `9cb9343`, `2e87528`).
- Mensagem `conversation` tratada (`conexao/protocolo.dart`, `robo.dart`): conversando com `timeout_ms` e esperando o nome mantêm o rosto atento (`c6b8617`, `715d20e`).
- wss:// com a CA interna do Caddy embutida; fechamentos 4009 e 4001 não reconectam sozinhos, 4013 espera mais (`3b1831e`, `ee5f61e`, `a46ec36`).

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

**Fases 0 a 5 concluídas:** servidor completo (VAD, STT, LLM, TTS em fluxo, emoção, memória, palavra de ativação, robustez), app com rosto, ferramentas de internet prontas e publicado em `wss://…/pegasus/ws` pelo Caddy.

**Próxima: Fase 6, piloto.** Detalhes em `docs/plano.md`.
