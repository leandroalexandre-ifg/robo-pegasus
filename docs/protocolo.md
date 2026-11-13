# Protocolo tablet ↔ servidor

Este documento é a fonte da verdade do protocolo. Ao mudar o protocolo, atualize este documento, o servidor (`servidor/app/`) e o app (`app/lib/conexao/`) no mesmo commit.

**Versão do protocolo:** 1

## Conexão

- WebSocket em `/ws`. O servidor escuta em `127.0.0.1:8100` (`PEGASUS_HOST` e `PEGASUS_PORTA_API`). O tablet chega a ele por túnel SSH, porta liberada ou VPN.
- Uma conexão por tablet. Na mesma conexão trafegam:
  - **quadros de texto**: controle, em JSON, sempre com o campo `type`;
  - **quadros binários**: áudio PCM, sem cabeçalho.
- Campos desconhecidos devem ser ignorados, para permitir evolução sem quebrar o outro lado.

## Sessão e memória

Cada conexão é uma sessão. O servidor guarda uma memória curta da conversa da sessão: os últimos `PEGASUS_MEMORIA_TURNOS` turnos (padrão 6), cada um com a fala do usuário e o que o robô respondeu, e os envia ao LLM a cada turno. Uma resposta interrompida entra na memória só com as frases que chegaram a ser sintetizadas; um turno sem resposta (sem fala reconhecida, erro, `abort` antes da primeira frase) não entra. A memória é zerada quando a conexão cai, numa despedida do modo `palavra` (ver "Conversa") e depois de `PEGASUS_MEMORIA_S` (padrão 180 s; 0 desliga) sem conversa, contados do fim do último turno: quem chegar depois começa do zero.

A memória fica só na memória do processo e é descartada quando a conexão fecha. Ao reconectar, o tablet começa uma conversa nova.

## Áudio

| Sentido | Formato | Blocos |
| --- | --- | --- |
| Tablet → servidor | PCM 16 bits little-endian, mono, 16 kHz | 20 ms (640 bytes) |
| Servidor → tablet | PCM 16 bits little-endian, mono, taxa da voz (Piper faber: 22.050 Hz) | até 100 ms cada |

A taxa do áudio de saída é informada no `hello` do servidor e repetida em cada `tts_start`.

## Sequência de um turno

```
Tablet                                   Servidor
  │ ── hello {token} ───────────────────►  │
  │ ◄─────────────────── hello {sessão} ── │
  │ ◄───────────────── state "ocioso" ──── │
  │ ── listen_start ────────────────────►  │
  │ ◄───────────────── state "ouvindo" ─── │
  │ ══ áudio PCM 16 kHz (20 ms) ════════►  │
  │                                        │   o VAD detecta o fim da fala
  │ ◄──────────────── state "pensando" ─── │   (ou o tablet envia listen_stop)
  │ ◄────────────────────── stt {text} ─── │
  │ ◄──────────── emotion {"feliz"} ────── │   uma por turno; pode vir já no meio da fala
  │ ◄───────────────── state "falando" ─── │
  │ ◄─────────────── tts_start {frase} ─── │   ┐
  │ ◄══════════════ áudio PCM da frase ═══ │   │ uma vez por frase
  │ ◄──────────────────────── tts_end ──── │   ┘
  │ ◄───────────────── state "ocioso" ──── │
```

**Fim da fala:** o servidor detecta sozinho, com o Silero VAD, quando o usuário parou de falar: depois de `PEGASUS_VAD_SILENCIO_MS` (padrão 600 ms) de silêncio após a fala, a escuta termina e o servidor envia `state "pensando"`. O tablet não precisa enviar `listen_stop`, mas pode, para encerrar antes.

**Prévia:** com `PEGASUS_VAD_PREVIA_MS` (padrão 300 ms) de silêncio, o servidor já começa o turno: transcreve, verifica a palavra de ativação e gera a primeira frase e a voz dela. Ele não envia nada ao tablet antes de completar `PEGASUS_VAD_SILENCIO_MS` (ou de receber `listen_stop`). Se a pessoa voltar a falar nesse meio-tempo, o servidor descarta a prévia sem deixar rastro e espera a fala terminar de novo. Para o tablet, nada muda: as mensagens e a ordem delas são as mesmas, só chegam mais cedo. `PEGASUS_VAD_PREVIA_MS=0` desliga a prévia.

