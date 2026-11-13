# Ferramentas de internet do LLM

Resumo do funcionamento em `CLAUDE.md` ("Ferramentas de internet do LLM"); código em `servidor/app/ferramentas/`.

## Medição com o cache de prefixo aquecido (2026-11-13, tarde)

Mesmo método da medição abaixo, depois do `--prefix-match-unit 16` no vLLM, do aquecimento do trecho fixo do prompt (`servidor/app/aquecimento.py`), do clima citado como "a previsão do tempo" e do prompt novo da busca. Taxa de acerto do cache no vLLM: ~72–76% (era 0%).

| Grupo | Turnos válidos | Com "Deixa eu ver…" | 1º som (mediana / p90 / máx) | Resposta (mediana / p90 / máx) |
| --- | --- | --- | --- | --- |
| Sem ferramentas | 10 | 0 | 630 / 1092 / 1092 ms | igual |
| Data e hora | 5 | 0 | 610 / 630 / 630 ms | igual |
| Clima | 7 | 6 | 612 / 631 / 631 ms | 980 / 2686 / 2686 ms |
| Wikipédia | 10 | 6 | 642 / 673 / 673 ms | 1004 / 1553 / 1553 ms |
| Busca | 10 | 9 | 612 / 683 / 683 ms | 1386 / 2117 / 2117 ms |

- Sem consulta, a mediana caiu de 782 para 630 ms, abaixo dos 660 ms de antes das ferramentas. O máximo de 1092 ms foi o primeiro turno depois de reiniciar a API, com o cache ainda frio; sem ele, o máximo foi 652 ms.
- A resposta com busca caiu de 2075 para 1386 ms de mediana. A primeira frase depois da consulta também se beneficia do cache, porque a segunda rodada (sem ferramentas) é aquecida.
- 6 das 48 falas foram descartadas antes do LLM: o Whisper não reconheceu "Pegasus" na voz sintética, que varia a cada síntese. Esse trecho do pipeline não mudou.
- Teste só da escolha da ferramenta, com 10 perguntas de fatos recentes (último, atual, hoje, cargos, resultados, preços), 3 vezes cada: busca em 30 de 30; o modelo respondeu de memória antes de buscar em 1 de 30.

## Medição (2026-11-13)

`servidor/scripts/medir_ferramentas.py`, pela API em produção (modo palavra, emoção em paralelo), uma conexão por pergunta, voz do Piper reamostrada para 16 kHz. Tempos do fim da fala, vistos pelo cliente, incluindo os 600 ms do VAD. Duas rodadas de 24 perguntas.

| Grupo | Turnos | Com "Deixa eu ver…" | 1º som (mediana / p90 / máx) | Resposta (mediana / p90 / máx) |
| --- | --- | --- | --- | --- |
| Sem ferramentas, antes (desligadas) | 17 | – | 660 / 724 / 724 ms | igual |
| Sem ferramentas, depois (ligadas) | 12 | 0 | 782 / 808 / 810 ms | igual |
| Data e hora (`[agora: …]`) | 6 | 0 | 782 / 881 / 881 ms | igual |
| Clima (citado como Open-Meteo) | 9 | 8 | 783 / 870 / 870 ms | 1262 / 3004 / 3004 ms |
| Wikipédia | 9 | 4 | 855 / 1140 / 1140 ms | 1140 / 1589 / 1589 ms |
| Busca | 10 | 8 | 804 / 959 / 959 ms | 2075 / 2443 / 2443 ms |

- O primeiro som ficou abaixo da meta de 1,5 s em todos os turnos (máximo de 1140 ms).
- Só por estarem ligadas, as ferramentas somam ~120 ms aos turnos sem consulta. O vLLM não reaproveita o prefixo com o Qwen3.8 (híbrido, "Prefix cache hit rate: 0.0%"), então as definições (~400 tokens) são processadas em todo turno.
- As consultas levaram: clima 0 ms (cache) a 1737 ms (cidade nova, sem cache); Wikipédia ~250–330 ms; busca 575–1055 ms. Depois da consulta, a segunda requisição leva ~300–500 ms até o primeiro áudio da resposta.
- O modelo nem sempre consulta: "o que é a fotossíntese?" e "quem ganhou a última Copa do Mundo?" foram respondidas de memória.
- Erros vistos foram do Whisper com a voz sintética, não das ferramentas: "Santos Dumont" virou "Santos do Monte" (a Wikipédia devolveu o município) e "Tiradentes" virou "quem tirou os dentes".
- GPU1 sem mudança (29,6 GB). O contêiner do SearXNG usa ~120 MB de RAM e quase nada de CPU.
- Teste de páginas maliciosas (ordem para dizer que foi hackeado, falso prompt de sistema com tokens do template, ordem para chamar outra ferramenta): 9 de 9 respostas trouxeram só os fatos da página.
