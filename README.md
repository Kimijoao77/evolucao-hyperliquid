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

## Onde fica cada coisa

| Onde | O quê |
|---|---|
| ramo `main` | o código, os testes e `memoria/` (um arquivo por geração fechada: DNA, pais, medidas e motivo de saída de cada robô) |
| ramo `estado` | os dados vivos: `evolucao.json` (o resumo que o app lê), `estado.json` (a população), `universo.json`, `fills/` e `contas/` |

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
