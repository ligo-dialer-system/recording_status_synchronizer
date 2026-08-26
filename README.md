# recording_status_synchronizer

Serviço batch (execução única, pensado para rodar via `cron`) que lê os arquivos de
log gerados pela rotina de cópia de gravações (`copy_rec_success`), extrai os metadados
de cada gravação e atualiza o registro correspondente no banco `RECORD_MANAGER`
(SQL Server) através da stored procedure `SPR_RM_UPD_AUDIO_FILE`.

Falhas de atualização não derrubam o processamento: cada linha com falha é reenfileirada
numa fila de retry com backoff exponencial e, após esgotar as tentativas, é movida para
uma fila de *dead letter* para intervenção manual.

## Como funciona

Para cada execução (`python main.py`):

1. **Lock de execução** — tenta adquirir um lock exclusivo (`fcntl.flock`) no arquivo
   definido em `paths.lock_file`. Se outra execução ainda estiver em andamento, o
   processo é encerrado sem fazer nada (evita duas instâncias processando os mesmos
   arquivos ao mesmo tempo).
2. **Descoberta de projetos** — lista os diretórios existentes em `paths.source_rep`;
   cada subdiretório é tratado como um "projeto" independente.
3. Para cada projeto:
   - **Reprocessa a fila de retry** (`copy_log_error/retry_queue`): reenvia os itens
     cujo horário de "próxima tentativa" já venceu.
   - **Processa os arquivos pendentes** (`copy_log_pending`): arquivos ordenados por
     data de modificação, ignorando aqueles modificados no minuto corrente (para não
     pegar um arquivo que ainda está sendo escrito).
4. Cada arquivo pendente é lido linha a linha. Cada linha é uma gravação, no formato
   `CHAVE=valor;CHAVE=valor;...`. Para cada linha:
   - os campos são parseados (`parsing.parse_line`);
   - a stored procedure `SPR_RM_UPD_AUDIO_FILE` é chamada com
     `NM_DEVICE`, `NM_FILE`, `ID_PROJECT`, `MUST_MERGE_FILES`;
   - se a chamada falhar (exceção, retorno `0` — SP recusou — ou `-1` — falha de
     infraestrutura), a linha é enfileirada na fila de retry.
5. Ao final do arquivo:
   - **sem falhas** → arquivo movido para `copy_log_success/`;
   - **com alguma falha** → arquivo movido para `copy_log_partial/` (as linhas que
     falharam já foram enfileiradas separadamente na fila de retry).

### Fila de retry e dead letter

Implementada em [retry_queue.py](retry_queue.py), dentro de cada diretório de projeto:

```
<projeto>/copy_log_error/retry_queue/    # itens aguardando nova tentativa
<projeto>/copy_log_error/dead_letter/    # itens que esgotaram as tentativas
```

- Cada item da fila é um arquivo `<epoch_proxima_tentativa>__a<tentativas>__<uuid>.retry`
  contendo a linha original serializada, mais os campos internos `LAST_ERROR` e
  `SRC_FILE` (nome do arquivo de origem, para rastreabilidade).
- O backoff entre tentativas é definido por `retry.backoff_seconds` (uma lista, indexada
  pelo número de tentativas já feitas) e o número máximo de tentativas por
  `retry.max_retries`.
- Ao esgotar `max_retries`, o item é movido para `dead_letter/` e um log de erro é
  emitido pedindo intervenção manual — nada é descartado silenciosamente.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| [main.py](main.py) | Ponto de entrada. Orquestra lock, descoberta de projetos, processamento de pendentes e configuração de logging. |
| [config.py](config.py) | Carrega `config.yml` (cacheado em memória), com caminho sobrescrevível pela variável de ambiente `COPY_DAY_UPDATE_CONFIG`. |
| [config.yml](config.yml) | Configuração de bancos de dados, caminhos, política de retry e nível de log. |
| [connection.py](connection.py) | `DBConnection`: wrappers de execução de comandos para SQL Server (`pyodbc`) e MySQL (`pymysql`). |
| [file_ops.py](file_ops.py) | Operações de filesystem: lock por `fcntl`, listagem de projetos/arquivos pendentes, mover arquivos. |
| [parsing.py](parsing.py) | Serialização/deserialização das linhas no formato `CHAVE=valor;CHAVE=valor`. |
| [retry_queue.py](retry_queue.py) | Fila de retry com backoff exponencial e fila de dead letter. |
| [log_manager/log_config.py](log_manager/log_config.py) | `LogConfig`: configuração de logging (stdout colorido + arquivo com rotação diária, 5 backups). |
| [requirements.txt](requirements.txt) | Dependências Python do projeto. |

