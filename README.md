# Evolução de robôs de copy trading (laboratório, sem dinheiro)

Uma população de robôs de copy trading que nasce, é testada, morre e se reproduz, na Hyperliquid. Roda em paralelo
aos testes do [radar-hyperliquid](https://github.com/Kimijoao77/radar-hyperliquid), sem tocar neles: aqui só se LÊ
o que o radar publica.

**Tudo é simulação.** Cada robô tem US$ 1.000 de mentira. Não existe ordem, chave nem conta neste repositório: o
código só consulta a API pública da Hyperliquid. Ligar um robô com dinheiro de verdade é decisão e ação do João, à
mão, fora daqui.

## A ideia

Um teste comum escolhe a melhor variação de uma amostra e para. Dois problemas: a "melhor" pode ser só a mais
sortuda daquela amostra, e uma regra fixa envelhece quando o mercado muda. Aqui a população inteira continua sendo
testada para sempre, geração após geração, e só tem filhos quem repete o bom resultado num período que ainda não
tinha acontecido quando foi escolhido.

**Só anda para a frente.** A primeira geração começou no dia em que a rotina foi ligada, com todo mundo zerado. O
resultado de um robô é só o que acontece depois que ele nasce. O passado entra de um jeito só: na ficha de cada
*trader*, que o robô consulta para decidir quem copiar (e a ficha só tem o que já se sabia naquele instante).

## O DNA: 14 genes em 4 blocos

| Bloco | Gene | O que decide | Faixa |
|---|---|---|---|
| Filtro | `janela_dias` | quantos dias do passado do trader o robô olha | 7 a 60 |
| Filtro | `min_operacoes` | mínimo de operações fechadas na janela | 5 a 60 |
| Filtro | `min_fator_lucro` | ganhos ÷ perdas mínimo na janela | 1,0 a 3,0 |
| Filtro | `duracao_min` | tempo mediano mínimo que o trader segura a posição | 5 a 240 min |
| Filtro | `max_carteiras` | quantos traders copia ao mesmo tempo | 1 a 10 |
| Filtro | `criterio` | como ordena os aprovados | fator de lucro, retorno ou constância |
| Alocação | `alvo` | exposição típica buscada em cada trader | 0,3× a 3× |
| Alocação | `revisao_dias` | de quantos em quantos dias revê quem copia | 1 a 7 |
| Risco | `parada` | queda desde o pico que faz largar um trader | 5 % a 25 % |
| Risco | `freio` | queda do robô inteiro que faz fechar tudo e descansar 3 dias | 8 % a 25 % |
| Risco | `corte` | perda numa posição que faz sair antes do trader | desligado ou 2 % a 30 % |
| Risco | `ganho` | lucro numa posição que faz sair antes do trader | desligado ou 3 % a 100 % |
| Risco | `tempo_max_h` | tempo máximo numa posição | desligado ou 6 a 240 h |
| Execução | `desvio_max` | quanto o preço pode ter fugido desde a ordem do trader para ainda entrar | 0,1 % a 3 % |

O DNA fica **congelado** a vida inteira do robô. Filho é outro robô, com história própria.

### O que NÃO é gene

Ficam no `config.json`, valem para todos e nenhum robô consegue mudar:

- **Ambiente:** atraso de 60 s depois da ordem do trader, taxa de 0,045 % e escorregamento de 0,05 % por ordem. São
  os mesmos números da cópia fiel do radar. Se fossem genes, a evolução "descobriria" que o melhor é atraso zero.
- **Limites duros:** exposição máxima de 3× o patrimônio, no máximo 50 % do robô num trader só, e abate com 30 % de
  queda desde o pico.

## Espécies

Quatro jeitos de ser, cada um com 10 vagas garantidas. Cada espécie aperta a faixa de alguns genes. As vagas
garantidas impedem que o vencedor de um período tome conta da população inteira.

| Espécie | Jeito | Genes apertados |
|---|---|---|
| Cautelosa | pouca exposição e paradas apertadas | alvo até 1×, parada até 12 %, freio até 12 % |
| Diversificada | copia muitos traders ao mesmo tempo | 6 a 10 traders, alvo de 0,5× a 2× |
| Curta | traders de operações rápidas, passado recente | duração de 5 a 45 min, janela de 7 a 21 dias, revisão a cada 1 ou 2 dias |
| Exigente | poucos traders, com filtro duro | 1 a 3 traders, fator de lucro de 1,8 para cima, 25 operações ou mais |

## O Predador

Tem duas funções separadas (`evolucao/predador.py`).

**1. Limites duros.** Quebrou, o robô é abatido na hora e não deixa descendentes. Nenhum lucro compensa.

**2. Fragilidade.** No fim de cada geração, cada robô recebe uma nota:

```
nota = min(r, r_estresse) − 0,5 × queda − 0,5 × max(0, r − r_sem_melhor)
```

- `r`: retorno da geração, já com taxas e escorregamento.
- `r_estresse`: o retorno da **conta gêmea**. Todo robô roda duas vezes com o mesmo DNA; a gêmea copia com 3 min de
  atraso e escorregamento 3 vezes maior. Quem só ganha com execução perfeita perde nota aqui.
- `queda`: a maior queda desde um pico dentro da geração.
- `r_sem_melhor`: o retorno tirando o trader que mais rendeu. Lucro que vem de um trader só vale metade.
- Quem não operou fica com nota 0: melhor que perder, mas sem direito a filhos.

A aptidão junta as últimas 4 gerações e pesa mais a pior:

```
aptidão = 0,6 × pior nota + 0,4 × média das notas
```

## A geração (14 dias)

Na virada, em cada espécie:

1. **Aprovado** é quem ficou na metade de cima da espécie, com nota positiva, pelo menos 10 ordens e nota acima da
   mediana do grupo de sorteio. Aprovado uma vez = *selecionado*. Aprovado em duas gerações **seguidas** =
   *confirmado*.
2. **Saem** os abatidos, os que ficaram 3 gerações sem operar e os de pior aptidão, até completar 30 % das vagas.
   Aprovado nunca sai.
3. **Nascem** para ocupar as vagas:
   - com 2 ou mais confirmados na espécie: filhos. Cada bloco de genes vem inteiro do pai ou da mãe (o filtro de um,
     a gestão de risco do outro) e depois passa por mutação. Em 10 % dos casos a mãe vem de outra espécie;
   - com 1 confirmado: mutantes dele;
   - sem confirmado: imigrantes, com DNA sorteado. Ninguém vira pai por ser "o menos ruim".
   - havendo 2 vagas ou mais, uma é sempre de imigrante.

Não operar é permitido: um robô cujo filtro não acha ninguém fica no caixa, e isso vale mais que perder.

## O controle: sorteio

Além dos 40 evoluídos vivem 12 robôs de **sorteio** (3 por espécie): DNA sorteado, mesmas regras, nunca se
reproduzem e são trocados no mesmo ritmo. É a busca aleatória com o mesmo orçamento de testes. Se, geração após
geração, os evoluídos não ganharem do sorteio, a evolução não está acrescentando nada, e é isso que o resumo mostra.
O "Copy trading" de regras fixas do radar aparece ao lado, no mesmo período, como a terceira régua.

## O universo de traders

O radar acompanha poucas carteiras, já aprovadas por ele. Para os robôs terem o que escolher, este repositório
mantém um universo próprio de até 120 carteiras (`evolucao/coletor.py`): as do radar e um **sorteio** entre as que
passam num pré-filtro do ranking da Hyperliquid. Quem para de operar por 30 dias sai da coleta; quem é liquidado e
fica com a conta quase zerada é marcado como "quebrou". Os dois continuam registrados.

Saldo zerado numa foto não quer dizer quebra: muita carteira tira o dinheiro da conta de perpétuos quando não tem
posição aberta. Para copiar na proporção certa vale a última foto com saldo; sem nenhuma, o saldo de referência do
ranking (a mesma saída do radar).

## Outras famílias: robôs de preço

A mesma evolução (espécies com vagas garantidas, sorteio de controle, Predador, gerações de 14 dias, filhos só de
confirmados) também roda com robôs que **não copiam ninguém**: cada um opera uma moeda sozinho, olhando só o preço
(velas de 1 hora) e o funding (`evolucao/precos/`). Os simuladores vêm do laboratório de grade do radar.

| Espécie | Letra | Jeito | Genes do sinal |
|---|---|---|---|
| Tendência | T | comprado na alta, vendido na queda | cruzamento de médias (rápida 6 a 96 h, lenta 2 a 8 vezes a rápida) ou rompimento de canal (24 a 360 h) |
| Reversão | V | compra depois da queda forte em 24 h e sai no repique | gatilho 3 % a 15 %, alvo 1 % a 6 %, só compra ou também vende na alta |
| Grade | G | compra embaixo e vende em cima, dentro de uma faixa | faixa ±4 % a ±30 %, 5 a 30 degraus |
| DCA | A | compra mais a cada queda e vende tudo no alvo | passo 1 % a 6 %, alvo 1 % a 5 %, pausa abaixo de uma média de 24 a 336 h (ou sem pausa) |

Genes de todas: a **moeda** (BTC, ETH, SOL, HYPE, XRP, AVAX, kPEPE, NEAR), a **alavancagem** (1× a 3×) e o **freio**
(queda de 8 % a 25 % desde o pico que faz fechar tudo e descansar 3 dias, ou desligado).

O que muda em relação ao copy trading:

- **A conta é refeita do nascimento a cada rodada.** As velas fechadas não mudam, então o passado dá sempre o mesmo
  resultado e não existe carteira guardada para corromper (`evolucao/familia.py`).
- **Estresse:** na conta gêmea as ordens limitadas pagam a taxa de quem executa a mercado e o escorregamento é 3 vezes
  maior.
- **Concentração:** em vez do "sem o melhor trader", a nota desconta metade do lucro do melhor **dia** da geração.
- **Mínimo de ordens para aprovar:** 4 (um robô de tendência opera pouco).
- **Régua de fora:** segurar BTC no mesmo período.
- **Funding entra na conta** (o histórico real da Hyperliquid, hora a hora).

O app lê `precos.json` no ramo `estado`. A memória das gerações fica em `memoria/precos/`.

## Outras famílias: cofres

Robôs que **não operam**: escolhem em quais cofres (vaults) da Hyperliquid depositar, quanto pôr em cada um e quando
sair (`evolucao/cofres/`). Quem opera é o dono do cofre, que fica com a comissão do cofre sobre o lucro (o HLP não
cobra).

| Bloco | Gene | O que decide | Faixa |
|---|---|---|---|
| Filtro | `janela_dias` | quantos dias do histórico do cofre o robô olha | 30 a 365 |
| Filtro | `criterio` | maior retorno, mais semanas no azul ou retorno ÷ queda | |
| Filtro | `max_queda` | a maior queda aceita no histórico olhado | 5 % a 60 % |
| Filtro | `min_idade_dias` | idade mínima do cofre | 30 a 365 dias |
| Filtro | `min_tvl` | dinheiro mínimo no cofre | US$ 100 mil a 20 milhões |
| Alocação | `n_cofres` | em quantos cofres de trader divide | 1 a 8 |
| Alocação | `peso_hlp` | parte fixa no HLP | desligado ou 10 % a 100 % |
| Alocação | `revisao_dias` | de quanto em quanto tempo revê | 7 a 60 dias |
| Risco | `parada` | queda desde o pico num cofre que faz sair dele até a próxima revisão | desligado ou 5 % a 40 % |

Espécies: **Âncora** (H, metade ou mais no HLP), **Diversificada** (D, 4 a 8 cofres), **Agressiva** (X, só retorno,
aceita queda grande) e **Constante** (K, queda pequena, janela longa).

- Os cofres são lidos de 6 em 6 horas: os 60 maiores que passam no pré-filtro (abertos, US$ 100 mil ou mais, 30 dias
  ou mais), o HLP e todos que já estavam guardados. Na primeira vez entra o histórico inteiro do cofre (o passado que
  um robô pode olhar); depois cada leitura só **acrescenta** um ponto, e o que já estava guardado nunca muda.
- Um depósito fica preso 1 dia (4 no HLP). Cofres-filho (os pedaços do HLP) ficam de fora: ninguém deposita neles.
- **Estresse:** cada depósito e cada saque só acontece 1 dia depois da decisão, e a comissão é 5 pontos maior.
- Mínimo de ordens para aprovar: 1 (um depósito). **Régua:** deixar tudo no HLP.

O app lê `cofres.json` no ramo `estado`. A memória das gerações fica em `memoria/cofres/`.

## Outras famílias: moedas novas

Robôs que **vendem (short) moeda recém-listada** na Hyperliquid, esperando a queda que costuma vir nas semanas depois
da estreia (`evolucao/listagens/`). A estreia de uma moeda é a hora do primeiro funding dela.

| Bloco | Gene | O que decide | Faixa |
|---|---|---|---|
| Entrada | `espera_h` | quantas horas depois da estreia vende | 1 a 336 |
| Entrada | `teto_estreia` | só vende se o preço estiver abaixo de X vezes o da estreia | desligado ou 0,6 a 3 |
| Saída | `parada` | subiu isso desde a venda: sai | 8 % a 80 % |
| Saída | `alvo` | caiu isso desde a venda: sai com lucro | desligado ou 8 % a 80 % |
| Saída | `prazo_dias` | sai depois de tantos dias | 1 a 30 |
| Risco | `parte` | margem de cada moeda, em fração do patrimônio | 3 % a 25 % |
| Risco | `alav` | alavancagem | 1× a 3× |
| Risco | `max_abertas` | moedas vendidas ao mesmo tempo | 2 a 15 |

Espécies: **Rápida** (R), **Paciente** (P), **Apertada** (J, parada curta e alvo) e **Espaçosa** (E, parada larga e
pouca margem). Custos: 0,045 % de taxa e 0,1 % de escorregamento em cada ponta e o funding real (vendido recebe
quando é positivo). Passou do ponto de liquidação: perde a margem daquela moeda. **Estresse:** escorregamento de 0,3 %
e entrada 1 hora depois. **Régua:** a regra fixa do laboratório de moedas novas do radar (vende 24 h depois, 10 % por
moeda, sai se subir 30 % ou em 14 dias). Moedas novas são poucas: muitos robôs passam uma geração sem operar, e
mínimo para aprovar é 1 ordem.

## Outras famílias: pools concentradas

Robôs que põem dinheiro em **pools de liquidez concentrada** (DLMM da Meteora, na Solana) e ganham a taxa de quem
troca enquanto o preço fica dentro da faixa (`evolucao/pools/`). A conta da posição é a do laboratório de pools do
radar (valor em SOL/USDC, fatia da taxa contra as posições típicas da pool, dividida com o nosso dinheiro).

| Bloco | Gene | O que decide | Faixa |
|---|---|---|---|
| Pool | `criterio` | maior taxa sobre o dinheiro em 24 h, na última hora, ou mais volume | |
| Pool | `balanco_max` | só pools com o preço calmo (desvio das variações de 1 h em 24 h) | desligado ou 0,5 % a 6 % |
| Pool | `tvl_min` | dinheiro mínimo na pool | US$ 10 mil a 2 milhões |
| Posição | `posicao` | faixa logo abaixo do preço (só SOL/USDC) ou centrada (troca metade) | |
| Posição | `r` | largura da faixa (abaixo: até −2r; centrada: ±r) | 1 % a 35 % |
| Posição | `n_pools` | em quantas pools divide | 1 a 5 |
| Saída | `prazo_h` | sai depois de tantas horas | 4 a 96 |
| Saída | `espera_acima_h` | preço acima da faixa: espera tantas horas e reabre | 1 a 12 |

Espécies: **Estreita** (N), **Larga** (L), **Calma** (C) e **Rápida** (Q). A cada rodada são lidas as 12 pools
elegíveis de maior taxa (SOL ou USDC do outro lado, US$ 10 mil ou mais, US$ 50 mil de volume) e as que já estavam
sendo seguidas, com velas de 5 min do GeckoTerminal. **Estresse:** a posição leva metade da fatia da taxa e o
escorregamento dobra. **Régua:** a regra fixa do radar (faixa estreita, 3 pools calmas, 24 h).

## Onde fica cada coisa

| Onde | O quê |
|---|---|
| ramo `main` | o código, os testes e `memoria/` (um arquivo por geração fechada: DNA, pais, medidas e motivo de saída de cada robô) |
| ramo `estado` | os dados vivos: `evolucao.json` (o resumo que o app lê), `estado.json` (a população), `universo.json`, `fills/` e `contas/`; de cada outra família (`precos`, `cofres`, `listagens`, `pools`), `<família>.json` (o resumo que o app lê), `<família>/estado.json` (a população) e os dados de mercado dela |

O ramo `estado` é regravado a cada rodada como um commit só, sem histórico. O repositório não cresce com os anos.

A rotina roda no GitHub Actions de 2 em 2 horas (`.github/workflows/evolucao.yml`).

## Limites deste teste, sem enfeite

- **Funding não entra na conta**, igual à cópia fiel do radar. Em posições de dias isso pesa.
- **O preço é o do minuto** (velas), não o livro de ofertas. O escorregamento é uma estimativa fixa.
- **14 dias é pouco.** Uma geração boa é quase sempre sorte; por isso só a segunda seguida conta, e mesmo assim
  "confirmado" quer dizer "merece continuar sendo observado", não "funciona".
- **Quanto mais robôs, mais sortudos.** Com 40 tentativas por geração sempre haverá algum com resultado ótimo. As
  réguas honestas são a mediana dos evoluídos contra a do sorteio e o que se repete entre gerações.
- **O universo começa com quem ia bem no mês.** O pré-filtro do ranking pega carteiras em fase boa; parte delas
  volta à média logo depois. Isso vale igual para evoluídos e sorteio, então a comparação entre eles continua justa.
- Nada aqui é recomendação de investimento.

## Rodar os testes

```
pip install -r requirements.txt pytest
python -m pytest -q
```
