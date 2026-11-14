# Plano do Robô Pegasus

## Fases

| Fase | Assunto | Estado |
| --- | --- | --- |
| 0 | Servidor: vLLM com o Qwen3.8 27B na GPU1 | concluída |
| 1–2 | Pipeline em fluxo (STT, LLM, TTS) e WebSocket `/ws` | concluída |
| 3 | Emoção (`definir_emocao`) e app com o rosto | concluída |
| 4 | Silero VAD, memória, persona, palavra de ativação, janela de conversa | concluída |
| 5 | Robustez: registro, limites de tempo, monitor do vLLM, carga, segurança; ferramentas de internet; publicação em `wss://…/pegasus/ws` | concluída (`docs/fase5.md`, `docs/ferramentas.md`) |
| **6** | **Piloto: um dia inteiro com público real** | **próxima** |

## Fase 6: piloto

**Objetivo:** pôr o robô num lugar público do campus por um dia inteiro, com pessoas que não conhecem o projeto, e responder a três perguntas:

1. Ele aguenta o dia sem intervenção técnica?
2. Ele entende e responde bem pessoas reais, com voz humana e ruído de verdade?
3. As pessoas gostam da conversa e entendem o que ele faz com a voz delas?

Até agora, as medidas de ativação e latência usaram voz sintética (Piper) ou poucas falas reais. O piloto é a primeira medição com voz humana em ambiente aberto.

Os itens marcados com **A decidir** dependem de quem coordena o piloto.

### 1. Local

Critérios:

- **Wi-Fi do campus** que alcance `wss://…/pegasus/ws`. Conferir antes, no ponto exato da montagem, com o próprio aparelho: o app abre a conexão, e o `pegasus-status` mostra o tablet conectado.
- **Tomada a menos de 2 m.** Tela sempre ligada com escuta contínua não passa um dia na bateria.
- **Ruído moderado.** Um corredor de passagem com conversa de fundo serve e é um bom teste. Uma cantina na hora do almoço ou um lugar com música ambiente atrapalha o VAD (a fala não "acaba") e o Whisper.
- **Movimento sem fila.** Um lugar por onde as pessoas passam e podem parar, como a entrada de uma biblioteca, um hall ou a recepção de um bloco, com espaço para 2 ou 3 pessoas em frente ao robô.
- **Parede atrás e luz sem reflexo na tela.** A parede evita que o aparelho seja derrubado. Sem sol direto na tela.
- **Autorização** da coordenação responsável pelo espaço.

**A decidir:** o local. Recomendação: um hall ou uma entrada com movimento moderado, perto do NumbERS, para a equipe atender rápido.

### 2. Público

- **Recomendação para o primeiro piloto:** estudantes maiores de idade e servidores do campus. A persona já fala em linguagem acessível, e o público adulto simplifica o consentimento (ver item 3).
- **Crianças e adolescentes** ficam para um segundo piloto. A LGPD (art. 14) exige que o tratamento de dados de crianças seja feito no melhor interesse delas, com consentimento específico de um dos pais ou responsável. Isso pede um termo próprio e acompanhamento.
- **Mediador:** uma pessoa da equipe fica perto do robô o tempo todo. Ela explica o aviso, ensina a chamar "Ei, Pegasus" e anota o que observa (item 5), sem conduzir a conversa.

**A decidir:** o público e se o piloto vai gerar publicação científica. Se for publicar resultados com pessoas (questionário e observação), consultar antes o Comitê de Ética em Pesquisa do IFG, porque pode ser preciso submeter à Plataforma Brasil. Isso vale principalmente para o questionário.

### 3. Aviso de escuta contínua (LGPD)

No modo `palavra`, o tablet envia ao servidor **todo** o áudio captado enquanto está ocioso. O servidor separa as falas com o VAD, transcreve cada uma e descarta as que não começam com "Pegasus". Quem passa perto é ouvido, mesmo sem falar com o robô. Por isso, o aviso deve estar visível **antes** de a pessoa chegar ao alcance do microfone.

O que o sistema faz com a voz (conferido no código em 2026-11-14):

| Dado | O que acontece |
| --- | --- |
| Áudio do microfone | Processado na memória do servidor do IFG. **Não é gravado** em disco. |
| Fala sem "Pegasus" | Transcrita e descartada na hora, sem registro (`sessao.py`). Falas com mais de 10 s são descartadas sem transcrever. |
| Conversa com o robô | Os últimos 6 turnos ficam na memória da sessão para dar contexto, por até 180 s. Somem ao fim da sessão ou quando a API reinicia. |
| Registro (`turnos.jsonl`) | Só tempos, contagens, nome do tablet e tipo do turno (lista fixa de campos em `registro.py`). **Nenhum texto** dito ou respondido. Guardado por 30 dias. |
| IA (fala → texto, resposta, voz) | Tudo roda no servidor do IFG. Nenhum serviço de IA de terceiros. |
| Ferramentas de internet | Na pergunta sobre clima, Wikipédia ou atualidades, **um termo de busca gerado a partir da pergunta** vai a serviços externos: Open-Meteo, Wikipédia e, pelo SearXNG, DuckDuckGo, Brave e Bing. O termo não leva a voz nem a identificação da pessoa. Sai pelo IP do servidor, com o User-Agent do projeto. |

