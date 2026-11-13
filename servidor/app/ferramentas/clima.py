"""Ferramenta clima: tempo atual e previsão de 3 dias, do Open-Meteo (sem chave).

Os dados do Open-Meteo são CC BY 4.0 (atribuição em docs/licencas.md)."""

import json
import math

from app.ferramentas.rede import Cache, Resultado, obter_json

GEOCODIFICACAO = "https://geocoding-api.open-meteo.com/v1/search"
PREVISAO = "https://api.open-meteo.com/v1/forecast"
# Dito em voz ("Segundo a previsão do tempo, …"), por escolha do projeto, em vez do
# nome do serviço; a atribuição do Open-Meteo (CC BY 4.0) fica em docs/licencas.md.
FONTE = "a previsão do tempo"

DEFINICAO = {
    "type": "function",
    "function": {
        "name": "clima",
        "description": "Tempo agora e previsão de 3 dias. Sem cidade: a do robô.",
        "parameters": {"type": "object", "properties": {"cidade": {"type": "string"}}},
    },
}

# Códigos WMO do Open-Meteo.
_TEMPO = {
    0: "céu limpo",
    1: "poucas nuvens",
    2: "parcialmente nublado",
    3: "nublado",
    45: "neblina",
    48: "neblina com geada",
    51: "garoa fraca",
    53: "garoa",
    55: "garoa forte",
    56: "garoa congelante",
    57: "garoa congelante forte",
    61: "chuva fraca",
    63: "chuva",
    65: "chuva forte",
    66: "chuva congelante",
    67: "chuva congelante forte",
    71: "neve fraca",
    73: "neve",
    75: "neve forte",
    77: "grãos de neve",
    80: "pancadas de chuva fracas",
    81: "pancadas de chuva",
    82: "pancadas de chuva fortes",
    85: "pancadas de neve",
    86: "pancadas de neve fortes",
    95: "trovoadas",
    96: "trovoadas com granizo",
    99: "trovoadas com granizo forte",
}
_DIAS = ("hoje", "amanhã", "depois de amanhã")

_lugares = Cache(validade_s=math.inf, maximo=256)  # cidade → lugar: não muda
_previsoes = Cache(validade_s=600)  # lugar → previsão: 10 min


def _graus(v: float | None) -> str | None:
    return None if v is None else f"{round(v)} graus"


def _pct(v: float | None) -> str | None:
    return None if v is None else f"{round(v)} por cento"


def _sem_vazios(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


async def _lugar(cidade: str) -> dict | None:
    chave = cidade.casefold()
    if (lugar := _lugares.obter(chave)) is not None:
        return lugar or None
    dados = await obter_json(
        GEOCODIFICACAO, {"name": cidade, "count": 5, "language": "pt", "format": "json"}
    )
    candidatos = (dados.get("results") if isinstance(dados, dict) else None) or []
    # Nomes repetidos (há várias "Goiânia" pelo mundo?): fica a mais populosa.
    melhor = max(candidatos, key=lambda r: r.get("population") or 0, default=None)
    lugar = {}
    if melhor and "latitude" in melhor and "longitude" in melhor:
        nome = ", ".join(
            dict.fromkeys(
                p for p in (melhor.get("name"), melhor.get("admin1"), melhor.get("country")) if p
            )
        )
        lugar = {"nome": nome, "lat": melhor["latitude"], "lon": melhor["longitude"]}
    _lugares.guardar(chave, lugar)
    return lugar or None


async def _previsao(lugar: dict) -> dict:
    chave = (lugar["lat"], lugar["lon"])
    if (previsao := _previsoes.obter(chave)) is not None:
        return previsao
    previsao = await obter_json(
        PREVISAO,
        {
            "latitude": lugar["lat"],
            "longitude": lugar["lon"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
            "weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 3,
        },
    )
    _previsoes.guardar(chave, previsao)
    return previsao


def _resumo(lugar: dict, p: dict) -> dict:
    atual = p.get("current") or {}
    diario = p.get("daily") or {}
    dias = []
    for i, nome in enumerate(_DIAS):

        def valor(campo, i=i):
            lista = diario.get(campo) or []
            return lista[i] if i < len(lista) else None

        if valor("weather_code") is None and valor("temperature_2m_max") is None:
            continue
        dias.append(
            _sem_vazios(
                {
                    "dia": nome,
                    "tempo": _TEMPO.get(valor("weather_code")),
                    "minima": _graus(valor("temperature_2m_min")),
                    "maxima": _graus(valor("temperature_2m_max")),
                    "chance_de_chuva": _pct(valor("precipitation_probability_max")),
                }
            )
        )
    agora = _sem_vazios(
        {
            "temperatura": _graus(atual.get("temperature_2m")),
            "sensacao": _graus(atual.get("apparent_temperature")),
            "tempo": _TEMPO.get(atual.get("weather_code")),
            "umidade": _pct(atual.get("relative_humidity_2m")),
            "vento": None
            if atual.get("wind_speed_10m") is None
            else f"{round(atual['wind_speed_10m'])} quilômetros por hora",
        }
    )
    return _sem_vazios({"cidade": lugar["nome"], "agora": agora or None, "previsao": dias or None})


async def clima(cidade: str | None, cidade_padrao: str) -> Resultado:
    cidade = (cidade or "").strip()[:80] or cidade_padrao
    lugar = await _lugar(cidade)
    if lugar is None:
        return Resultado(f"Cidade não encontrada: {cidade}.")
    previsao = await _previsao(lugar)
    texto = json.dumps(_resumo(lugar, previsao), ensure_ascii=False, separators=(",", ":"))
    return Resultado(texto, FONTE)


def limpar_cache() -> None:
    _lugares.limpar()
    _previsoes.limpar()
