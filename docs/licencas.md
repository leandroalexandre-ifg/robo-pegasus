# Licenças

Modelos, vozes e bibliotecas usados pelo Robô Pegasus. Confira a licença antes de adicionar qualquer item novo e registre aqui.

## Modelos

| Item | Origem | Licença | Observações |
| --- | --- | --- | --- |
| Whisper large-v3-turbo | [openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | MIT | Pesos originais da OpenAI. |
| Whisper large-v3-turbo (CTranslate2) | [mobiuslabsgmbh/faster-whisper-large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | MIT | Conversão usada pelo faster-whisper, em `modelos/hub`. |
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

## Bibliotecas do app

| Item | Versão | Licença | Observações |
| --- | --- | --- | --- |
| Flutter | 3.44.4 | BSD-3-Clause | Dart 3.12.2. |
| web_socket_channel | 3.0.3 | BSD-3-Clause | Cliente WebSocket. |
| record | 7.2.0 | BSD-3-Clause | Captura do microfone em PCM 16 kHz. |
| flutter_pcm_sound | 3.3.3 | Unlicense | Reprodução do PCM da resposta em fluxo. |
| wakelock_plus | 1.8.2 | BSD-3-Clause | Tela sempre ligada. |
| shared_preferences | 2.5.6 | BSD-3-Clause | Guarda o endereço do servidor e o token. |