**Meio-duplex:** no modo `toque`, o tablet desliga o microfone ao receber `state "pensando"` (ou `state "ocioso"`) e só volta a ouvir com um novo `listen_start`. O servidor ignora áudio recebido fora do estado `ouvindo`. No modo `palavra`, veja a seção a seguir.

## Ativação: toque ou palavra

O modo é configurado no servidor com `PEGASUS_ATIVACAO` (padrão `toque`) e informado ao tablet no campo `activation` do `hello` do servidor.

- **`toque`:** a escuta começa com `listen_start` (um toque na tela), como na sequência acima.
- **`palavra`:** escuta contínua. A escuta começa quando o usuário diz "Pegasus". O toque (`listen_start`) continua valendo.

### Modo `palavra`

O tablet envia áudio o tempo todo, exceto enquanto toca a voz do robô: ele fecha o microfone no primeiro `tts_start` e reabre quando termina de tocar o último áudio recebido. Como o servidor envia o áudio mais rápido que o tempo real, isso acontece depois do `state` seguinte (`ocioso` ou `ouvindo`). Assim o robô não ouve a própria voz, que também diz "Pegasus".

No estado `ocioso`, o servidor separa as falas com o VAD (o mesmo fim de fala de `PEGASUS_VAD_SILENCIO_MS`), transcreve cada uma com o Whisper e olha a primeira palavra:

- **"Pegasus" seguido de mais texto** ("Pegasus, qual é o seu nome?"): o resto da frase é a pergunta. O servidor envia `state "pensando"` e segue um turno normal, com `stt` trazendo só a pergunta, sem a palavra.
- **Só "Pegasus":** o servidor responde "Oi?" (`state "falando"`, uma frase `tts_start`/áudio/`tts_end`, sem `emotion`) e abre a conversa (`conversation "conversando"` e `state "ouvindo"`). A fala seguinte é a pergunta, sem precisar repetir a palavra. Sem fala em `PEGASUS_VAD_SEM_FALA_MS`, volta a esperar o nome.
- **Qualquer outra fala:** é descartada na hora. O servidor não envia nada ao tablet, não registra nada no log e não guarda o áudio nem o texto. A fala também não entra na memória da sessão.
- **Fala com mais de 10 s:** é descartada sem transcrever, do mesmo jeito. Um chamado é curto; uma fala longa é conversa ou ruído da sala, que deixa o Whisper lento. A fala que continua depois do corte conta como fala nova.

### Conversa

Depois de cada resposta (e do "Oi?"), o servidor não volta a esperar o nome: ele envia `conversation "conversando"` e `state "ouvindo"`, e a próxima fala vira pergunta sem precisar de "Pegasus" (se a fala começar com o nome, ele é tirado da pergunta, como no estado `ocioso`). A memória da sessão segue valendo, então a pergunta pode depender da anterior ("e quantos anos você tem?").

- **Prazo:** `PEGASUS_CONVERSA_S` (padrão 8 s; 0 desliga a conversa) sem fala, contado no áudio que chega do tablet, isto é, a partir do momento em que ele termina de tocar a resposta e reabre o microfone. Depois do "Oi?", o prazo é `PEGASUS_VAD_SEM_FALA_MS`.
- **Renovação:** cada nova resposta envia outro `conversation "conversando"` e recomeça o prazo.
- **Fim por silêncio:** sem fala no prazo, o servidor envia `conversation "esperando_nome"` e `state "ocioso"`; daí em diante, só "Pegasus" abre a escuta de novo.
- **Despedida:** se a fala inteira for uma despedida ("tchau, Pegasus", "obrigado, é só isso", "até logo", "pode descansar"), o servidor não chama o LLM: envia `stt`, responde "Tchau! Até a próxima." (`state "falando"`, uma frase, sem `emotion`) e termina com `conversation "esperando_nome"` e `state "ocioso"`. Palavras de cortesia e o nome em volta não mudam isso ("ok, obrigado, tchau"). Já "Obrigado." sozinho ou "Tchau, mas antes me diz uma coisa" são perguntas normais. A despedida zera a memória da sessão. "Pegasus, tchau" vindo de `ocioso` também é despedida.
- **Outros fins:** `abort`, `error`, a queda do LLM (`state "desconectado"`) ou uma fala sem texto reconhecido (`stt` vazio) também encerram a conversa, com `conversation "esperando_nome"` antes do `state`.

