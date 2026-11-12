"""Detecção do início e do fim da fala com o Silero VAD, em fluxo."""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.config import Config
from app.wav import TAXA_ENTRADA

BLOCO = 512  # amostras por inferência do Silero a 16 kHz (32 ms)
_CONTEXTO = 64  # amostras do bloco anterior que o modelo v6 espera junto de cada bloco
BLOCO_S = BLOCO / TAXA_ENTRADA
FALA_MIN_S = 0.1  # fala contínua mínima para valer como início (ignora estalos)

_sessao = None


def _carregar_sessao():
    """Modelo ONNX do Silero VAD que vem com o faster-whisper (MIT), na CPU."""
    global _sessao
    if _sessao is None:
        import faster_whisper
        import onnxruntime

        caminho = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
        opcoes = onnxruntime.SessionOptions()
        opcoes.inter_op_num_threads = 1
        opcoes.intra_op_num_threads = 1
        opcoes.log_severity_level = 4
        _sessao = onnxruntime.InferenceSession(
            str(caminho), providers=["CPUExecutionProvider"], sess_options=opcoes
        )
    return _sessao


class _Silero:
    """Probabilidade de fala de cada bloco, guardando o estado do modelo entre blocos."""

    def __init__(self):
        self._sessao = _carregar_sessao()
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._contexto = np.zeros(_CONTEXTO, dtype=np.float32)

    def __call__(self, bloco: np.ndarray) -> float:
        entrada = np.concatenate([self._contexto, bloco])[None, :]
        saida, self._h, self._c = self._sessao.run(
            None, {"input": entrada, "h": self._h, "c": self._c}
        )
        self._contexto = bloco[-_CONTEXTO:]
        return float(saida.ravel()[0])


def preparar() -> None:
    """Carrega o modelo na subida do servidor, para o primeiro turno não esperar."""
    _carregar_sessao()


class DetectorFala:
    """Recebe o PCM do microfone e avisa quando a fala começa e quando termina.

    A fala começa com FALA_MIN_S de blocos acima do limiar e termina depois de
    `vad_silencio_s` de blocos abaixo de limiar - 0,15 (histerese do Silero).
    Os instantes são contados em amostras do áudio recebido, não no relógio."""

    def __init__(self, config: Config, probabilidade: Callable[[np.ndarray], float] | None = None):
        self._prob = probabilidade or _Silero()
        self._limiar = config.vad_limiar
        self._limiar_silencio = max(config.vad_limiar - 0.15, 0.01)
        self._blocos_silencio = max(1, round(config.vad_silencio_s / BLOCO_S))
        self._blocos_fala_min = max(1, round(FALA_MIN_S / BLOCO_S))
        self._pendente = np.zeros(0, dtype=np.float32)
        self._amostras = 0  # amostras já avaliadas
        self._seguidos_fala = 0
        self._seguidos_silencio = 0
        self.inicio: int | None = None  # amostra em que a fala começou
        self.fim: int | None = None  # amostra em que começou o silêncio final
        self.terminou = False

    @property
    def falou(self) -> bool:
        return self.inicio is not None

    @property
    def silencio_s(self) -> float:
        """Silêncio desde o fim da fala até a última amostra avaliada."""
        return 0.0 if self.fim is None else (self._amostras - self.fim) / TAXA_ENTRADA

    def processar(self, pcm: bytes) -> str | None:
        """Avalia mais áudio. Devolve "inicio" ou "fim" quando a fala começa ou termina."""
        if self.terminou:
            return None
        amostras = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16)
        self._pendente = np.concatenate([self._pendente, amostras.astype(np.float32) / 32768.0])
        evento = None
        while len(self._pendente) >= BLOCO and not self.terminou:
            bloco, self._pendente = self._pendente[:BLOCO], self._pendente[BLOCO:]
            evento = self._avaliar(self._prob(bloco)) or evento
            self._amostras += BLOCO
        return evento

    def _avaliar(self, p: float) -> str | None:
        if not self.falou:
            self._seguidos_fala = self._seguidos_fala + 1 if p >= self._limiar else 0
            if self._seguidos_fala >= self._blocos_fala_min:
                self.inicio = self._amostras + BLOCO - self._seguidos_fala * BLOCO
                return "inicio"
            return None
        if p < self._limiar_silencio:
            if self._seguidos_silencio == 0:
                self.fim = self._amostras
            self._seguidos_silencio += 1
            if self._seguidos_silencio >= self._blocos_silencio:
                self.terminou = True
                return "fim"
        elif p >= self._limiar:
            self._seguidos_silencio = 0
            self.fim = None
        return None
