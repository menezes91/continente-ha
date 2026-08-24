"""Constantes da integração."""

DOMAIN = "continente"

CONF_CONTINENTE_EMAIL = "continente_email"
CONF_CONTINENTE_PASSWORD = "continente_password"
CONF_COOKIDOO_EMAIL = "cookidoo_email"
CONF_COOKIDOO_PASSWORD = "cookidoo_password"

# O carrinho e a lista mudam devagar, e cada leitura é uma ida ao site.
DEFAULT_SCAN_MINUTES = 30
CONF_SCAN_MINUTES = "scan_minutes"

# Onde o painel aparece na barra lateral.
PANEL_URL_PATH = "continente"
PANEL_TITLE = "Continente"
PANEL_ICON = "mdi:cart-outline"

# Prefixo das rotas HTTP que a integração serve.
API_BASE = "/api/continente"

SERVICE_SEND_LIST = "enviar_lista"
SERVICE_ADD_PRODUCT = "adicionar_produto"
SERVICE_REMOVE_PRODUCT = "remover_produto"
SERVICE_SNAPSHOT_PRICES = "registar_precos"
SERVICE_EMPTY_CART = "esvaziar_carrinho"