No modo `toque` não há conversa: a mensagem `conversation` nunca é enviada, e "tchau" vai ao LLM como qualquer pergunta.

Valem as variações próximas que o Whisper produz: acentos e maiúsculas são ignorados ("Pégasus", "PEGASUS"), e grafias como "Pégaso", "Pegasos" ou "Pegassus" também valem. A palavra precisa abrir a frase, podendo vir só depois de um chamamento ("Ei, Pegasus", "Oi, Pegasus"): "Qual é o seu nome, Pegasus?" é descartada.

```
Tablet                                   Servidor
  │ ◄───── hello {activation:"palavra"} ── │
  │ ◄───────────────── state "ocioso" ──── │
  │ ══ áudio PCM contínuo ══════════════►  │   VAD separa as falas; Whisper transcreve
  │                                        │   "conversa qualquer" → descartada
  │                                        │   "Pegasus." →
  │ ◄───────────────── state "falando" ─── │
  │ ◄───────────── tts_start {"Oi?"} ───── │
  │ ◄══════════════════ áudio do "Oi?" ═══ │   o tablet fecha o microfone e toca
  │ ◄──────────────────────── tts_end ──── │
  │ ◄──── conversation "conversando" ───── │
  │ ◄───────────────── state "ouvindo" ─── │
  │ ══ áudio PCM (depois de tocar) ═════►  │   "que horas são?"
  │ ◄──────────────── state "pensando" ─── │
  │                ...                     │   turno normal
  │ ◄──── conversation "conversando" ───── │   prazo renovado
  │ ◄───────────────── state "ouvindo" ─── │
  │ ══ áudio PCM ═══════════════════════►  │   "e amanhã?" (sem "Pegasus")
  │                ...                     │   turno normal, prazo renovado
  │ ══ áudio PCM ═══════════════════════►  │   "tchau, Pegasus"
  │ ◄────────────────────── stt {text} ─── │
  │ ◄───────────────── state "falando" ─── │
  │ ◄─── tts_start {"Tchau! Até..."} ───── │   despedida fixa, sem LLM
  │ ◄──────────────────────── tts_end ──── │
  │ ◄─── conversation "esperando_nome" ─── │
  │ ◄───────────────── state "ocioso" ──── │   só "Pegasus" abre a escuta de novo
```

Enquanto uma fala está sendo verificada, um `listen_start` ou um `abort` a descarta. Áudio recebido em `pensando` ou `falando` é ignorado.

## Mensagens do tablet → servidor

### `hello`

Primeira mensagem da conexão, obrigatória em até 5 s.

```json
{
  "type": "hello",
  "version": 1,
  "token": "segredo-do-tablet",
  "device_id": "tablet-sala-01",
  "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1, "frame_ms": 20}
}
```

- `token`: um dos valores de `PEGASUS_TOKENS` no `pegasus.env` do servidor (separados por vírgula).
- `device_id`: identificação livre do tablet, usada nos registros.
- `audio`: formato que o tablet vai enviar; na versão 1 só `pcm_s16le`, 16 kHz, mono.

### `listen_start`

```json
{"type": "listen_start"}
```

Começa a captar. Se o servidor estiver em `pensando` ou `falando`, o turno em andamento é interrompido (como num `abort`) e a escuta começa.

Durante a escuta, o servidor:

- encerra a escuta sozinho quando a fala termina (VAD) e responde;
- volta a `ocioso`, sem responder, se não houver fala nenhuma em `PEGASUS_VAD_SEM_FALA_MS` (padrão 8 s) de áudio;
- encerra a escuta e responde ao chegar a 30 s de áudio.

### Áudio (binário)

Blocos de 20 ms de PCM a partir do `listen_start` (no modo `palavra`, o tempo todo, exceto enquanto toca a voz do robô). O tablet continua enviando até receber `state "pensando"` ou `state "ocioso"`; o que chegar depois disso é descartado. Para o Whisper, o servidor recorta o áudio em volta da fala detectada (300 ms antes, 200 ms depois).

