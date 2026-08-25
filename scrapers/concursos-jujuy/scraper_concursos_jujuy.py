"""
Scraper de Concursos Preventivos y Quiebras - Boletín Oficial de Jujuy
========================================================================

Fuente confirmada (en vivo, GET, sin login ni captcha):
    https://boletinoficial.jujuy.gob.ar/?cat=8            -> página 1 (más reciente)
    https://boletinoficial.jujuy.gob.ar/?cat=8&paged=2    -> página 2, etc.

Cómo correrlo a mano:
    pip install -r requirements.txt
    python scraper_concursos_jujuy.py

Este script corre automáticamente todos los días vía GitHub Actions
(ver .github/workflows/scraper-concursos-jujuy.yml en la raíz del repo).
Cada corrida:
  - guarda en `ultima_corrida.json` el ID del post más nuevo ya visto, así
    en cada corrida solo procesa avisos nuevos.
  - guarda en `ultima_corrida_resultado.json` el resultado de la corrida
    (avisos nuevos filtrados a Jujuy), que el workflow lee para abrir un
    GitHub Issue de aviso cuando hay novedades.

Filtro de jurisdicción: se queda solo con avisos cuyo texto menciona
juzgados/localidades de Jujuy (San Salvador de Jujuy, San Pedro de Jujuy,
Libertador Gral. San Martín, Palpalá, etc.) para descartar los concursos
de otras provincias que también publican edicto ahí por notificación federal.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://boletinoficial.jujuy.gob.ar/?cat=8"

# Los archivos de estado viven junto al script para que el workflow los
# encuentre sin importar desde qué directorio se invoque.
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "ultima_corrida.json"
RESULT_FILE = SCRIPT_DIR / "ultima_corrida_resultado.json"

# Localidades/juzgados que indican que el concurso es de Jujuy (ajustar si hace falta)
JURISDICCIONES_JUJUY = [
    "san salvador de jujuy",
    "san pedro de jujuy",
    "libertador general san martín",
    "libertador gral. san martin",
    "palpalá",
    "perico",
    "el carmen",
    "provincia de jujuy",
    "pcia. de jujuy",
    "pcia de jujuy",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AscentaMonitor/1.0)"
}


def cargar_ultimo_id_visto() -> int:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text()).get("ultimo_id", 0)
    return 0


def guardar_ultimo_id_visto(post_id: int) -> None:
    STATE_FILE.write_text(json.dumps({"ultimo_id": post_id}))


def guardar_resultado(nuevos: list[dict], solo_jujuy: list[dict]) -> None:
    resultado = {
        "fecha_corrida_utc": datetime.now(timezone.utc).isoformat(),
        "total_nuevos": len(nuevos),
        "nuevos_jujuy": solo_jujuy,
    }
    RESULT_FILE.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))


def extraer_post_id(url: str) -> int:
    m = re.search(r"[?&]p=(\d+)", url)
    return int(m.group(1)) if m else 0


def es_de_jujuy(texto: str) -> bool:
    texto_lower = texto.lower()
    return any(loc in texto_lower for loc in JURISDICCIONES_JUJUY)


def extraer_cuit(texto: str) -> str | None:
    m = re.search(r"CUIT\s*N?º?\s*[:.]?\s*(\d{2}-?\d{7,8}-?\d)", texto, re.IGNORECASE)
    return m.group(1) if m else None


def parsear_pagina(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    avisos = []

    for h3 in soup.select("h3"):
        link = h3.find("a")
        if not link:
            continue
        titulo = link.get_text(strip=True)
        url = link.get("href", "")
        post_id = extraer_post_id(url)

        # El resumen suele estar en el párrafo siguiente al h3
        resumen_tag = h3.find_next_sibling("p")
        resumen = resumen_tag.get_text(strip=True) if resumen_tag else ""

        avisos.append({
            "post_id": post_id,
            "titulo": titulo,
            "url": url,
            "resumen": resumen,
            "cuit": extraer_cuit(resumen),
            "es_jujuy": es_de_jujuy(resumen),
        })

    return avisos


def buscar_avisos_nuevos(ultimo_id_visto: int, max_paginas: int = 5) -> list[dict]:
    nuevos = []
    url = BASE_URL

    for pagina in range(1, max_paginas + 1):
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        avisos = parsear_pagina(resp.text)

        if not avisos:
            break

        for aviso in avisos:
            if aviso["post_id"] <= ultimo_id_visto:
                # Llegamos a avisos ya procesados en una corrida anterior: cortamos.
                return nuevos
            nuevos.append(aviso)

        pagina += 1
        url = f"{BASE_URL}&paged={pagina}"
        time.sleep(1)  # no golpear el sitio de forma agresiva

    return nuevos


def main():
    ultimo_id_visto = cargar_ultimo_id_visto()
    nuevos = buscar_avisos_nuevos(ultimo_id_visto)

    if not nuevos:
        print("Sin avisos nuevos desde la última corrida.")
        guardar_resultado([], [])
        return

    # El más nuevo queda primero en la lista (orden descendente de la página)
    guardar_ultimo_id_visto(nuevos[0]["post_id"])

    solo_jujuy = [a for a in nuevos if a["es_jujuy"]]
    guardar_resultado(nuevos, solo_jujuy)

    print(f"Avisos nuevos encontrados: {len(nuevos)} (de Jujuy: {len(solo_jujuy)})\n")
    for aviso in solo_jujuy:
        print(f"- {aviso['titulo']}")
        print(f"  CUIT: {aviso['cuit'] or 'no detectado'}")
        print(f"  URL:  {aviso['url']}")
        print(f"  Resumen: {aviso['resumen'][:200]}...\n")

    # TODO: acá enganchar la carga a Notion (Pipeline Comercial de Websy/Ascenta)
    # usando el mismo patrón que ya usan los otros agentes de captación.


if __name__ == "__main__":
    main()
