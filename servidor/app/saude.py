"""Saúde do LLM: verifica o vLLM periodicamente e avisa as sessões quando ele cai ou volta."""

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from app.config import Config

log = logging.getLogger("pegasus.saude")

INTERVALO_S = 5.0  # entre verificações com o LLM no ar
INTERVALO_FORA_S = 2.0  # com o LLM fora, para voltar logo que ele subir
LIMITE_S = 2.0  # de cada verificação
FALHAS_PARA_CAIR = 2  # verificações seguidas sem resposta antes de declarar a queda

Verificador = Callable[[], Awaitable[bool]]
Aviso = Callable[[bool], Awaitable[None]]


def verificador_http(config: Config) -> Verificador:
    """GET /v1/models no vLLM: responde rápido mesmo com o LLM ocupado gerando."""
    cliente = httpx.AsyncClient(timeout=LIMITE_S)
    cabecalhos = {"Authorization": f"Bearer {config.llm_chave}"}
    url = config.llm_url.rstrip("/") + "/models"

    async def verificar() -> bool:
        try:
            resposta = await cliente.get(url, headers=cabecalhos)
        except httpx.HTTPError:
            return False
        return resposta.status_code == 200

    return verificar


class MonitorLLM:
    def __init__(self, verificar: Verificador, avisar: Aviso):
        self._verificar = verificar
        self._avisar = avisar
        self.disponivel = True
        self.desde = time.time()  # instante da última mudança
        self.quedas = 0
        self._falhas = 0
        self._laco: asyncio.Task | None = None
        self._avisos: set[asyncio.Task] = set()

    async def iniciar(self) -> None:
        """Verifica uma vez (para o primeiro tablet já saber o estado) e segue em fundo."""
        if not await self._verificar():
            self._mudar(False)
        self._laco = asyncio.create_task(self._vigiar())

    async def parar(self) -> None:
        tarefas = [t for t in (self._laco, *self._avisos) if t is not None]
        for tarefa in tarefas:
            tarefa.cancel()
        for tarefa in tarefas:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tarefa

    async def _vigiar(self) -> None:
        while True:
            await asyncio.sleep(INTERVALO_S if self.disponivel else INTERVALO_FORA_S)
            ok = await self._verificar()
            if ok:
                self._falhas = 0
                if not self.disponivel:
                    self._mudar(True)
            else:
                self._falhas += 1
                if self.disponivel and self._falhas >= FALHAS_PARA_CAIR:
                    self._mudar(False)

    async def suspeitar(self) -> bool:
        """Um turno não conseguiu falar com o LLM: verifica na hora e, sem resposta,
        declara a queda sem esperar a próxima verificação. Devolve a disponibilidade."""
        if self.disponivel and not await self._verificar():
            self._mudar(False)
        return self.disponivel

    def _mudar(self, disponivel: bool) -> None:
        self.disponivel = disponivel
        self.desde = time.time()
        self._falhas = 0
        if disponivel:
            log.info("LLM de volta; tablets liberados")
        else:
            self.quedas += 1
            log.error("LLM fora do ar; tablets em desconectado")
        # O aviso roda à parte: quem chamou pode estar dentro de um turno de sessão.
        aviso = asyncio.create_task(self._avisar(disponivel))
        self._avisos.add(aviso)
        aviso.add_done_callback(self._avisos.discard)