### `listen_stop`

```json
{"type": "listen_stop"}
```

Opcional: encerra a escuta antes de o VAD decidir (por exemplo, por um toque na tela). O servidor transcreve e responde. Sem áudio recebido, volta a `ocioso`.

### `abort`

```json
{"type": "abort"}
```

Cancela a escuta ou a resposta em andamento, na hora:

- a geração do LLM é interrompida (o servidor fecha o fluxo e o vLLM aborta a requisição), assim como o pedido de emoção;
- o Piper para antes do próximo bloco de áudio, e nenhum áudio novo é enviado;
- o servidor fecha a frase aberta com `tts_end` e envia `state "ocioso"`, sem esperar mais que 500 ms pela limpeza do turno.

O servidor envia o áudio de cada frase mais rápido que o tempo real, então o tablet pode já ter recebido áudio que ainda não tocou: ao enviar `abort`, ele deve parar a reprodução e descartar esse áudio. O que o robô chegou a dizer fica na memória da sessão.

### `ping`

```json
{"type": "ping", "t": 1731430000123}
```

A cada 15 s. `t` é opcional e volta igual no `pong`. Sem nenhuma mensagem do tablet por 45 s, o servidor fecha a conexão.

## Mensagens do servidor → tablet

### `hello`

```json
{
  "type": "hello",
  "version": 1,
  "session_id": "3f2c9a7e",
  "audio": {"format": "pcm_s16le", "sample_rate": 22050, "channels": 1},
  "activation": "toque"
}
```

`audio` descreve o áudio que o servidor vai enviar. `activation` é o modo de ativação (`toque` ou `palavra`, ver "Ativação: toque ou palavra").

### `state`

```json
{"type": "state", "state": "ouvindo"}
```

Estados: `ocioso`, `ouvindo`, `pensando`, `falando`, `desconectado`.

`desconectado` vindo do servidor quer dizer que a conexão está de pé, mas o servidor de linguagem (vLLM) está fora do ar. O app também mostra `desconectado` quando a própria conexão cai. Ver "Servidor de linguagem fora do ar".

### `conversation`

```json
{"type": "conversation", "state": "conversando", "timeout_ms": 8000}
{"type": "conversation", "state": "esperando_nome"}
```

Só no modo `palavra` (ver "Conversa"). `conversando`: a escuta está aberta sem precisar do nome; `timeout_ms` é o prazo sem fala, contado depois que o tablet termina de tocar a resposta. `esperando_nome`: a conversa acabou e só "Pegasus" abre a escuta. Vem sempre logo antes do `state` correspondente (`ouvindo`; `ocioso` ou `desconectado`). Ao conectar, o tablet está em `esperando_nome`, sem mensagem. O app pode usar isso no rosto, por exemplo para mostrar que o robô ainda espera a continuação da conversa.

### `stt`

```json
{"type": "stt", "text": "Olá, robô! Qual é o seu nome?"}
```

Texto reconhecido. `text` vazio quando nada foi entendido; nesse caso o servidor volta a `ocioso` sem responder.

### `tts_start`

```json
{"type": "tts_start", "text": "Olá! Meu nome é Pegasus.", "sample_rate": 22050}
```

Início de uma frase. Os quadros binários seguintes são o áudio dela.

### Áudio (binário)

PCM da frase, em blocos de até 100 ms. A boca do rosto segue o volume (RMS) deste áudio.

### `tts_end`

```json
{"type": "tts_end"}
```

Fim do áudio da frase. Pode vir outra frase (`tts_start`) ou `state "ocioso"`.

### `pong`

```json
{"type": "pong", "t": 1731430000123}
```

### `error`

```json
{"type": "error", "message": "O servidor de linguagem não está disponível."}
```

Falha no turno (por exemplo, LLM desligado). A mensagem é em português e pode ser exibida ou falada. O servidor volta a `ocioso` em seguida; a conexão continua aberta.

Cada etapa tem um limite de tempo; a que passar dele encerra o turno com `error` "O servidor demorou demais para responder.":

