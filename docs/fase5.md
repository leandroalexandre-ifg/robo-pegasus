# Fase 5: robustez do servidor (medidas de 2026-11-12)

## Teste de carga

`servidor/scripts/carga.py`: 3 tablets simulados no modo palavra, por 10 minutos, contra a API em produção (`127.0.0.1:8100`). Cada cliente mantém o microfone aberto em tempo real, fecha o microfone enquanto "toca" a resposta e sorteia falas geradas pelo Piper: pergunta com a palavra (60%), "Pegasus." seguido de pergunta (20%) e fala sem a palavra (20%). Durante o teste, um tablet real (`tablet-01`) também estava conectado.

As latências abaixo são as do servidor (`fala_ate_primeiro_audio` no `turnos.jsonl`), do fim real da fala ao envio do primeiro áudio. A medida do cliente sai cerca de 250 ms menor, porque o Piper põe silêncio no fim de cada WAV.

| Rodada | Turnos com resposta | Sem resposta | Mediana | p90 | Máx. | Acima de 1,5 s |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (código inicial) | 126 | **17 (12%)**: o LLM não disse nada | 1346 ms | 1636 ms | 1884 ms | 24 |
| 2 (repete o pedido) | 140 | 0, mas 10 com a fala de reserva | 1339 ms | 1591 ms | 2015 ms | 22 |
| 3 (repete sem a memória) | 132 | 0, e nenhuma fala de reserva | 1345 ms | 1548 ms | 1707 ms | 16 (12%) |
| 4 (propostas 1, 2 e 4 aplicadas; ver abaixo) | 139 | 0, e nenhuma fala de reserva | **817 ms** | 974 ms | 1273 ms | 0 |

Na rodada 3, todas as falas tiveram o resultado esperado:

| Fala | Total | Resultado |
| --- | --- | --- |
| "Pegasus, pergunta" | 94 | 94 respostas |
| Pergunta depois do "Oi?" | 38 | 38 respostas |
| Só "Pegasus." | 38 | 38 "Oi?" (cerca de 420 ms medidos no cliente) |
| Fala sem a palavra | 53 | 53 descartadas, sem rastro no log |

**Memória.** A memória da GPU1 ficou entre 29,3 e 29,6 GB nas três rodadas, sobrando cerca de 3 GB livres. O Whisper da API ficou fixo em 2594 MiB, e o vLLM cresceu 100 MiB uma vez, entre as rodadas. A API usa cerca de 1,1 GB de RAM. A utilização da GPU, amostrada a cada 5 s, teve mediana de 0%: com 3 tablets a GPU fica ociosa a maior parte do tempo.

### Achado: o LLM às vezes não responde nada

O Qwen3.8 às vezes gera só o token de fim de turno: a resposta vem vazia, com 1 token e `finish_reason` igual a `stop`. Isso depende do conteúdo da memória da sessão. Com certas conversas, chegou a 55% das tentativas para uma mesma pergunta, e nunca aconteceu sem memória (0 em 60). `min_tokens` não resolve: a resposta sai com 2 tokens ("Est", "Um").

Correção (`turno.falar`): quando o LLM termina sem nenhuma frase, o pedido é repetido uma vez sem a memória. Se ainda vier vazio, o robô diz "Desculpe, me perdi. Pode perguntar de novo?", e essa fala não entra na memória. Na rodada 3, 9 de 132 turnos (7%) precisaram da repetição, e ela custa cerca de 300 ms nesses turnos. Os turnos repetidos têm `llm_repeticao` em `ms` no registro.

## Por que o modo palavra leva ~1,3 s até o primeiro áudio

A diferença para o toque não vem do modo palavra. Os ~0,7 s do toque foram medidos com `listen_stop` enviado no fim exato da fala, o que pula a espera do VAD. Medido pelo VAD, o toque leva os mesmos 1,27 s. Depois de o servidor decidir que a fala acabou, o caminho é o mesmo nos dois modos.

Etapas na rodada 3 (medianas, em ms desde o fim da fala detectado):

| Etapa | Tempo |
| --- | --- |
| Silêncio esperado pelo VAD (`PEGASUS_VAD_SILENCIO_MS`) | 608 (antes do zero) |
| Whisper | 45 |
| LLM: primeiro token | 308 |
| LLM: primeira frase pronta | 483 |
| Emoção pronta (pedido paralelo) | 737 |
| **Primeiro áudio** | **737** |

Em 131 de 132 turnos, o primeiro áudio ficou esperando a emoção: a frase e a voz dela já estavam prontas cerca de 250 ms antes. Os dois maiores custos são a espera do VAD (608 ms) e a emoção (cerca de 250 ms).

### Propostas, da mais para a menos vantajosa

