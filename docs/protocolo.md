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

Cada conexão é uma sessão. O servidor guarda uma memória curta da conversa da sessão: os últimos `PEGASUS_MEMORIA_TURNOS` turnos (padrão 6), cada um com a fala do usuário e o que o robô respondeu, e os envia ao LLM a cada turno. Uma resposta interrompida entra na memória só com as frases que chegaram a ser sintetizadas; um turno sem resposta (sem fala reconhecida, erro, `abort` antes da primeira frase) não entra.

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
  │ ◄──────────── emotion {"feliz"} ────── │   uma por turno, antes do 1º áudio
  │ ◄───────────────── state "falando" ─── │
  │ ◄─────────────── tts_start {frase} ─── │   ┐
  │ ◄══════════════ áudio PCM da frase ═══ │   │ uma vez por frase
  │ ◄──────────────────────── tts_end ──── │   ┘
  │ ◄───────────────── state "ocioso" ──── │
```

**Fim da fala:** o servidor detecta sozinho, com o Silero VAD, quando o usuário parou de falar: depois de `PEGASUS_VAD_SILENCIO_MS` (padrão 600 ms) de silêncio após a fala, a escuta termina e o servidor envia `state "pensando"`. O tablet não precisa enviar `listen_stop`, mas pode, para encerrar antes.

**Meio-duplex:** o tablet desliga o microfone ao receber `state "pensando"` (ou `state "ocioso"`) e só volta a ouvir com um novo `listen_start`. O servidor ignora áudio recebido fora do estado `ouvindo`.

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

Blocos de 20 ms de PCM a partir do `listen_start`. O tablet continua enviando até receber `state "pensando"` ou `state "ocioso"`; o que chegar depois disso é descartado. Para o Whisper, o servidor recorta o áudio em volta da fala detectada (300 ms antes, 200 ms depois).

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
  "audio": {"format": "pcm_s16le", "sample_rate": 22050, "channels": 1}
}
```

`audio` descreve o áudio que o servidor vai enviar.

### `state`

```json
{"type": "state", "state": "ouvindo"}
```

Estados: `ocioso`, `ouvindo`, `pensando`, `falando`. O estado `desconectado` existe só no app, quando a conexão cai.

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

### `emotion`

```json
{"type": "emotion", "emotion": "feliz"}
```

Emoção a sobrepor ao estado do rosto durante a resposta. Valores: `neutro`, `feliz`, `triste`, `surpreso`, `pensativo`, `bravo`.

- **Uma por turno com resposta, sempre antes do primeiro áudio:** chega depois de `stt` e antes de `state "falando"` e do primeiro `tts_start`. O app pode aplicá-la ao rosto antes de tocar qualquer som.
- **Origem:** o LLM escolhe a emoção chamando a ferramenta `definir_emocao(emocao)`. O servidor valida o valor contra a lista acima. Há dois modos (`PEGASUS_EMOCAO_MODO`):
  - `antes` (padrão): a própria requisição da fala oferece a ferramenta e o prompt pede que ela seja chamada antes de qualquer palavra da resposta.
  - `paralelo`: uma requisição própria, em paralelo com a fala, obriga a chamada.
- **Valor padrão:** o servidor envia `neutro` quando o LLM não chama a ferramenta, devolve um valor fora da lista ou falha. No modo `antes`, isso acontece se a primeira frase ficar pronta sem que a ferramenta tenha sido chamada; no modo `paralelo`, se a emoção não chegar em até `PEGASUS_EMOCAO_ESPERA_MS` (padrão 1000 ms) depois da primeira frase pronta. Uma emoção que chegue depois disso é descartada.
- **Duração:** a emoção vale até o fim do turno; ao receber `state "ocioso"` o app volta o rosto a `neutro`. Turnos sem resposta (`stt` vazio, `error`, `abort` antes do primeiro áudio) não têm `emotion`.
- **Texto limpo:** o texto de `tts_start` e o áudio nunca contêm marcações de emoção nem de ferramenta. O servidor encerra a fala na primeira imitação de chamada escrita pelo LLM (`<tool_call>`, `definir_emocao(...)`, `{"emocao": ...}`) e remove marcas como `[feliz]` ou `*sorri*`, emojis e símbolos de markdown antes da síntese.

## Fechamento

| Código | Motivo |
| --- | --- |
| 1000 | Fechamento normal |
| 4000 | Erro de protocolo (JSON inválido, `hello` ausente ou fora de ordem, versão ou formato de áudio não suportado) |
| 4001 | Token inválido |
| 4008 | Tempo esgotado (sem `hello` em 5 s ou sem mensagens por 45 s) |

Ao perder a conexão, o app mostra `desconectado` e tenta reconectar com espera crescente.