**Base legal e encarregado:** o IFG é uma autarquia federal. A base legal (execução de política pública ou pesquisa, art. 7º e art. 23; ou consentimento) deve ser confirmada com o **encarregado de dados do IFG** antes do piloto. Levar a tabela acima para essa conversa.

**Proposta de cartaz** (A4 ou A3, ao lado do robô e na entrada do espaço):

> **Este robô está ouvindo.**
> O Pegasus é um robô de conversa do IFG (núcleo NumbERS). Para conversar, diga **"Ei, Pegasus"** e faça sua pergunta.
> O microfone fica ligado o tempo todo para ele perceber quando é chamado. O som é processado no servidor do IFG e **não é gravado**. O que é dito sem chamar o Pegasus é descartado na hora.
> Perguntas sobre clima, notícias ou a Wikipédia são pesquisadas na internet. Só o termo da busca é enviado, sem a sua voz.
> Não fale dados pessoais (CPF, endereço, saúde) para o robô.
> Dúvidas ou pedido para desligar: fale com a pessoa da equipe ao lado. Contato: [e-mail do projeto] · Encarregado de dados do IFG: [contato].

**Alternativa com menos exposição:** `PEGASUS_ATIVACAO=toque`. Só há escuta depois de alguém tocar na tela, então quem passa não é ouvido. O custo é a experiência ficar menos natural. Se o encarregado pedir, o piloto pode rodar no modo toque, ou alternar meio dia em cada modo para comparar.

**Botão de privacidade:** o mediador pode desligar a escuta na hora, a pedido de qualquer pessoa: basta tirar o app da tela ou rodar `pegasus-desligar` no servidor.

### 4. Montagem física

**Aparelho:** tablet Android de 10" ou mais (recomendado) ou celular Android. O rosto ocupa a tela cheia em paisagem; num celular ele funciona, mas é pequeno para ser visto a mais de 1 m. Se for um celular, usar um aparelho dedicado ao piloto, sem chip e sem contas pessoais.

**Caixa de som:**

- O alto-falante interno some num corredor. Uma caixa externa ajuda, mas o tipo de ligação importa:
  - **Com fio (P2 ou USB):** recomendada. Latência baixa, e os ~50 ms de atraso da boca (`app/lib/audio/volume.dart`) continuam valendo.
  - **Bluetooth:** acrescenta de 100 a 300 ms. A boca fica adiantada em relação ao som, e o primeiro som chega mais tarde (a meta de 1,5 s já ficou mais apertada). Se for o único jeito, medir a latência da caixa e ajustar o `atraso` antes do piloto.
- Caixa **atrás ou embaixo** do aparelho, virada para o público, não para o microfone. O meio-duplex impede que o robô ouça a própria voz enquanto fala, mas o eco da sala logo depois da fala pode chegar ao microfone quando a escuta reabre.
- Volume ajustado no local, com o ruído real: audível a 1,5 m sem incomodar quem passa.
- Caixa ligada na tomada. Desligar a função de economia de energia da caixa, se houver: muitas desligam sozinhas depois de minutos sem som.

**Microfone:** o do próprio aparelho, que capta melhor entre 0,5 m e 1,5 m. Marcar no chão ou na mesa onde a pessoa deve ficar (por exemplo, uma faixa a 1 m: "Fale daqui"). Microfone externo (USB) só se o teste de bancada mostrar falha com o ruído do local.

**Suporte:**

- Pedestal ou suporte de mesa com o rosto **na altura dos olhos** de um adulto em pé (cerca de 1,5 m), em paisagem, preso e sem poder ser levado.
- Cabos presos com fita, sem passar onde as pessoas pisam.

**Aparelho preparado:**

- Carregador ligado o dia todo.
- **Fixar app** (fixação de tela do Android) ligado, para o app não ser fechado por toque.
- Notificações, atualizações automáticas e economia de bateria desligadas para o app.
- Brilho fixo, alto o bastante para o ambiente.
- Wi-Fi do campus salvo e testado no local. Token do aparelho próprio do piloto, cadastrado em `PEGASUS_TABLETS` (ver `scripts/tokens.py`).

### 5. Teste de um dia inteiro

**Antes do dia:**

| Quando | O quê |
| --- | --- |
| D−7 | Local, público e aviso aprovados (itens 1–3). Conversa com o encarregado de dados. |
| D−3 | **Ensaio de bancada** de 2 h no próprio local, com a equipe: Wi-Fi, volume, distância, falas com ruído. Ajustar `PEGASUS_VAD_SILENCIO_MS` se cortar quem faz pausas. |
| D−1 | Conferir o servidor: `nvidia-smi` (GPU1 livre e GPU0 só com o SciTech Ear), `pegasus-status`, espaço em disco. Avisar os outros projetos do servidor sobre o dia do piloto. Imprimir o cartaz e as fichas de observação. |
| D, 30 min antes | `pegasus-ligar` (se estiverem desligados), `pegasus-status`, montagem, um teste de cada tipo: conversa, clima, Wikipédia, busca e despedida. |