1. **Emoção por escolha estruturada** (cerca de −250 ms). Hoje a emoção é uma chamada de ferramenta obrigatória, com cerca de 32 tokens em XML: 534 ms em mediana, sem carga. Com saída estruturada de escolha única (`structured_outputs: {"choice": [...]}` no vLLM), o modelo escreve só o nome da emoção: 112 ms. Assim ela chega bem antes da primeira frase e deixa de atrasar o áudio. O que falta: no teste rápido, com um prompt improvisado, "meu cachorro morreu" saiu como "surpreso". O prompt precisa de ajuste e de uma avaliação de qualidade. Também muda a regra do CLAUDE.md de que a emoção vem pela ferramenta `definir_emocao`. É uma decisão sua.
2. **Começar a responder antes do fim do silêncio** (cerca de −300 ms). Depois de ~300 ms de silêncio, o servidor já transcreve e começa a gerar, mas só envia algo quando completar os 600 ms. Se a pessoa voltar a falar, cancela. Isso esconde o pipeline dentro da espera sem encurtá-la, então não aumenta o risco de cortar quem faz pausas. O custo são pedidos ao LLM cancelados quando a pessoa retoma a fala.
3. **Encurtar o silêncio do VAD para 450–500 ms** (−100 a −150 ms). É simples, mas a sua gravação real tinha uma pausa de cerca de 670 ms no meio da frase, que já passa dos 600 ms atuais. Só vale depois de testar com fala real no tablet.
4. **Primeira frase menor** (−50 a −100 ms). Cortar a primeira frase na primeira vírgula leva o primeiro trecho ao Piper mais cedo.

As propostas 1 e 2 juntas levariam a mediana de ~1,35 s para cerca de 0,8 s.

### Depois dos ajustes (rodada 4, 2026-11-13)

Decisões aplicadas: (1) o primeiro áudio não espera mais a emoção, que vai assim que chega, mesmo no meio da fala (em vez da saída estruturada); (2) prévia: o turno começa com 300 ms de silêncio (`PEGASUS_VAD_PREVIA_MS`) e só envia com os 600 ms completos; (4) a primeira frase termina na primeira vírgula; e falas da escuta contínua acima de 10 s são descartadas sem transcrever. O silêncio do VAD (proposta 3) ficou em 600 ms.

Mesma carga da rodada 3 (3 clientes, 10 min, modo palavra): 234 falas, todas com o resultado esperado (99/99 perguntas, 40/40 seguintes, 40/40 "Oi?", 55/55 descartadas). Todos os 139 turnos com resposta passaram pela prévia; 7 repetiram o pedido ao LLM mudo, sem nenhuma fala de reserva.

| Medida (servidor) | Rodada 3 | Rodada 4 |
| --- | --- | --- |
| Fim da fala → primeiro áudio, mediana | 1345 ms | **817 ms** |
| p90 / máximo | 1548 / 1707 ms | 974 / 1273 ms |
| Acima de 1,5 s | 16 de 132 | 0 de 139 |
| "Oi?" (só a palavra), mediana | 667 ms | 618 ms |
| Memória da GPU1 | 29,3–29,6 GB | 29,4–29,6 GB |

Etapas na rodada 4, em ms desde a prévia (que começa com 320 ms de silêncio):

| Etapa | Mediana |
| --- | --- |
| Whisper | 45 |
| LLM: primeiro token | 234 |
| Fim da fala confirmado pelo VAD (`liberado`) | 281 |
| LLM: primeira frase pronta (até a vírgula) | 461 |
| Primeiro áudio pronto e enviado | 496–497 |
| Emoção | 749, depois do primeiro áudio em 138 de 139 turnos |

Agora o que limita é o LLM: o primeiro áudio sai, em mediana, 215 ms depois de o VAD confirmar o fim da fala, e quase todo esse tempo é a geração da primeira frase. Em nenhum turno o áudio ficou pronto antes da confirmação. Pelos clientes, a mediana até o primeiro som foi de 559 ms para perguntas com a palavra (o Piper põe silêncio no fim de cada WAV, e por isso a medida do cliente sai menor).

### Outro achado: Whisper lento com ruído longo

Às 21:55:42, a verificação da palavra no `tablet-01` passou do limite de 5 s do Whisper. A fala foi descartada e o robô seguiu normalmente. A causa provável é um trecho longo de ruído da sala: no modo palavra, uma fala pode ter até 30 s, e o Whisper inventa texto em repetição. Proposta: limitar a fala da escuta contínua a ~10 s e, depois de passar disso, cortar ou descartar.

## Recuperação do vLLM

Teste com um proxy TCP na frente do vLLM, com uma instância de teste: matar o proxy simula a queda.

| Situação | Tempo até o tablet saber |
| --- | --- |
| O vLLM cai com o robô ocioso (duas verificações a cada 5 s) | 6,6 s até `state "desconectado"` |
| Um turno encontra o vLLM fora | na hora: `error` e depois `state "desconectado"` em todas as sessões |
| O vLLM volta (verificação a cada 2 s) | 1,6 s até `state "ocioso"`; o turno seguinte respondeu normalmente |

## Registro e status

- `~/.local/state/robo-pegasus/turnos.jsonl` (`PEGASUS_LOG_PASTA`): uma linha JSON por turno, só com tempos, contagens e identificadores. Troca de arquivo à meia-noite e guarda 30 dias (`PEGASUS_LOG_DIAS`). O log geral (journald) também deixou de gravar texto da conversa, argumentos da ferramenta e a duração das falas descartadas.
- `pegasus-status` (`servidor/scripts/pegasus-status`, com link em `~/.local/bin`): serviços, vLLM, API (via `/status`, só local), GPU1 e turnos do dia. Sai com 1 se o vLLM ou a API não respondem.
