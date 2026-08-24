"""Mapeamento entre os nomes do Cookidoo e os produtos do Continente.

A lista do Cookidoo fala em "farinha" e "papel higiénico"; o Continente vende
"Farinha de Trigo T65 Continente" com o pid 7108347. Este módulo guarda essas
correspondências à medida que as decides, e propõe hipóteses para as que ainda
não existem.

O ficheiro é um CSV de propósito: podes abri-lo e corrigi-lo à mão.
"""
from __future__ import annotations

import csv
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from . import config

FIELDS = ["termo", "pid", "nome_continente", "quantidade", "atualizado"]

# Quanto vale, na ordenação, um produto que já compras.
KNOWN_BONUS = 0.15

# Um `pid` assim quer dizer "nunca comprar isto".
IGNORE = "-"

# Palavras que só fazem ruído na comparação de nomes.
_STOPWORDS = {
    "de", "do", "da", "dos", "das", "e", "com", "sem", "para", "em", "a", "o",
    "os", "as", "um", "uma", "no", "na", "ao", "pack", "emb", "un", "gr", "kg",
    "ml", "lt", "cl", "g", "l",
}


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação — a chave do mapeamento."""
    text = unicodedata.normalize("NFKD", (text or "").strip().lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text)).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in normalize(text).split() if t and t not in _STOPWORDS}


def similarity(query: str, candidate: str) -> float:
    """0..1. Combina sobreposição de palavras com semelhança de texto.

    A sobreposição pesa mais: "papel higiénico" contra "Papel Higiénico 4
    Folhas Grand Royal Renova" tem pouca semelhança de string mas todas as
    palavras que interessam batem certo.
    """
    q, c = _tokens(query), _tokens(candidate)
    if not q or not c:
        return 0.0
    overlap = len(q & c) / len(q)
    # Palavras do Cookidoo que aparecem dentro de palavras do produto
    # ("azeite" em "azeitona" não conta, mas "farinha" em "farinhas" sim).
    partial = sum(
        1 for t in q if t not in c and any(w.startswith(t) for w in c)
    ) / len(q)
    ratio = SequenceMatcher(None, normalize(query), normalize(candidate)).ratio()
    return round(min(1.0, overlap + 0.5 * partial) * 0.75 + ratio * 0.25, 4)


class MappingStore:
    """As correspondências já decididas, num CSV editável.

    Um termo pode ter mais do que um produto: guardas os que aceitas para
    "cebola" e o sistema compra o mais barato à unidade de medida. No CSV isso
    é uma linha por par (termo, produto).
    """

    def __init__(self, path: Path | None = None):
        # Resolvido agora, não no import: o Home Assistant só diz onde ficam
        # os dados depois de o módulo estar carregado.
        self.path = path or config.MAPPING_FILE
        self.rows: dict[str, list[dict]] = {}
        self.load()

    def load(self) -> None:
        self.rows = {}
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                key = normalize(row.get("termo", ""))
                pid = (row.get("pid") or "").strip()
                if not key or not pid:
                    continue
                entry = {
                    "termo": row.get("termo", ""),
                    "pid": pid,
                    "nome_continente": row.get("nome_continente", ""),
                    "quantidade": _to_float(row.get("quantidade"), 1.0),
                    "atualizado": row.get("atualizado", ""),
                }
                bucket = self.rows.setdefault(key, [])
                if not any(e["pid"] == pid for e in bucket):
                    bucket.append(entry)

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for key in sorted(self.rows):
                for entry in self.rows[key]:
                    w.writerow(entry)

    def get(self, term: str) -> list[dict]:
        """Todos os produtos aceites para este termo."""
        return self.rows.get(normalize(term), [])

    def add(self, term: str, pid: str, name: str = "",
            quantity: float = 1.0) -> dict:
        """Acrescenta um produto aos aceites, sem apagar os outros."""
        entry = {
            "termo": term,
            "pid": str(pid),
            "nome_continente": name,
            "quantidade": quantity,
            "atualizado": time.strftime("%Y-%m-%d"),
        }
        bucket = self.rows.setdefault(normalize(term), [])
        existing = next((e for e in bucket if e["pid"] == str(pid)), None)
        if existing:
            existing.update(entry)
        else:
            # Escolher um produto normal apaga o "ignorar", que é exclusivo.
            bucket[:] = [e for e in bucket if e["pid"] != IGNORE]
            bucket.append(entry)
        self.save()
        return entry

    def set(self, term: str, pid: str, name: str = "",
            quantity: float = 1.0) -> dict:
        """Deixa este produto como o único aceite para o termo."""
        self.rows[normalize(term)] = []
        return self.add(term, pid, name, quantity)

    def remove(self, term: str, pid: str) -> bool:
        """Tira um produto dos aceites, deixando os restantes."""
        key = normalize(term)
        bucket = self.rows.get(key)
        if not bucket:
            return False
        before = len(bucket)
        bucket[:] = [e for e in bucket if e["pid"] != str(pid)]
        if not bucket:
            del self.rows[key]
        if len(self.rows.get(key, [])) != before:
            self.save()
            return True
        return False

    def set_quantity(self, term: str, quantity: float) -> list[dict]:
        """A quantidade é do item da lista, não de cada produto."""
        bucket = self.rows.get(normalize(term), [])
        for entry in bucket:
            entry["quantidade"] = quantity
            entry["atualizado"] = time.strftime("%Y-%m-%d")
        self.save()
        return bucket

    def forget(self, term: str) -> bool:
        key = normalize(term)
        if key in self.rows:
            del self.rows[key]
            self.save()
            return True
        return False

    def __len__(self) -> int:
        return len(self.rows)


def load_known_products(path: Path | None = None) -> list[dict]:
    """Produtos que já compras, lidos do CSV — as primeiras hipóteses.

    Uma sugestão tirada daqui vale mais do que uma da pesquisa: é um produto
    que já escolheste alguma vez.
    """
    path = path or config.KNOWN_PRODUCTS_FILE
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            name = row.get("Artigo") or row.get("artigo") or row.get("nome")
            link = row.get("Link") or row.get("link") or ""
            pid = (row.get("pid") or "").strip() or _pid_from(link)
            if name and pid:
                out.append({
                    "pid": pid,
                    "name": name,
                    "url": link,
                    "price": _to_float(row.get("Preco"), None),
                    "origin": "já compras",
                })
    return out


def _pid_from(url: str) -> str:
    m = re.search(r"-(\d{5,})\.html", url or "")
    return m.group(1) if m else ""


def _to_float(value, default):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


_PER_UNIT = re.compile(r"(\d+)[,.](\d+)\s*€\s*/\s*(\w+)")


def parse_price_per_unit(text: str | None) -> tuple[float, str] | None:
    """`"1,86€/kg"` -> `(1.86, "kg")`."""
    m = _PER_UNIT.search(text or "")
    if not m:
        return None
    return float(f"{m.group(1)}.{m.group(2)}"), m.group(3).lower()


def cheapest(candidates: list[dict]) -> dict:
    """Escolhe o mais barato entre vários produtos aceites para um item.

    Compara pelo preço à unidade de medida — mas só quando os candidatos
    partilham a mesma unidade. `1,86€/kg` e `0,40€/un` são grandezas
    diferentes: fingir que se comparam daria a escolha errada com toda a
    confiança. Nesse caso decide o preço total, e a razão fica registada.
    """
    usable = [c for c in candidates
              if c.get("price") and not c.get("out_of_stock")]
    dropped = [c for c in candidates if c not in usable]

    if not usable:
        return {"chosen": None, "basis": "nenhum disponível",
                "candidates": candidates, "unavailable": dropped}

    per_unit = {c["pid"]: parse_price_per_unit(c.get("price_per_unit"))
                for c in usable}

    # Agrupa por unidade de medida. Comparar por €/kg só é honesto entre
    # produtos vendidos ao kg, por isso decide-se dentro do maior grupo — dois
    # produtos ao quilo comparam-se entre si e não perdem para um terceiro que
    # calha ser mais barato à peça.
    groups: dict[str, list[dict]] = {}
    for c in usable:
        pu = per_unit[c["pid"]]
        if pu:
            groups.setdefault(pu[1], []).append(c)

    if groups:
        unit, group = max(
            groups.items(),
            key=lambda kv: (len(kv[1]), -min(c["price"] for c in kv[1])),
        )
        best = min(group, key=lambda c: per_unit[c["pid"]][0])
        left_out = len(usable) - len(group)
        basis = f"mais barato por {unit}"
        if left_out:
            basis += f" ({len(group)} de {len(usable)}; {left_out} noutra unidade)"
    else:
        best = min(usable, key=lambda c: c["price"])
        basis = "mais barato ao total — nenhum traz preço por unidade"

    return {
        "chosen": best,
        "basis": basis,
        "candidates": usable,
        "unavailable": dropped,
    }


class Matcher:
    """Propõe produtos do Continente para um nome vindo do Cookidoo."""

    def __init__(self, client, store: MappingStore | None = None,
                 known: list[dict] | None = None):
        self.client = client
        self.store = store or MappingStore()
        self.known = known if known is not None else load_known_products()

    def resolve(self, term: str, limit: int = 6) -> dict:
        """Resolve um item da lista.

        Devolve `status`:
          `mapeado`   — já decidido antes, usa-se sem perguntar
          `sugestoes` — há hipóteses à espera de escolha
          `nada`      — a pesquisa não devolveu nada de útil
        """
        saved = self.store.get(term)
        if saved:
            return {
                "term": term,
                "status": "mapeado",
                "chosen": saved,
                "candidates": [],
            }
        candidates = self.candidates(term, limit=limit)
        return {
            "term": term,
            "status": "sugestoes" if candidates else "nada",
            "chosen": None,
            "candidates": candidates,
        }

    def candidates(self, term: str, limit: int = 6) -> list[dict]:
        """Hipóteses ordenadas: primeiro o que já compras, depois a pesquisa."""
        scored: dict[str, dict] = {}

        for product in self.known:
            score = similarity(term, product["name"])
            if score >= 0.5:
                scored[product["pid"]] = {**product, "score": score}

        try:
            results = self.client.search(term, limit=24)["results"]
        except Exception:  # a pesquisa é um extra: sem ela ainda há o CSV
            results = []

        for product in results:
            pid = product["pid"]
            score = similarity(term, product.get("name") or "")
            if pid in scored:
                # Já veio do CSV: fica com a melhor pontuação e ganha o preço.
                scored[pid]["score"] = max(scored[pid]["score"], score)
                scored[pid].setdefault("image", product.get("image"))
                if scored[pid].get("price") is None:
                    scored[pid]["price"] = product.get("price")
                continue
            if score >= 0.3:
                scored[pid] = {**product, "score": score, "origin": "pesquisa"}

        # Já comprares um produto é um bónus, não uma prioridade absoluta: sem
        # isto, "papel alumínio" propunha o papel higiénico do CSV à frente do
        # papel de alumínio que a pesquisa encontrou.
        ordered = sorted(
            scored.values(),
            key=lambda p: p["score"] + (KNOWN_BONUS if p.get("origin") == "já compras" else 0),
            reverse=True,
        )
        return ordered[:limit]
