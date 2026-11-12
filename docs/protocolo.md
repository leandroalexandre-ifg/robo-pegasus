# Protocolo tablet ↔ servidor

Este documento é a fonte da verdade do protocolo. Ao mudar o protocolo, atualize este documento, o servidor (`servidor/app/`) e o app (`app/lib/conexao/`) no mesmo commit.

**Versão do protocolo:** 1

## Conexão

- WebSocket em `/ws`. O servidor escuta em `127.0.0.1:8100` (`PEGASUS_HOST` e `PEGASUS_PORTA_API`). O tablet chega a ele por túnel SSH, porta liberada ou VPN.
- Uma conexão por tablet. Na mesma conexão trafegam:
  - **quadros de texto**: controle, em JSON, sempre com o campo `type`;
  - **quadros binários**: áudio PCM, sem cabeçalho.
- Campos desconhecidos devem ser ignorados, para permitir evolução sem quebrar o outro lado.

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
  │ ── listen_stop ─────────────────────►  │
  │ ◄──────────────── state "pensando" ─── │
  │ ◄────────────────────── stt {text} ─── │
  │ ◄───────────────── state "falando" ─── │
  │ ◄─────────────── tts_start {frase} ─── │   ┐
  │ ◄══════════════ áudio PCM da frase ═══ │   │ uma vez por frase
  │ ◄──────────────────────── tts_end ──── │   ┘
  │ ◄───────────────── state "ocioso" ──── │
```

**Meio-duplex:** o tablet desliga o microfone ao receber `state "pensando"` e só volta a ouvir com um novo `listen_start`. O servidor ignora áudio recebido fora do estado `ouvindo`.

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

### Áudio (binário)

Blocos de 20 ms de PCM entre `listen_start` e `listen_stop`. O servidor guarda no máximo 30 s por turno; o excedente é descartado.

### `listen_stop`

```json
{"type": "listen_stop"}
```

Fim da fala. O servidor transcreve e responde. Sem áudio recebido, volta a `ocioso`.

### `abort`

```json
{"type": "abort"}
```

Cancela a escuta ou a resposta em andamento. O servidor para de enviar áudio, fecha a frase aberta com `tts_end` e envia `state "ocioso"`. O tablet deve descartar o áudio ainda não tocado.

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

### `emotion` (planejada)

```json
{"type": "emotion", "emotion": "feliz"}
```

Ainda não implementada. Virá da ferramenta `definir_emocao` do LLM. Emoções: `neutro`, `feliz`, `triste`, `surpreso`, `pensativo`, `bravo`.

## Fechamento

| Código | Motivo |
| --- | --- |
| 1000 | Fechamento normal |
| 4000 | Erro de protocolo (JSON inválido, `hello` ausente ou fora de ordem, versão ou formato de áudio não suportado) |
| 4001 | Token inválido |
| 4008 | Tempo esgotado (sem `hello` em 5 s ou sem mensagens por 45 s) |

Ao perder a conexão, o app mostra `desconectado` e tenta reconectar com espera crescente.
