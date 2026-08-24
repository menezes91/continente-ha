"""Histórico de preços dos produtos.

O continente.pt não publica preços passados: a única referência que dá é o
PVPR dos produtos em promoção. O histórico verdadeiro constrói-se daqui para a
frente, um registo por dia, guardado em SQLite.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS precos (
    pid           TEXT NOT NULL,
    dia           TEXT NOT NULL,   -- YYYY-MM-DD
    preco         REAL NOT NULL,
    preco_ref     REAL,            -- o PVPR, quando está em promoção
    preco_unidade TEXT,
    nome          TEXT,
    registado_em  TEXT NOT NULL,
    PRIMARY KEY (pid, dia)
);
CREATE INDEX IF NOT EXISTS idx_precos_pid ON precos(pid, dia);
"""


class PriceHistory:
    """Um registo de preços por produto e por dia."""

    def __init__(self, path: Path | None = None):
        self.path = path or config.PRICES_FILE
        with closing(self._connect()) as db:
            db.executescript(SCHEMA)
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    # ------------------------------------------------------------- escrita

    def record(self, products: list[dict], day: str | None = None) -> dict:
        """Grava os preços de hoje.

        Um registo por produto e por dia: correr o snapshot duas vezes no mesmo
        dia atualiza, não duplica.
        """
        day = day or time.strftime("%Y-%m-%d")
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        # O site devolve `price: 0` para produtos indisponíveis. Zero não é um
        # preço — registá-lo achatava a escala do gráfico e inventava uma queda.
        rows = [
            (p["pid"], day, float(p["price"]),
             p.get("list_price"), p.get("price_per_unit"), p.get("name"), now)
            for p in products
            if p.get("pid") and p.get("price") not in (None, 0)
            and float(p["price"]) > 0
        ]
        if not rows:
            return {"day": day, "recorded": 0, "products": 0}

        with closing(self._connect()) as db:
            db.executemany(
                "INSERT INTO precos (pid, dia, preco, preco_ref, preco_unidade,"
                " nome, registado_em) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(pid, dia) DO UPDATE SET"
                " preco=excluded.preco, preco_ref=excluded.preco_ref,"
                " preco_unidade=excluded.preco_unidade, nome=excluded.nome,"
                " registado_em=excluded.registado_em",
                rows,
            )
            db.commit()
        return {"day": day, "recorded": len(rows), "products": len(products)}

    # ------------------------------------------------------------- leitura

    def history(self, pid: str) -> dict:
        """Série temporal de um produto."""
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT dia, preco, preco_ref, preco_unidade, nome FROM precos"
                " WHERE pid = ? ORDER BY dia", (pid,)
            ).fetchall()
        points = [dict(r) for r in rows]
        return {
            "pid": pid,
            "name": points[-1]["nome"] if points else None,
            "points": points,
            **_summary(points),
        }

    def tracked(self) -> list[dict]:
        """Produtos com histórico, e o que aconteceu ao preço de cada um."""
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT pid, COUNT(*) AS dias, MIN(dia) AS desde,"
                " MAX(dia) AS ate, MIN(preco) AS minimo, MAX(preco) AS maximo"
                " FROM precos GROUP BY pid ORDER BY MAX(dia) DESC"
            ).fetchall()
            out = []
            for r in rows:
                last = db.execute(
                    "SELECT preco, preco_ref, nome FROM precos WHERE pid = ?"
                    " ORDER BY dia DESC LIMIT 1", (r["pid"],)
                ).fetchone()
                first = db.execute(
                    "SELECT preco FROM precos WHERE pid = ? ORDER BY dia LIMIT 1",
                    (r["pid"],)
                ).fetchone()
                out.append({
                    **dict(r),
                    "nome": last["nome"],
                    "preco": last["preco"],
                    "preco_ref": last["preco_ref"],
                    "variacao": _pct(first["preco"], last["preco"]),
                })
        return out

    def stats(self) -> dict:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT COUNT(DISTINCT pid) AS produtos, COUNT(DISTINCT dia)"
                " AS dias, MIN(dia) AS desde, MAX(dia) AS ate FROM precos"
            ).fetchone()
        return {**dict(row), "ficheiro": str(self.path)}


def _summary(points: list[dict]) -> dict:
    if not points:
        return {"atual": None, "minimo": None, "maximo": None,
                "variacao": None, "dias": 0}
    precos = [p["preco"] for p in points]
    return {
        "atual": precos[-1],
        "minimo": min(precos),
        "maximo": max(precos),
        "variacao": _pct(precos[0], precos[-1]),
        "dias": len(points),
        "preco_ref": points[-1].get("preco_ref"),
    }


def _pct(first: float, last: float) -> float | None:
    if not first:
        return None
    return round(100 * (last - first) / first, 1)


def snapshot(client, extra_pids: list[str] | None = None,
             history: PriceHistory | None = None) -> dict:
    """Regista os preços de hoje dos produtos que te interessam.

    A lista de compras frequentes vem toda num pedido; os produtos que não
    estejam lá (os que mapeaste do Cookidoo) custam um pedido cada.
    """
    history = history or PriceHistory()
    products: dict[str, dict] = {}
    problems: list[str] = []

    try:
        for p in client.my_list()["products"]:
            if p.get("price") is not None:
                products[p["pid"]] = p
    except Exception as exc:
        # Sem sessão ainda dá para seguir os pids explícitos — mas não em
        # silêncio, senão um snapshot vazio parece um snapshot bem-sucedido.
        problems.append(f"lista da conta: {exc}")

    for pid in extra_pids or []:
        if pid in products or not str(pid).isdigit():
            continue
        try:
            found = client.search(str(pid), limit=3)["results"]
            match = next((p for p in found if p["pid"] == str(pid)), None)
            if match and match.get("price") is not None:
                products[pid] = match
        except Exception as exc:
            problems.append(f"produto {pid}: {exc}")

    result = history.record(list(products.values()))
    result["stats"] = history.stats()
    if problems:
        result["problems"] = problems
    return result
