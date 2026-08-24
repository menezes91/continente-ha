"""Extração de dados do HTML do continente.pt."""
from __future__ import annotations

import html
import json
import re

from bs4 import BeautifulSoup

from .config import BASE

_PID_IN_URL = re.compile(r"-(\d{5,})\.html")
_CSRF = re.compile(r'name="csrf_token"\s+value="([^"]+)"')
_TOTAL_COUNT = re.compile(r'data-total-count="(\d+)"')


def csrf_token(page_html: str) -> str | None:
    m = _CSRF.search(page_html)
    return m.group(1) if m else None


def total_count(page_html: str) -> int | None:
    m = _TOTAL_COUNT.search(page_html)
    return int(m.group(1)) if m else None


def pid_from_url(product_url: str) -> str | None:
    """`.../banana-continente-continente-2597619.html` -> `2597619`."""
    m = _PID_IN_URL.search(product_url)
    return m.group(1) if m else None


def parse_products(page_html: str) -> list[dict]:
    """Produtos de uma página de resultados ou de sugestões.

    Baseia-se no JSON de tracking que cada tile transporta, e completa-o com o
    link e a imagem lidos do DOM à volta.
    """
    soup = BeautifulSoup(page_html, "lxml")
    out: list[dict] = []
    seen: set[str] = set()

    for node in soup.select("[data-product-tile-impression]"):
        raw = node.get("data-product-tile-impression")
        try:
            data = json.loads(html.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue

        pid = str(data.get("id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)

        out.append(
            {
                "pid": pid,
                "name": data.get("name"),
                "brand": data.get("brand") or None,
                "price": data.get("price"),
                "category": data.get("category") or None,
                "url": _product_link(node, pid),
                "image": _product_image(node, pid),
                **_tile_prices(node),
            }
        )
    return out


def _tile_prices(node) -> dict:
    """Preço de referência e preço por unidade, lidos do tile.

    Em promoção o tile traz `PVPR 5,99€` riscado ao lado do preço em vigor; é
    a única referência de "quanto custava" que o site dá.
    """
    scope = node
    for _ in range(5):
        if scope is None:
            break
        wrapper = scope.select_one(".prices-wrapper")
        if wrapper:
            listed = wrapper.select_one(".list")
            per_unit = scope.select_one(".pwc-tile--price-secondary")
            return {
                "list_price": _money(listed.get_text(" ", strip=True)) if listed else None,
                "price_per_unit": per_unit.get_text(" ", strip=True) or None if per_unit else None,
            }
        scope = scope.parent
    return {"list_price": None, "price_per_unit": None}


def _money(text: str) -> float | None:
    m = re.search(r"(\d+)[,.](\d{2})\s*€", text or "")
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def _product_link(node, pid: str) -> str | None:
    scope = node
    for _ in range(4):  # o <a> pode estar acima do nó que tem o JSON
        if scope is None:
            break
        a = scope.select_one("a[href*='/produto/']")
        if a and a.get("href"):
            href = a["href"].split("?")[0]
            return href if href.startswith("http") else BASE + href
        scope = scope.parent
    return None


def _product_image(node, pid: str = "", size: int = 120) -> str | None:
    """A foto do produto.

    Um tile traz mais imagens do que a do produto — o selo de desconto, a
    bandeira do país de origem. A foto certa é a do catálogo, e traz o `pid`
    no nome do ficheiro.
    """
    sources = []
    for img in node.select("img[src], img[data-src]"):
        src = img.get("src") or img.get("data-src") or ""
        if src and not src.startswith("data:"):
            sources.append(src.split("?")[0])

    def rank(src: str) -> int:
        if pid and pid in src:
            return 0
        if "master-catalog" in src and "/badges/" not in src:
            return 1
        if "/badges/" in src or "/flags/" in src:
            return 3
        return 2

    if not sources:
        return None
    best = min(sources, key=rank)
    if rank(best) == 3:  # só sobraram selos: melhor imagem nenhuma
        return None
    return f"{best}?sw={size}&sh={size}"


def parse_quantity_rules(pdp_html: str) -> dict:
    """Regras de quantidade de um produto, lidas da sua página.

    O continente.pt aceita silenciosamente quantidades inválidas e depois não
    adiciona nada, por isso é preciso conhecê-las antes de pedir.
    """
    text = html.unescape(pdp_html)

    def num(key: str) -> float | None:
        m = re.search(rf'"{key}"\s*:\s*([0-9]+(?:\.[0-9]+)?)', text)
        return float(m.group(1)) if m else None

    def unit(key: str) -> str | None:
        m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
        return m.group(1) if m else None

    return {
        "min_quantity": num("minOrderQuantity"),
        "step_quantity": num("stepQuantity"),
        "max_units": num("maxNumberOfUnitsPerSale"),
        "primary_unit": unit("primaryunit"),
        "secondary_unit": unit("secondaryunit"),
    }


def parse_product_page(pdp_html: str, product_url: str) -> dict:
    """Detalhe de um produto a partir da sua página."""
    soup = BeautifulSoup(pdp_html, "lxml")
    info: dict = {"pid": pid_from_url(product_url), "url": product_url}

    ld = soup.select_one("script[type='application/ld+json']")
    if ld and ld.string:
        try:
            data = json.loads(ld.string)
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Product"), data[0])
            info["name"] = data.get("name")
            info["brand"] = (data.get("brand") or {}).get("name")
            info["image"] = data.get("image")
            offers = data.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            info["price"] = _to_float(offers.get("price"))
            info["availability"] = offers.get("availability")
        except (json.JSONDecodeError, AttributeError, IndexError, KeyError):
            pass

    if not info.get("name"):
        h1 = soup.select_one("h1")
        info["name"] = h1.get_text(strip=True) if h1 else None

    btn = soup.select_one("button.add-to-cart[data-pid]")
    if btn:
        info["pid"] = btn.get("data-pid") or info["pid"]
        info["out_of_stock"] = btn.get("data-outofstock") == "true"

    info.update(parse_quantity_rules(pdp_html))
    info["price_per_unit"] = _price_per_unit(pdp_html)
    return info


def _price_per_unit(pdp_html: str) -> str | None:
    """O "0,24€/un" que o site mostra por baixo do preço."""
    m = re.search(r"\d+,\d{2}\s*€\s*/\s*\w+", html.unescape(pdp_html))
    return re.sub(r"\s+", "", m.group(0)) if m else None


def _to_float(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_basket(basket: dict) -> dict:
    """Normaliza o `basket` devolvido por `Cart-MiniCartShow`."""
    items = []
    for group in basket.get("itemsSortedByBrand") or []:
        for it in group.get("items") or []:
            total = it.get("priceTotal") or {}
            # `selectedDimension` vem por vezes com a string "undefined".
            unit = it.get("selectedDimension")
            items.append(
                {
                    "pid": it.get("id"),
                    "name": it.get("productName"),
                    "brand": it.get("brand"),
                    "quantity": it.get("secondaryQuantity"),
                    "unit": None if unit in (None, "undefined") else unit,
                    "unit_price": ((it.get("price") or {}).get("sales") or {}).get("value"),
                    "line_total": total.get("value"),
                    "line_total_formatted": total.get("price"),
                    "uuid": it.get("UUID") or it.get("uuid"),
                    "available": it.get("online", True),
                }
            )

    totals = basket.get("totals") or {}
    return {
        "items": items,
        "num_items": basket.get("numItems"),
        "subtotal": totals.get("subTotal"),
        "grand_total": totals.get("grandTotal"),
        "shipping": totals.get("totalShippingCost"),
        "products_total": totals.get("totalPriceProductsOnly"),
    }