## Configuração

O arquivo [config.yml](config.yml) segue esta estrutura:

```yaml
database:
  sqlserver:
    driver: "ODBC Driver 17 for SQL Server"
    server: "<host>"
    database: "<database>"
    uid: "<usuario>"
    pwd: "<senha>"
  mysql:
    host: "<host>"
    user: "<usuario>"
    password: "<senha>"
    db: "<database>"

paths:
  source_rep: "/caminho/para/copy_rec_success/"   # raiz com um subdiretório por projeto
  log_dir: "/caminho/para/logs"
  lock_file: "/caminho/para/rec_status_sync.lock"

retry:
  max_retries: 5
  backoff_seconds: [300, 900, 3600, 21600, 86400]

logging:
  level: "INFO"
```

> **Atenção — credenciais em texto plano:** o `config.yml` versionado neste projeto
> contém credenciais reais de acesso aos bancos SQL Server e MySQL. Trate este arquivo
> como segredo (não o exponha publicamente, restrinja permissões de leitura, considere
> movê-lo para fora do controle de versão e usar `COPY_DAY_UPDATE_CONFIG` para apontar
> para um arquivo local fora do repositório).

O caminho do arquivo de configuração pode ser sobrescrito com a variável de ambiente:

```bash
export COPY_DAY_UPDATE_CONFIG=/caminho/alternativo/config.yml
```

### Layout esperado por projeto

Dentro de cada subdiretório de `paths.source_rep` (um "projeto"):

```
<projeto>/
├── copy_log_pending/     # arquivos aguardando processamento (entrada)
├── copy_log_success/     # arquivos processados com sucesso (saída)
├── copy_log_partial/     # arquivos com pelo menos uma linha em falha (saída)
└── copy_log_error/
    ├── retry_queue/      # itens aguardando nova tentativa
    └── dead_letter/      # itens que esgotaram as tentativas (intervenção manual)
```

## Dependências

Declaradas em [requirements.txt](requirements.txt):

- `pyodbc` — acesso ao SQL Server (requer driver ODBC instalado no sistema, ex.:
  *ODBC Driver 17 for SQL Server* / unixODBC no Linux).
- `pymysql` — acesso ao MySQL.
- `PyYAML` — leitura do `config.yml`.

> O módulo [file_ops.py](file_ops.py) usa `fcntl`, disponível apenas em sistemas
> Unix/Linux — o projeto não roda em Windows sem adaptação.

Instalação:

```bash
pip install -r requirements.txt
```

## Execução

```bash
python main.py
```

O script é feito para ser agendado periodicamente (ex.: via `cron`). O lock em
`paths.lock_file` garante que, se uma execução anterior ainda estiver em andamento
quando o `cron` disparar a próxima, a nova execução simplesmente registra um aviso e
encerra sem reprocessar nada.

## Logging

Configurado por [log_manager/log_config.py](log_manager/log_config.py) (`LogConfig`):

- Saída simultânea em `stdout` e em arquivo (`<log_dir>/log_read_file_<AAAA-MM-DD>.log`).
- Saída de `stdout` colorida por nível (DEBUG ciano, INFO verde, WARNING amarelo, ERROR
  vermelho, CRITICAL vermelho negrito) quando executado em um terminal interativo — a
  cor é desativada automaticamente quando a saída é redirecionada (ex.: `cron`, `>
  arquivo`), evitando códigos ANSI sujando redirecionamentos. O arquivo de log em disco
  nunca recebe códigos de cor, mesmo com `stdout` colorido.
- Rotação diária (`TimedRotatingFileHandler`), mantendo 5 arquivos de backup.
- Nível configurável via `logging.level` no `config.yml`.

## Criando ambiente para execução
Cole o repositorio dentro da pasta microservices

```bash
cd /etc/asterisk/ayty_dialplan/system/core/microservices/
cd recording_status_synchronizer/
python3 -m venv .venv --prompt "recording_status_synchronizer" 
source .venv/bin/activate
pip install -r requirements.txt
```