| Etapa | Variável | Padrão |
| --- | --- | --- |
| Transcrição de uma fala (Whisper) | `PEGASUS_STT_LIMITE_MS` | 5 s |
| Cada pedaço do fluxo do LLM, inclusive o primeiro | `PEGASUS_LLM_LIMITE_MS` | 10 s |
| Síntese de uma frase (Piper) | `PEGASUS_TTS_LIMITE_MS` | 5 s |
| Turno inteiro, do fim da fala ao último áudio | `PEGASUS_TURNO_LIMITE_MS` | 60 s |

O que já foi falado fica na memória da sessão. Um envio ao tablet travado por 10 s fecha a conexão com o código 4008.

### `emotion`

```json
{"type": "emotion", "emotion": "feliz"}
```

Emoção a sobrepor ao estado do rosto durante a resposta. Valores: `neutro`, `feliz`, `triste`, `surpreso`, `pensativo`, `bravo`.

- **Uma por turno com resposta, assim que fica pronta:** chega depois de `stt`, antes ou durante a fala. O primeiro áudio não espera por ela. No modo `antes`, ela vem antes do primeiro `tts_start`. No modo `paralelo`, costuma chegar enquanto a primeira frase toca, entre o `tts_end` de uma frase e o `tts_start` da seguinte. O app a aplica ao rosto na hora, com o áudio tocando.
- **Origem:** o LLM escolhe a emoção chamando a ferramenta `definir_emocao(emocao)`. O servidor valida o valor contra a lista acima. Há dois modos (`PEGASUS_EMOCAO_MODO`):
  - `antes` (padrão): a própria requisição da fala oferece a ferramenta e o prompt pede que ela seja chamada antes de qualquer palavra da resposta.
  - `paralelo`: uma requisição própria, em paralelo com a fala, obriga a chamada.
- **Valor padrão:** o servidor envia `neutro` quando o LLM não chama a ferramenta, devolve um valor fora da lista ou falha. No modo `antes`, isso acontece se a primeira frase ficar pronta sem que a ferramenta tenha sido chamada; no modo `paralelo`, se a emoção não chegar em até `PEGASUS_EMOCAO_ESPERA_MS` (padrão 1000 ms) depois do primeiro áudio. Uma emoção que chegue depois disso é descartada.
- **Duração:** a emoção vale até o próximo `listen_start` ou até 10 s depois de o rosto voltar a `ocioso` com o áudio da resposta já tocado; então o rosto volta a `neutro`. O app não zera a emoção no próprio `state "ocioso"` porque o áudio da resposta ainda está tocando nesse momento (o servidor envia mais rápido do que toca). Turnos sem resposta (`stt` vazio, `error`, `abort` antes do primeiro áudio) e o "Oi?" da palavra de ativação não têm `emotion`.
- **Texto limpo:** o texto de `tts_start` e o áudio nunca contêm marcações de emoção nem de ferramenta. O servidor encerra a fala na primeira imitação de chamada escrita pelo LLM (`<tool_call>`, `definir_emocao(...)`, `{"emocao": ...}`) e remove marcas como `[feliz]` ou `*sorri*`, emojis e símbolos de markdown antes da síntese.

## Servidor de linguagem fora do ar

O servidor verifica o vLLM a cada 5 s. Com duas verificações seguidas sem resposta, ou com um turno que não conseguiu falar com ele, o servidor:

- interrompe o turno em andamento em todas as sessões (um turno que falhou envia antes o `error`);
- envia `state "desconectado"` a todos os tablets, e também no lugar do `ocioso` inicial a quem se conectar nesse período;
- deixa de escutar: responde a `listen_start` com `state "desconectado"` de novo e descarta o áudio, inclusive o da escuta contínua.

A conexão continua aberta, com `ping`/`pong`. Com o vLLM fora, o servidor o verifica a cada 2 s. Quando ele volta, o servidor envia `state "ocioso"`, e o robô volta a escutar sem o tablet precisar reconectar.

## Fechamento

| Código | Motivo |
| --- | --- |
| 1000 | Fechamento normal |
| 4000 | Erro de protocolo (JSON inválido, `hello` ausente ou fora de ordem, versão ou formato de áudio não suportado) |
| 4001 | Token inválido |
| 4008 | Tempo esgotado (sem `hello` em 5 s ou sem mensagens por 45 s) |

Ao perder a conexão, o app mostra `desconectado` e tenta reconectar com espera crescente.
