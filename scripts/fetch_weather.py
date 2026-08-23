#!/usr/bin/env python3
"""
Descarga la prevision de Open-Meteo y publica docs/data/tiempo.json.

Open-Meteo no pide clave y es gratuito para uso no comercial hasta 10.000
llamadas diarias, con atribucion obligatoria (CC BY 4.0). Refrescando cada
media hora gastamos 48 llamadas al dia.

Reglas acordadas:
- Se imprime la probabilidad a partir del 10 %.
- La banda de aviso salta solo si se superan A LA VEZ el 50 % de probabilidad
  y el minimo de milimetros: un 60 % con dos decimas es una llovizna que no
  moja, un 35 % con cinco milimetros si es un chaparron.
- Si ninguna de las 12 horas proximas cruza el umbral, se mira la semana y se
  nombra el primer dia que lo haga. Si tampoco, no hay aviso y la banda
  desaparece sin dejar hueco.
"""

import json
import pathlib
import urllib.parse
import urllib.request
from datetime import datetime

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "data" / "tiempo.json"

LAT, LON = 41.3874, 2.1686          # Barcelona
ZONA = "Europe/Madrid"
CIUDAD = "Barcelona"

UMBRAL_MOSTRAR = 10                 # % a partir del cual se imprime la cifra
UMBRAL_AVISO = 50                   # % minimo para la banda de aviso
MM_AVISO = 1.0                      # y ademas, milimetros minimos
HORAS = 12

DIAS = ["dl", "dt", "dc", "dj", "dv", "ds", "dg"]
DIAS_ES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

# Codigos WMO agrupados en los cuatro iconos que usa la pantalla.
# Mas granularidad no aporta nada en e-ink.
def icono(codigo, es_de_dia):
    if codigo in (0, 1):
        return "sol" if es_de_dia else "luna"
    if codigo in (2, 3, 45, 48):
        return "nube"
    return "lluvia"


def pedir():
    parametros = {
        "latitude": LAT,
        "longitude": LON,
        "timezone": ZONA,
        "forecast_days": 8,
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,precipitation_sum",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(parametros)
    peticion = urllib.request.Request(url, headers={"User-Agent": "trmnl-dashboard/1.0"})
    with urllib.request.urlopen(peticion, timeout=20) as respuesta:
        return json.loads(respuesta.read())


def construir(bruto):
    ahora = datetime.now()
    h = bruto["hourly"]

    # El feed empieza a medianoche: hay que localizar la hora actual.
    inicio = 0
    for i, marca in enumerate(h["time"]):
        if datetime.fromisoformat(marca) > ahora:
            inicio = i
            break

    horas = []
    for i in range(inicio, min(inicio + HORAS, len(h["time"]))):
        prob = h["precipitation_probability"][i] or 0
        horas.append({
            "hora": datetime.fromisoformat(h["time"][i]).strftime("%H"),
            "temp": round(h["temperature_2m"][i]),
            "prob": prob,
            "mm": round(h["precipitation"][i] or 0, 1),
            "mostrar_prob": prob >= UMBRAL_MOSTRAR,
            "icono": icono(h["weather_code"][i], bool(h["is_day"][i])),
        })

    d = bruto["daily"]
    dias = []
    for i in range(len(d["time"])):
        fecha = datetime.fromisoformat(d["time"][i])
        if fecha.date() <= ahora.date():
            continue
        prob = d["precipitation_probability_max"][i] or 0
        dias.append({
            "etiqueta": f"{DIAS_ES[fecha.weekday()]} {fecha.day}",
            "max": round(d["temperature_2m_max"][i]),
            "min": round(d["temperature_2m_min"][i]),
            "prob": prob,
            "mm": round(d["precipitation_sum"][i] or 0, 1),
            "mostrar_prob": prob >= UMBRAL_MOSTRAR,
            "destacar": prob >= UMBRAL_AVISO and (d["precipitation_sum"][i] or 0) >= MM_AVISO,
            "icono": icono(d["weather_code"][i], True),
        })
        if len(dias) == 7:
            break

    return {
        "ciudad": CIUDAD,
        "generado": ahora.isoformat(timespec="seconds"),
        "horas": horas,
        "dias": dias,
        "aviso": calcular_aviso(horas, dias),
        "atribucion": "Open-Meteo (CC BY 4.0)",
    }


def calcular_aviso(horas, dias):
    """Primero las 12 horas; si no hay nada, la semana; si no, ninguno."""
    disparo = [x for x in horas if x["prob"] >= UMBRAL_AVISO and x["mm"] >= MM_AVISO]
    if disparo:
        primera = disparo[0]
        pico = max(disparo, key=lambda x: x["prob"])
        texto = f"Lluvia prevista a partir de las {primera['hora']} h"
        if pico["hora"] != primera["hora"]:
            texto += f" · {pico['prob']}% hacia las {pico['hora']} h"
        else:
            texto += f" · {primera['prob']}%"
        return {"activo": True, "alcance": "horas", "texto": texto}

    for dia in dias:
        if dia["destacar"]:
            return {"activo": True, "alcance": "semana",
                    "texto": f"Lluvia prevista el {dia['etiqueta']} · {dia['prob']}%"}

    return {"activo": False, "alcance": None, "texto": None}


def main():
    datos = construir(pedir())
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")

    aviso = datos["aviso"]
    print(f"tiempo    {datos['ciudad']}  {len(datos['horas'])} horas, {len(datos['dias'])} dias")
    print(f"    aviso: {aviso['texto'] if aviso['activo'] else 'ninguno'}")
    print("    " + "  ".join(f"{x['hora']}h {x['temp']}° {x['prob']}%" for x in datos["horas"][:6]))


if __name__ == "__main__":
    main()
