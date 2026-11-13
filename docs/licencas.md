# Licenças

Modelos, vozes e bibliotecas usados pelo Robô Pegasus. Confira a licença antes de adicionar qualquer item novo e registre aqui.

## Modelos

| Item | Origem | Licença | Observações |
| --- | --- | --- | --- |
| Whisper large-v3-turbo | [openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | MIT | Pesos originais da OpenAI. |
| Whisper large-v3-turbo (CTranslate2) | [mobiuslabsgmbh/faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | MIT | Conversão usada pelo faster-whisper, em `modelos/hub`. |
| Silero VAD v6 (ONNX) | [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | MIT | Arquivo `silero_vad_v6.onnx` que vem dentro do pacote faster-whisper (`faster_whisper/assets/`); usado em fluxo, na CPU, pelo onnxruntime. |
| Qwen3.8 27B | [Qwen/Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | Apache-2.0 | Modelo base. |
| Qwen3.8 27B AWQ INT4 | [cyankiwi/Qwen3.8-27B-AWQ-INT4](https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4) | Apache-2.0 | Quantização servida pelo vLLM. |

## Vozes

| Item | Origem | Licença | Observações |
| --- | --- | --- | --- |
| Piper `pt_BR-faber-medium` | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR/faber/medium) | Dataset CC0 | Ajustada a partir do modelo base `hifi_tts_92` (Hi-Fi TTS, leitora 92, conjunto de dados sob CC BY 4.0). Em `modelos/piper`. |

## Bibliotecas do servidor

| Item | Versão | Licença | Observações |
| --- | --- | --- | --- |
| faster-whisper | 1.2.1 | MIT | |
| CTranslate2 | 4.9.0 | MIT | |
| nvidia-cublas-cu12 | 12.9.3.13 | Licença NVIDIA (redistribuível) | cuBLAS 12 exigido pelo CTranslate2. |
| piper-tts | 1.8.0 | **GPL-3.0-or-later** | Importado como biblioteca. Sem efeito enquanto o servidor for de uso interno; se o código do servidor for distribuído, rever (ou chamar o Piper como subprocesso). |
| onnxruntime | 1.31.1 | MIT | Usado pelo Piper. |
| vLLM | 0.33.0 | Apache-2.0 | |
| openai (SDK Python) | 3.49.0 | Apache-2.0 | Cliente da API do vLLM. |
| PyTorch | 2.14.0 | BSD-3-Clause | |
| httpx | 0.28.1 | BSD-3-Clause | Cliente HTTP das ferramentas; já vinha como dependência do SDK openai. |

## Serviços e dados externos (ferramentas do LLM)

| Item | Origem | Licença / termos | Observações |
| --- | --- | --- | --- |
| SearXNG | [searxng/searxng](https://github.com/searxng/searxng), imagem Docker `searxng/searxng:2026.11.9-57ff753ad` (fixada pelo digest em `servidor/systemd/pegasus-busca.service`) | **AGPL-3.0-or-later** | Roda sem modificação, como serviço separado, só em 127.0.0.1; o servidor só faz pedidos HTTP a ele. Se o SearXNG for modificado e oferecido pela rede, o código modificado precisa ser publicado. Configuração em `servidor/searxng/settings.yml`. |
| Open-Meteo (API de previsão e de geocodificação) | [open-meteo.com](https://open-meteo.com/) | Dados CC BY 4.0; API gratuita para uso não comercial (até 10 mil pedidos/dia) | Sem chave. A atribuição é feita em voz: "Segundo o Open-Meteo, …". Uso comercial exige plano pago. |
| Wikipédia em português (API MediaWiki) | [pt.wikipedia.org](https://pt.wikipedia.org/w/api.php) | Textos CC BY-SA 4.0 | Atribuição em voz: "Segundo a Wikipédia, …". User-Agent `RoboPegasus/0.1 (+URL do repositório)`, como pede a política da Wikimedia. |
| Buscadores consultados pelo SearXNG | DuckDuckGo, Brave, Bing, Wikipedia | Termos de cada serviço | Trechos curtos (até 3 resultados) usados só para a resposta falada, sem guardar. Limite de 20 buscas/min para não sobrecarregar. |

## Bibliotecas do app

| Item | Versão | Licença | Observações |
| --- | --- | --- | --- |
| Flutter | 3.44.4 | BSD-3-Clause | Dart 3.12.2. |
| web_socket_channel | 3.0.3 | BSD-3-Clause | Cliente WebSocket. |
| record | 7.2.0 | BSD-3-Clause | Captura do microfone em PCM 16 kHz. |
| flutter_pcm_sound | 3.3.3 | Unlicense | Reprodução do PCM da resposta em fluxo. |
| wakelock_plus | 1.8.2 | BSD-3-Clause | Tela sempre ligada. |
| shared_preferences | 2.5.6 | BSD-3-Clause | Guarda o endereço do servidor e o token. |
