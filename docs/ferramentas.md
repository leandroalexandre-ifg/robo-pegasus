# Ferramentas de internet do LLM

Resumo do funcionamento em `CLAUDE.md` ("Ferramentas de internet do LLM"); código em `servidor/app/ferramentas/`.

## Medição (2026-11-13)

`servidor/scripts/medir_ferramentas.py`, pela API em produção (modo palavra, emoção em paralelo), uma conexão por pergunta, voz do Piper reamostrada para 16 kHz. Tempos do fim da fala, vistos pelo cliente, incluindo os 600 ms do VAD. Duas rodadas de 24 perguntas.

| Grupo | Turnos | Com "Deixa eu ver…" | 1º som (mediana / p90 / máx) | Resposta (mediana / p90 / máx) |
| --- | --- | --- | --- | --- |
| Sem ferramentas, antes (desligadas) | 17 | – | 660 / 724 / 724 ms | igual |
| Sem ferramentas, depois (ligadas) | 12 | 0 | 782 / 808 / 810 ms | igual |
| Data e hora (`[agora: …]`) | 6 | 0 | 782 / 881 / 881 ms | igual |
| Clima | 9 | 8 | 783 / 870 / 870 ms | 1262 / 3004 / 3004 ms |
| Wikipédia | 9 | 4 | 855 / 1140 / 1140 ms | 1140 / 1589 / 1589 ms |
| Busca | 10 | 8 | 804 / 959 / 959 ms | 2075 / 2443 / 2443 ms |

- O primeiro som ficou abaixo da meta de 1,5 s em todos os turnos (máximo de 1140 ms).
- Só por estarem ligadas, as ferramentas somam ~120 ms aos turnos sem consulta. O vLLM não reaproveita o prefixo com o Qwen3.8 (híbrido, "Prefix cache hit rate: 0.0%"), então as definições (~400 tokens) são processadas em todo turno.
- As consultas levaram: clima 0 ms (cache) a 1737 ms (cidade nova, sem cache); Wikipédia ~250–330 ms; busca 575–1055 ms. Depois da consulta, a segunda requisição leva ~300–500 ms até o primeiro áudio da resposta.
- O modelo nem sempre consulta: "o que é a fotossíntese?" e "quem ganhou a última Copa do Mundo?" foram respondidas de memória.
- Erros vistos foram do Whisper com a voz sintética, não das ferramentas: "Santos Dumont" virou "Santos do Monte" (a Wikipédia devolveu o município) e "Tiradentes" virou "quem tirou os dentes".
- GPU1 sem mudança (29,6 GB). O contêiner do SearXNG usa ~120 MB de RAM e quase nada de CPU.
- Teste de páginas maliciosas (ordem para dizer que foi hackeado, falso prompt de sistema com tokens do template, ordem para chamar outra ferramenta): 9 de 9 respostas trouxeram só os fatos da página.
