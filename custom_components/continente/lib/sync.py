"""Espelho entre a lista de compras do Cookidoo e o carrinho do Continente."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .client import ContinenteClient
from .cookidoo import CookidooClient, CookidooError
from .mapping import (
    IGNORE,
    MappingStore,
    Matcher,
    cheapest,
    load_known_products,
    normalize,
)


class ShoppingSync:
    """Junta as três peças: a lista, as correspondências e o carrinho."""

    def __init__(self, continente: ContinenteClient | None = None,
                 cookidoo: CookidooClient | None = None,
                 store: MappingStore | None = None,
                 cookidoo_credentials: tuple[str, str] | None = None):
        self.continente = continente or ContinenteClient()
        self._cookidoo = cookidoo
        self._cookidoo_credentials = cookidoo_credentials
        self.store = store or MappingStore()
        self.matcher = Matcher(self.continente, self.store,
                               load_known_products())
        # A lista do Cookidoo custa um login e três pedidos. As decisões de
        # mapeamento não a alteram, por isso guarda-se até pedires outra.
        self._cached_list: dict | None = None
        # Preços dos candidatos, para não voltar ao site a cada comparação.
        self._price_cache: dict[str, dict] = {}

    @property
    def cookidoo(self) -> CookidooClient:
        if self._cookidoo is None:
            email, password = self._cookidoo_credentials or (None, None)
            self._cookidoo = CookidooClient(email, password)
        return self._cookidoo

    # -------------------------------------------------------------- a lista

    def shopping_list(self, include_owned: bool = True,
                      refresh: bool = False) -> dict:
        """A lista do Cookidoo com o estado de mapeamento de cada item.

        Mostra tudo por omissão, incluindo o que está marcado como "já tenho":
        esconder itens por causa de uma flag mal interpretada seria pior do que
        mostrar de mais. Quem filtra é a app.

        Não vai à pesquisa do Continente: isto tem de ser instantâneo. As
        hipóteses para os itens por decidir pedem-se com `candidates()`.
        """
        if refresh or self._cached_list is None:
            self._cached_list = self.cookidoo.shopping_list()
            self._price_cache.clear()   # preços mudam; recarregar relê-os
        raw = self._cached_list

        items = [
            {**group, **self._state(group["name"])}
            for group in _group_by_name(raw["ingredients"] + raw["additional"])
            if include_owned or not group["owned"]
        ]
        return {
            "items": items,
            "recipes": raw["recipes"],
            "counts": _counts(items),
        }

    def _state(self, term: str) -> dict:
        saved = self.store.get(term)
        if not saved:
            return {"status": "por_decidir", "mapped": None, "options": []}
        if any(e["pid"] == IGNORE for e in saved):
            return {"status": "ignorado", "mapped": saved[0], "options": []}
        pick = self.pick_best(term)
        return {
            "status": "mapeado",
            "mapped": pick["chosen"] or saved[0],
            "options": saved,
            "basis": pick["basis"] if len(saved) > 1 else None,
        }

    def pick_best(self, term: str) -> dict:
        """Qual dos produtos aceites para este termo se compra hoje.

        Com um só produto não há nada a decidir; com vários, ganha o mais
        barato à unidade de medida (ver `mapping.cheapest`).
        """
        saved = [e for e in self.store.get(term) if e["pid"] != IGNORE]
        if not saved:
            return {"chosen": None, "basis": None}
        if len(saved) == 1:
            return {"chosen": saved[0], "basis": None}

        enriched = []
        for entry in saved:
            info = self._price_of(entry["pid"])
            enriched.append({**entry, **info})
        result = cheapest(enriched)
        return {"chosen": result["chosen"], "basis": result["basis"],
                "candidates": result["candidates"],
                "unavailable": result["unavailable"]}

    def _price_of(self, pid: str) -> dict:
        """Preço atual de um produto, guardado enquanto a app corre."""
        if pid in self._price_cache:
            return self._price_cache[pid]
        try:
            p = self.continente.product(pid)
            info = {
                "price": p.get("price"),
                "price_per_unit": p.get("price_per_unit"),
                "out_of_stock": p.get("out_of_stock", False),
                "nome_continente": p.get("name") or "",
            }
        except Exception:
            info = {"price": None, "price_per_unit": None,
                    "out_of_stock": True, "nome_continente": ""}
        self._price_cache[pid] = info
        return info

    # ---------------------------------------------------------- as hipóteses

    def candidates(self, term: str, limit: int = 6) -> list[dict]:
        return self.matcher.candidates(term, limit=limit)

    def candidates_for(self, terms: list[str], limit: int = 6) -> dict:
        """Hipóteses para vários termos ao mesmo tempo.

        Cada termo é uma pesquisa no Continente; em série, uma lista de vinte
        itens demorava quase um minuto.
        """
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(
                lambda t: (t, self._safe_candidates(t, limit)), terms
            ))
        return dict(results)

    def _safe_candidates(self, term: str, limit: int) -> list[dict]:
        try:
            return self.matcher.candidates(term, limit=limit)
        except Exception:
            return []

    def search(self, query: str, limit: int = 12) -> list[dict]:
        """Pesquisa livre, para quando nenhuma hipótese serve."""
        results = self.continente.search(query, limit=limit)["results"]
        return [{**p, "origin": "pesquisa", "score": None} for p in results]

    # ------------------------------------------------------- as decisões

    def map_item(self, term: str, pid: str, name: str = "",
                 quantity: float = 1.0, replace: bool = True) -> dict:
        """Escolhe um produto para o termo.

        `replace=False` acrescenta-o aos já aceites, em vez de os substituir —
        é assim que um item passa a ter vários candidatos.
        """
        if replace:
            return self.store.set(term, pid, name, quantity)
        return self.store.add(term, pid, name, quantity)

    def unmap_option(self, term: str, pid: str) -> bool:
        return self.store.remove(term, pid)

    def set_quantity(self, term: str, quantity: float) -> list[dict]:
        return self.store.set_quantity(term, quantity)

    def ignore_item(self, term: str) -> dict:
        return self.store.set(term, IGNORE, "(ignorado)", 0)

    def unmap_item(self, term: str) -> bool:
        return self.store.forget(term)

    # ------------------------------------------------------- para o carrinho

    def send_to_cart(self, terms: list[str] | None = None,
                     include_owned: bool = False,
                     mark_done: bool = True) -> dict:
        """Atira para o carrinho os itens já mapeados.

        Ao contrário da listagem, aqui os itens marcados como "já tenho" ficam
        de fora por omissão: vê-se tudo, compra-se só o que falta.

        Junta quantidades quando dois itens da lista apontam ao mesmo produto
        — duas receitas a pedir cebola não são duas idas ao mesmo produto.
        """
        listing = self.shopping_list(include_owned=include_owned)
        wanted = [
            i for i in listing["items"]
            if i["status"] == "mapeado"
            and (terms is None or normalize(i["name"]) in
                 {normalize(t) for t in terms})
        ]

        merged: dict[str, dict] = {}
        for item in wanted:
            pid = item["mapped"]["pid"]
            qty = float(item["mapped"].get("quantidade") or 1)
            if pid in merged:
                merged[pid]["quantity"] += qty
                merged[pid]["terms"].append(item["name"])
            else:
                merged[pid] = {
                    "product": pid,
                    "quantity": qty,
                    "terms": [item["name"]],
                    "produto": item["mapped"].get("nome_continente") or pid,
                    # Os outros produtos aceites, para o caso de este falhar.
                    "alternativas": [
                        o for o in (item.get("options") or [])
                        if o["pid"] != pid and o["pid"] != IGNORE
                    ],
                }

        if not merged:
            return {"added": 0, "failed": 0, "results": [],
                    "cart": self.continente.cart(),
                    "skipped": len(listing["items"]), "marked": 0}

        results = [self._add_with_fallback(entry) for entry in merged.values()]
        out = {
            "added": sum(1 for r in results if r.get("ok")),
            "failed": sum(1 for r in results if not r.get("ok")),
            "results": results,
            "cart": self.continente.cart(),
            "skipped": len(listing["items"]) - len(merged),
        }

        if mark_done:
            bought = {t for r in results if r.get("ok") for t in r["terms"]}
            out["marked"] = self._mark_done(wanted, bought)
        else:
            out["marked"] = 0
        return out

    def _add_with_fallback(self, entry: dict) -> dict:
        """Põe um produto no carrinho, tentando os outros aceites se falhar.

        Escolher três areias e ficar sem nenhuma porque a mais barata esgotou
        seria um desperdício — se há alternativas, tenta-se a seguinte.
        """
        tried: list[dict] = []
        candidates = [{"pid": entry["product"], "nome_continente": entry["produto"]}]
        candidates += entry["alternativas"]

        for n, candidate in enumerate(candidates):
            try:
                result = self.continente.add_to_cart(
                    candidate["pid"], entry["quantity"]
                )
            except Exception as exc:  # noqa: BLE001 - a razão vai no resultado
                result = {"ok": False, "pid": candidate["pid"], "reason": str(exc)}

            result["terms"] = entry["terms"]
            result["produto"] = (
                (result.get("line") or {}).get("name")
                or candidate.get("nome_continente") or candidate["pid"]
            )
            if result.get("ok"):
                if n:
                    result["fallback"] = (
                        f"{tried[0]['produto']} não deu ({tried[0]['reason']})"
                    )
                return result
            tried.append(result)

        # Nenhum serviu: devolve-se a primeira tentativa, com nota das outras.
        final = tried[0]
        if len(tried) > 1:
            final["tambem_falharam"] = [
                {"produto": t["produto"], "reason": t.get("reason")}
                for t in tried[1:]
            ]
        return final

    def _mark_done(self, items: list[dict], bought_terms: set[str]) -> int:
        """Põe o visto no Cookidoo nos itens que entraram mesmo no carrinho.

        Só nos que entraram: marcar um item que falhou faria desaparecer da
        lista uma coisa que continuas a precisar de comprar.

        Cada linha pode representar várias entradas do Cookidoo — três receitas
        a pedir cebola são três vistos a pôr, não um.
        """
        bought = {normalize(t) for t in bought_terms}
        ingredient_ids: list[str] = []
        additional_ids: list[str] = []
        for item in items:
            if normalize(item["name"]) not in bought:
                continue
            ingredient_ids += item["ids"]["receita"]
            additional_ids += item["ids"]["extra"]
        if not ingredient_ids and not additional_ids:
            return 0
        try:
            self.cookidoo.mark_owned(ingredient_ids, additional_ids)
        except CookidooError:
            return 0
        # A lista em cache deixou de refletir o Cookidoo.
        self._cached_list = None
        return len(ingredient_ids) + len(additional_ids)

    def status(self) -> dict:
        info = {"mappings": len(self.store),
                "mapping_file": str(self.store.path),
                "continente": self.continente.whoami()}
        try:
            self.cookidoo  # noqa: B018 - força a validação das credenciais
            info["cookidoo"] = "credenciais presentes"
        except CookidooError as exc:
            info["cookidoo"] = str(exc)
        return info


def _group_by_name(entries: list[dict]) -> list[dict]:
    """Junta numa linha as entradas que são o mesmo artigo.

    A lista do Cookidoo repete nomes: "cebola" vem de três receitas e ainda de
    ti, e há artigos adicionais escritos duas vezes. Cada entrada tem o seu
    `id`, mas para quem compra é tudo o mesmo produto — mostrar quatro linhas
    iguais só confunde.

    Duas decisões que o agrupamento obriga a tomar:

    * **Marcado** só quando *todas* as entradas estão marcadas. Se ainda há uma
      por marcar, ainda precisas de comprar.
    * **O nome** é o da primeira entrada, mas prefere-se um que comece por
      maiúscula: entre "cif creme" e "Cif creme", mostra-se o segundo.
    """
    groups: dict[str, dict] = {}
    for entry in entries:
        key = normalize(entry["name"])
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "key": key,
                "name": entry["name"],
                "amount": "",
                "amounts": [],
                "count": 0,
                "owned": True,
                "owned_count": 0,
                "source": entry["source"],
                "sources": {},
                "recipes": [],
                "ids": {"receita": [], "extra": []},
            }
        group["count"] += 1
        if entry["owned"]:
            group["owned_count"] += 1
        else:
            group["owned"] = False
        if entry["name"][:1].isupper() and not group["name"][:1].isupper():
            group["name"] = entry["name"]
        if entry["amount"] and entry["amount"] not in group["amounts"]:
            group["amounts"].append(entry["amount"])
        group["sources"][entry["source"]] = group["sources"].get(entry["source"], 0) + 1
        group["ids"][entry["source"]].append(entry["id"])
        for recipe in entry.get("recipes") or []:
            if recipe not in group["recipes"]:
                group["recipes"].append(recipe)

    for group in groups.values():
        group["amount"] = " · ".join(group["amounts"])
        # A origem dominante decide o crachá; "receita" ganha a "extra".
        group["source"] = "receita" if group["sources"].get("receita") else "extra"
        group["id"] = group["key"]   # identidade estável para a interface
    return list(groups.values())


def _counts(items: list[dict]) -> dict:
    out = {"total": len(items), "mapeado": 0, "por_decidir": 0, "ignorado": 0,
           "owned": 0, "a_comprar": 0}
    for i in items:
        out[i["status"]] = out.get(i["status"], 0) + 1
        if i.get("owned"):
            out["owned"] += 1
        elif i["status"] == "mapeado":
            out["a_comprar"] += 1
    return out
