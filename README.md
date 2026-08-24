# Continente — integração para Home Assistant

Leva a lista de compras do Cookidoo para o carrinho do continente.pt, segue os
preços dos produtos que compras, e põe tudo dentro do Home Assistant.

> Projeto pessoal, **sem qualquer ligação ao Continente / MC Sonae nem à
> Vorwerk**. Usa endpoints internos dos sites, que podem mudar sem aviso, e
> serve para gerir a tua própria conta.

> **Ainda não foi testada num Home Assistant a sério.** Foi escrita a partir da
> versão autónoma — essa sim, verificada a funcionar contra o site — mas a
> máquina onde foi feita não corre Home Assistant. Conta com uns ajustes na
> primeira instalação, e vê os *logs*.

## O que traz

**Painel próprio na barra lateral** — a app de mapeamento e os gráficos de
preços, servidos pela própria integração.

**Sensores**

| | |
|---|---|
| `sensor.continente_total_do_carrinho` | valor do carrinho, com os produtos nos atributos |
| `sensor.continente_artigos_no_carrinho` | quantos artigos lá estão |
| `sensor.continente_por_comprar` | itens da lista prontos a ir |
| `sensor.continente_por_decidir` | itens à espera de produto |
| `sensor.continente_preco_<produto>` | um por produto seguido |

Os sensores de preço são a razão principal para isto viver no Home Assistant:
o histórico passa a ser do *recorder*, com gráficos nativos e automações a
sério.

**Botões** — enviar a lista, registar os preços de hoje, esvaziar o carrinho.

**Serviços** — `continente.enviar_lista`, `continente.adicionar_produto`,
`continente.remover_produto`, `continente.registar_precos`,
`continente.esvaziar_carrinho`.

## Instalação

### Por HACS

**HACS → Integrações → ⋮ → Repositórios personalizados**, cola
`https://github.com/menezes91/continente-ha`, categoria **Integration**.
Instala, reinicia o Home Assistant.

### À mão

Copia `custom_components/continente/` para o teu `config/custom_components/` e
reinicia.

### Configurar

**Definições → Dispositivos e Serviços → Adicionar → Continente**, e mete as
credenciais no formulário. **É só aí** — não há ficheiros de configuração nem
variáveis de ambiente; ficam guardadas pelo Home Assistant com o resto.

As do Cookidoo são opcionais: sem elas ficas com o carrinho e os preços, mas
não com a lista de compras.

As credenciais são validadas contra os sites antes de a configuração ser
guardada — se forem recusadas, a configuração não avança.

## Onde ficam os dados

Em `config/continente/`:

```
sessao.json                    cookies da sessão
mapeamento_cookidoo.csv        as tuas decisões (editável à mão)
meus_produtos_continente.csv   produtos que já compras
precos.db                      histórico de preços
cookidoo_cookies.pickle        sessão do Cookidoo
```

Fica fora da integração de propósito, para sobreviver a atualizações. Se vens
da versão autónoma, copia para lá os teus ficheiros e as decisões vêm contigo.

## Automações

```yaml
automation:
  # Enviar a lista todas as quintas às 18h
  - alias: Compras de quinta
    triggers:
      - trigger: time
        at: "18:00:00"
    conditions:
      - condition: time
        weekday: [thu]
    actions:
      - action: continente.enviar_lista

  # Registar os preços todas as manhãs
  - alias: Preços diários
    triggers:
      - trigger: time
        at: "09:00:00"
    actions:
      - action: continente.registar_precos

  # Avisar quando um produto fica bem mais barato
  - alias: Baixou de preço
    triggers:
      - trigger: numeric_state
        entity_id: sensor.continente_preco_papel_higienico_4_folhas_grand_royal_renova
        below: 12
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            Papel higiénico a
            {{ states('sensor.continente_preco_papel_higienico_4_folhas_grand_royal_renova') }}€
```

## Notas

- **Sem browser.** O login é um OAuth2 PKCE contra a API do SSO — quatro
  pedidos, cerca de cinco segundos. É o que permite isto correr num container.
  A sessão do continente.pt expira depressa e é renovada sozinha.
- **As rotas do painel correm sem autenticação** (`requires_auth = False`),
  porque um iframe não leva o token do Home Assistant. Ficam ao alcance de quem
  já chega ao teu Home Assistant na rede local; não as exponhas à internet sem
  uma camada à frente.
- A biblioteca está em `custom_components/continente/lib/` e é a mesma da
  versão autónoma, sem o Selenium e sem o FastAPI.
- A biblioteca é síncrona; todas as idas ao site correm no executor, nunca no
  *event loop*.

## A versão autónoma

O projeto original corre sem Home Assistant nenhum, com linha de comandos, modo
explorer e a mesma app web. Está na pasta `continente/`, ao lado desta, e o seu
README ficou aqui como [README_original_autonomo.md](README_original_autonomo.md)
— é onde está explicado como o site funciona por dentro.
