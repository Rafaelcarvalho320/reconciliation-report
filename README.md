# reconciliation-report

[![CI](https://github.com/Rafaelcarvalho320/reconciliation-report/actions/workflows/ci.yml/badge.svg)](https://github.com/Rafaelcarvalho320/reconciliation-report/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Compara dois sistemas que deveriam concordar sobre os mesmos dados e aponta
cada divergência: o que falta de cada lado, quais campos discordam, quais
chaves aparecem duas vezes e quais linhas não têm chave nenhuma.

Sem dependências de runtime. Biblioteca e CLI.

> *[English summary below](#english-summary)*

## O problema

Todo mundo que integra dois sistemas acaba escrevendo o mesmo script: carrega
os dois CSVs em dicionários, compara, imprime as diferenças. E aí descobre que
o script acusa **tudo** como divergente.

Não é que os sistemas discordem dos dados. Eles discordam de **como escrever**
os dados:

| ERP | Loja | São a mesma coisa? |
| --- | --- | --- |
| `00101` | `101` | Sim — zero à esquerda |
| `1.250,00` | `1250.00` | Sim — separador decimal |
| `123.456.789-00` | `12345678900` | Sim — pontuação do CPF |
| `PAID` | `paid` | Sim — caixa |
| `04/03/2026` | `2026-03-04` | Sim — formato de data |
| `2.300,50` | `2300.51` | Depende — um centavo de arredondamento |

Comparar valor bruto reporta tudo isso como diferença e **enterra** as três
linhas que realmente divergem. É por isso que a maior parte deste projeto são
normalizadores, não o algoritmo de comparação.

## Vendo funcionar

Os arquivos em `examples/` são dois extratos do mesmo dia, exportados por dois
sistemas com opiniões diferentes sobre formatação. Comparando de forma ingênua:

```console
$ reconcile examples/erp_orders.csv examples/shop_orders.csv \
    --key order_id --compare total,status,customer_doc

Reconciliation: erp_orders.csv vs shop_orders.csv   [14 PROBLEM(S)]
  matched      0
  mismatched   0
  only in erp_orders.csv    6
  only in shop_orders.csv   6
```

Zero coincidências. Agora dizendo **como ler cada campo**:

```console
$ reconcile examples/erp_orders.csv examples/shop_orders.csv \
    --key order_id --compare total,status,customer_doc \
    --normalize order_id=integer --normalize total=money \
    --normalize status=lower --normalize customer_doc=digits \
    --tolerance total=0.01 \
    --left-name ERP --right-name Loja

Reconciliation: ERP vs Loja   [5 PROBLEM(S)]
========================================================================
  key      : order_id
  compared : total, status, customer_doc

  ERP: 8 record(s)
  Loja: 6 record(s)

  matched      4
  mismatched   1
  only in ERP   1
  only in Loja   1
  duplicate keys   1 / 0
  unkeyed rows     1 / 0

Mismatched (1)
------------------------------------------------------------------------
  103
      status: ERP='pending'  Loja='shipped'

Only in ERP (1)
------------------------------------------------------------------------
  105

Only in Loja (1)
------------------------------------------------------------------------
  107

Duplicate keys (1)
------------------------------------------------------------------------
  ERP: 106 x2

Unkeyed rows (1)
------------------------------------------------------------------------
  ERP: missing key field(s): order_id
```

De 14 ruídos para **5 divergências reais**. O centavo de diferença no pedido
104 foi perdoado pela tolerância; id com zero à esquerda, CPF pontuado e moeda
em formato brasileiro passaram a bater.

## Instalação

```bash
pip install git+https://github.com/Rafaelcarvalho320/reconciliation-report.git
```

## Normalizadores

| Nome | Efeito | Resolve |
| --- | --- | --- |
| `text` | Corta espaços, colapsa espaços repetidos | *(padrão)* |
| `lower` | Ignora caixa | `PAID` vs `paid` |
| `unaccented` | Ignora caixa e acento | `São Paulo` vs `Sao Paulo` |
| `integer` | Identidade numérica | `00042` vs `42` |
| `digits` | Só os dígitos | `123.456.789-00` vs `12345678900` |
| `money` | `Decimal`, aceita os dois formatos | `1.234,56` vs `1234.56` |
| `date` | Data de calendário, ignora hora | `04/03/2026` vs `2026-03-04T23:59` |
| `boolean` | As várias grafias de sim e não | `1`, `true`, `sim` |

Todos tratam `""`, `-`, `N/A`, `null` e `NaN` como ausência de valor, porque
cada exportador escolhe um deles.

**`money` devolve `Decimal`, nunca `float`.** Em ponto flutuante binário
`0.1 + 0.2 != 0.3`, e numa conciliação isso significa inventar diferenças de
centésimo de centavo e reportá-las como reais. Tem teste cobrindo exatamente
esse caso.

**`date` reduz timestamp a data.** Comparar uma data contra um timestamp é uma
verificação que falha o dia inteiro e passa à meia-noite — o tipo de bug que
leva uma semana para ser notado.

## Saída

Quatro formatos, porque a resposta é lida por públicos diferentes:

```bash
reconcile a.csv b.csv --key id --format text       # terminal (padrão)
reconcile a.csv b.csv --key id --format json       # dashboard, pipeline
reconcile a.csv b.csv --key id --format csv        # planilha
reconcile a.csv b.csv --key id --format markdown   # comentário de PR, ticket
```

No JSON, valores monetários saem como **string**, não como número. Serializar
`Decimal` para float reintroduziria justamente o erro de arredondamento que o
projeto inteiro existe para evitar.

## Códigos de saída

O lugar mais útil para rodar uma conciliação é um job agendado que precisa
decidir se acorda alguém:

| Código | Significado |
| --- | --- |
| `0` | Os dois lados concordam |
| `1` | Foram encontradas divergências |
| `2` | A execução falhou: arquivo inexistente, coluna errada, schema inválido |

Separar `1` de `2` não é preciosismo. Se fossem o mesmo código, um erro de
digitação no nome de uma coluna ficaria **idêntico a uma noite limpa** — que é
a pior falha possível para um job de monitoramento.

```bash
reconcile erp.csv loja.csv --key order_id --compare total || notificar-time
```

## Como biblioteca

O CLI é uma casca fina. A mesma coisa em Python, lendo de onde você quiser:

```python
from decimal import Decimal
from reconciler import CallableSource, Schema, as_markdown, reconcile

schema = Schema.build(
    key=["order_id"],
    compare=["total", "status"],
    normalizers={"order_id": "integer", "total": "money", "status": "lower"},
    tolerances={"total": Decimal("0.01")},
)

resultado = reconcile(
    CallableSource(lambda: Pedido.objects.values("order_id", "total", "status")),
    CallableSource(buscar_pedidos_da_api),
    schema,
    left_name="ERP",
    right_name="Loja",
)

if not resultado.is_clean:
    print(as_markdown(resultado))
```

Uma fonte é **qualquer coisa que produza dicionários**. Esse contrato
deliberadamente pequeno é o que deixa a mesma conciliação rodar contra um CSV
hoje e contra um cursor de banco ou uma API paginada amanhã, sem o código de
comparação aprender nada sobre nenhum dos dois.

## Decisões de projeto

**Chave duplicada não é "divergência", é dado quebrado — e conta como problema.**
Se o mesmo id aparece duas vezes de um lado, a conciliação não sabe qual linha
comparar. Ela compara a primeira, reporta a chave como duplicada e **não se
declara limpa**. Dizer "tudo certo" enquanto uma comparação não foi realmente
feita seria mentir sobre o que foi verificado.

**Linha sem chave é contada à parte.** Uma linha com `order_id` vazio não é
"faltando no outro lado" — é uma linha quebrada. Jogá-la no balde de ausentes
esconderia um problema de qualidade de dado dentro de um relatório de
divergência.

**Campo-chave não pode ser comparado.** Linhas só se encontram quando as chaves
já batem, então comparar a chave nunca produziria diferença. Aceitar isso em
silêncio prometeria uma verificação que não faz nada; o schema recusa.

**Tolerância não aproxima ausência de zero.** `None` e `0,00` são fatos
diferentes — "não informado" e "informado como zero". Nenhuma tolerância, por
maior que seja, faz os dois virarem o mesmo.

**É um hash join, e isso tem consequência.** O lado direito vai para a memória,
o esquerdo é percorrido em fluxo. Quando um extrato é muito maior que o outro,
**coloque o grande à esquerda**. Um sort-merge join não guardaria nenhum dos
dois lados, mas exigiria as duas entradas ordenadas pela mesma chave
normalizada — que um CSV exportado de um sistema qualquer não é.

**Emoji no relatório não pode derrubar a execução.** O console do Windows ainda
usa uma code page legada por padrão, onde um caractere fora do ASCII levanta
`UnicodeEncodeError` e mata o processo. A saída pede UTF-8 e, se não conseguir,
degrada para ASCII — um relatório um pouco mais feio é melhor que um traceback.

## Desenvolvimento

```bash
python -m venv .venv && source .venv/Scripts/activate   # Linux/macOS: .venv/bin/activate
pip install -e ".[dev]"

pytest                  # 122 testes
ruff check . && ruff format --check .
mypy                    # strict
```

```
src/reconciler/
    normalizers.py   como ler cada valor: dinheiro, documento, data, texto
    schema.py        chave, campos comparados, tolerâncias
    sources.py       CSV, JSON, JSON Lines, iterável, callable
    core.py          o hash join e a classificação das diferenças
    report.py        texto, JSON, CSV e markdown
    cli.py           argumentos e códigos de saída
examples/            dois extratos do mesmo dia, formatados de forma diferente
tests/               122 testes
```

## English summary

Compares two systems that ought to agree about the same data and reports every
way they do not: rows missing from either side, fields that disagree, keys that
appear twice, and rows that cannot be keyed at all. A library and a CLI, with
no runtime dependencies.

The interesting part is not the comparison, it is the **normalization**. Two
systems rarely disagree about the data; they disagree about how it is written.
`00101` and `101`, `1.234,56` and `1234.56`, `PAID` and `paid` are the same
value, and a reconciliation that reports them as differences buries the three
rows that genuinely differ. On the bundled example that is the difference
between 14 findings and 5 real ones.

Decisions worth knowing:

- **Money is `Decimal`, never `float`.** `0.1 + 0.2 != 0.3` in binary floating
  point, which in a reconciliation means inventing sub-cent differences and
  reporting them as real.
- **Duplicate keys and unkeyed rows are problems, not differences**, and they
  keep the result from calling itself clean — otherwise it would be reporting
  on a comparison it never actually made.
- **Tolerance never merges `None` with `0.00`.** "Not reported" and "reported
  as zero" are different facts.
- **Exit codes separate "differences found" (1) from "the run failed" (2)**, so
  a typo in a column name can never look like a clean night to a cron job.
- **It is a hash join**: the right side is held in memory, the left is streamed.
  Put the bigger export on the left. The constraint is documented rather than
  hidden.

Code and docstrings are in English; the sections above are in Portuguese.

## Licença

MIT. Veja [LICENSE](LICENSE).