**No dia (sugestão: das 8h às 18h):**

- **A cada hora**, alguém da equipe roda `pegasus-status` (pode ser do celular, por SSH) e anota: tablets conectados, turnos, mediana e p90 da latência, quedas do LLM e reinícios.
- **Mediador** com a ficha de observação (item 6) o tempo todo, em turnos de no máximo 2 h.
- **Pausa planejada** no almoço, para conferir o aparelho, a temperatura, o carregador e o registro.
- **Nenhuma mudança de código ou de configuração durante o dia.** Problemas vão para o diário e são corrigidos depois. Exceção: desligar o robô, se for preciso.

**Contingência:**

| Problema | O que fazer |
| --- | --- |
| Rosto em "desconectado" | O app reconecta sozinho. Se passar de 2 min: `pegasus-status`. Se o vLLM caiu, o systemd tenta 3 vezes em 10 min; depois, `pegasus-ligar`. |
| Wi-Fi do campus caiu | Anotar o horário. Ele volta sozinho quando a rede voltar. |
| Servidor reiniciou | As unidades não sobem sozinhas (sem `[Install]`): `pegasus-ligar`. |
| Resposta ofensiva ou inadequada | Anotar o horário e o assunto (não a fala da pessoa) e **desligar o robô**. Retomar só depois de avaliar o prompt. |
| Pedido de alguém para parar de ouvir | Atender na hora (item 3) e anotar. |

### 6. Coleta de feedback

Nada de gravação de áudio nem de transcrição para avaliar o piloto. As fontes são:

1. **Registro do servidor** (`~/.local/state/robo-pegasus/turnos.jsonl` do dia): turnos por tipo (`turno`, `ativacao`, `despedida`, `sem_fala`, `falha`, `interrompido`), latência por etapa (`ms`), ferramentas usadas, emoções, fala de reserva e repetições do LLM. Um script de resumo do dia fica para o começo da Fase 6.
2. **Ficha de observação do mediador** (papel ou planilha), uma linha por interação, **sem o conteúdo da conversa**: horário, número de pessoas, faixa etária aparente (adulto ou criança), se ativou na primeira tentativa, quantas vezes precisou repetir "Pegasus", se a resposta foi adequada (sim, mais ou menos, não), se cortou a fala da pessoa, ativação sem ninguém chamar (falso positivo) e comentários espontâneos ("muito lento", "não entendeu").
3. **Questionário curto e anônimo** por QR code no cartaz, em até 1 minuto:
   - Foi fácil começar a conversa? (1–5)
   - Ele entendeu o que você disse? (1–5)
   - As respostas foram úteis? (1–5)
   - A demora para responder incomodou? (1–5)
   - Você entendeu o aviso sobre o microfone? (sim / não)
   - Você conversaria com ele de novo? (sim / talvez / não)
   - Comentário livre (opcional; o formulário avisa para não colocar dados pessoais).
   
   Usar um formulário institucional do IFG, sem login e sem coletar e-mail.
4. **Diário técnico:** quedas, reinícios, rede, temperatura do aparelho, ações da contingência.

### 7. Critérios de sucesso

| Critério | Meta | Fonte |
| --- | --- | --- |
| Disponibilidade | Robô respondendo ≥ 95% do horário, sem nenhuma intervenção no servidor | Diário e `pegasus-status` |
| Latência (fim da fala → 1º som) | Mediana ≤ 1,0 s e p90 ≤ 1,5 s nos turnos sem ferramenta | `turnos.jsonl` |
| Latência com ferramenta | "Deixa eu ver…" sempre antes de 1,5 s | `turnos.jsonl` |
| Ativação com voz humana | ≥ 85% na 1ª tentativa | Ficha |
| Falso positivo | ≤ 1 ativação sem chamado por hora | Ficha |
| Respostas adequadas | ≥ 80% "sim" e ≤ 5% "não" | Ficha |
| Fala cortada pelo VAD | ≤ 10% das interações | Ficha |
| Falhas | `falha` ≤ 2% dos turnos; fala de reserva ≤ 5% | `turnos.jsonl` |
| Satisfação | Média ≥ 4 em "fácil começar" e "entendeu" | Questionário |
| Aviso | ≥ 80% entenderam o aviso | Questionário |
| Segurança | **Nenhuma** resposta ofensiva, nenhum incidente de privacidade, nenhum impacto no SciTech Ear (GPU0) | Diário |

Os itens de segurança são **eliminatórios**: um incidente basta para o piloto não ser aprovado, mesmo com o resto dentro da meta.

**Depois do piloto:** um `docs/fase6.md` com os números do dia, o que falhou e as propostas de ajuste, no mesmo formato de `docs/fase5.md`. Com os critérios atingidos, o passo seguinte é um piloto de vários dias ou com outro público (por exemplo, crianças, com o termo do item 2).
