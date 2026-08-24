"""Constantes e caminhos partilhados.

Ao contrário da versão autónoma, aqui os ficheiros não vivem ao lado do código:
o Home Assistant tem o seu diretório de configuração, e é lá que a sessão, o
mapeamento e o histórico de preços têm de ficar para sobreviverem a uma
atualização da integração. Quem manda é `set_data_dir()`, chamada no arranque.
"""
from pathlib import Path

BASE = "https://www.continente.pt"
SITE_ID = "Sites-continente-Site"
LOCALE = "default"
CTRL = f"{BASE}/on/demandware.store/{SITE_ID}/{LOCALE}/"

# Onde se vê o carrinho no site. Tem de ser o controller: ele prepara o estado
# e só depois redireciona para /checkout/carrinho/ — ir lá diretamente devolve
# a homepage, e /carrinho/ dá 404.
CART_URL = CTRL + "Cart-Show"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Até `set_data_dir()` correr, os dados ficam ao lado do código — serve para
# quem use a biblioteca fora do Home Assistant.
DATA_DIR = Path(__file__).resolve().parent

SESSION_FILE = DATA_DIR / "sessao.json"
MAPPING_FILE = DATA_DIR / "mapeamento_cookidoo.csv"
KNOWN_PRODUCTS_FILE = DATA_DIR / "meus_produtos_continente.csv"
PRICES_FILE = DATA_DIR / "precos.db"
COOKIDOO_COOKIES = DATA_DIR / "cookidoo_cookies.pickle"


def set_data_dir(path) -> None:
    """Define onde ficam os dados persistentes (`config/continente/`)."""
    global DATA_DIR, SESSION_FILE, MAPPING_FILE, KNOWN_PRODUCTS_FILE
    global PRICES_FILE, COOKIDOO_COOKIES

    DATA_DIR = Path(path)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE = DATA_DIR / "sessao.json"
    MAPPING_FILE = DATA_DIR / "mapeamento_cookidoo.csv"
    KNOWN_PRODUCTS_FILE = DATA_DIR / "meus_produtos_continente.csv"
    PRICES_FILE = DATA_DIR / "precos.db"
    COOKIDOO_COOKIES = DATA_DIR / "cookidoo_cookies.pickle"


# Cookies que transportam a identidade/sessão SFCC. Só estes são exportados.
SESSION_COOKIE_PREFIXES = (
    "dwsid",
    "dwsecuretoken_",
    "dwanonymous_",
    "dwac_",
    "sid",
    "cqcid",
    "cquid",
    "__cq_dnt",
    "dw_dnt",
    "dwpersonalization_",
    "storeContext",
    "selectedStore",
)


def url(controller: str) -> str:
    """`Cart-AddProduct` -> URL completo do controller."""
    return CTRL + controller
