"""Estado de um tablet conectado e execução dos seus turnos de conversa."""

import asyncio
import contextlib
import json
import logging
import secrets

import numpy as np
import openai
from fastapi import WebSocket

from app.config import Config
from app.pipeline.turno import Turno, falar, transcrever
from app.wav import TAXA_ENTRADA

log = logging.getLogger("pegasus.sessao")

MAX_AUDIO_S = 30
_MAX_BYTES = MAX_AUDIO_S * TAXA_ENTRADA * 2
BLOCO_SAIDA_S = 0.1


class Sessao:
    def __init__(self, ws: WebSocket, config: Config, device_id: str):
        self.ws = ws
        self.config = config
        self.device_id = device_id
        self.id = secrets.token_hex(4)
        self.estado = "ocioso"
        self._audio = bytearray()
        self._turno: asyncio.Task | None = None
        self._frase_aberta = False
        # O receptor de mensagens e a tarefa do turno enviam pela mesma conexão.
        self._envio = asyncio.Lock()

    async def enviar_json(self, mensagem: dict) -> None:
        async with self._envio:
            await self.ws.send_text(json.dumps(mensagem, ensure_ascii=False))

    async def enviar_audio(self, pcm: bytes) -> None:
        async with self._envio:
            await self.ws.send_bytes(pcm)

    async def mudar_estado(self, estado: str) -> None:
        self.estado = estado
        await self.enviar_json({"type": "state", "state": estado})

    async def ao_listen_start(self) -> None:
        await self.cancelar_turno()  # falar por cima interrompe o robô
        self._audio.clear()
        await self.mudar_estado("ouvindo")

    def ao_audio(self, dados: bytes) -> None:
        if self.estado != "ouvindo":
            return  # meio-duplex: áudio fora da escuta é descartado
        espaco = _MAX_BYTES - len(self._audio)
        if espaco > 0:
            self._audio += dados[:espaco]

    async def ao_listen_stop(self) -> None:
        if self.estado != "ouvindo":
            return
        pcm = bytes(self._audio[: len(self._audio) // 2 * 2])
        self._audio.clear()
        if not pcm:
            await self.mudar_estado("ocioso")
            return
        await self.mudar_estado("pensando")
        self._turno = asyncio.create_task(self._responder(pcm, Turno()))

    async def ao_abort(self) -> None:
        await self.cancelar_turno()
        self._audio.clear()
        await self.mudar_estado("ocioso")

    async def cancelar_turno(self) -> None:
        if self._turno is not None and not self._turno.done():
            self._turno.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._turno
            log.info("sessão %s: turno interrompido", self.id)
        self._turno = None
        if self._frase_aberta:
            self._frase_aberta = False
            await self.enviar_json({"type": "tts_end"})

    async def _responder(self, pcm: bytes, turno: Turno) -> None:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            texto = await transcrever(audio, self.config, turno)
            await self.enviar_json({"type": "stt", "text": texto})
            if texto:
                await self._falar(texto, turno)
            await self.mudar_estado("ocioso")
        except asyncio.CancelledError:
            raise
        except openai.APIError as e:
            log.error("sessão %s: falha no LLM: %s", self.id, e)
            await self._falhar("O servidor de linguagem não está disponível.")
        except Exception:
            log.exception("sessão %s: falha no turno", self.id)
            await self._falhar("Ocorreu um erro no servidor.")
        else:
            self._registrar(turno, len(audio) / TAXA_ENTRADA)

    async def _falar(self, texto: str, turno: Turno) -> None:
        passo = None
        async for bloco in falar(texto, self.config, turno):
            if self.estado != "falando":
                await self.mudar_estado("falando")
            passo = passo or int(bloco.taxa * BLOCO_SAIDA_S) * 2
            self._frase_aberta = True
            await self.enviar_json(
                {"type": "tts_start", "text": bloco.frase, "sample_rate": bloco.taxa}
            )
            for i in range(0, len(bloco.pcm), passo):
                await self.enviar_audio(bloco.pcm[i : i + passo])
                turno.marcar("primeiro_envio")
            await self.enviar_json({"type": "tts_end"})
            self._frase_aberta = False

    async def _falhar(self, mensagem: str) -> None:
        # A conexão pode já ter caído; nesse caso não há a quem avisar.
        with contextlib.suppress(Exception):
            if self._frase_aberta:
                self._frase_aberta = False
                await self.enviar_json({"type": "tts_end"})
            await self.enviar_json({"type": "error", "message": mensagem})
            await self.mudar_estado("ocioso")

    def _registrar(self, turno: Turno, duracao_s: float) -> None:
        medidas = {k: round(v * 1000) for k, v in turno.tempos.items()}
        medidas["tts_soma"] = round(turno.tts_s * 1000)
        log.info(
            "turno %s",
            json.dumps(
                {
                    "sessao": self.id,
                    "tablet": self.device_id,
                    "audio_s": round(duracao_s, 2),
                    "frases": len(turno.frases),
                    "ms": medidas,
                },
                ensure_ascii=False,
            ),
        )
        log.debug("sessão %s: %r → %r", self.id, turno.texto_usuario, turno.resposta)
