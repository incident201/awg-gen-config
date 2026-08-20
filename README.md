# awg-gen-config

Интерактивный генератор и безопасный обновлятор серверного `awg0.conf` для AmneziaWG 3.1 в Docker.

Утилита предназначена для случая, когда Amnezia уже установлена и серверный конфиг существует. Она **не создаёт VPN с нуля** и не меняет ключи, адреса или список пиров. Вместо этого она полностью регенерирует набор параметров обфускации AWG и аккуратно встраивает его в существующий конфиг.

Текущая версия: **0.1.6**.

## Что делает

При обычном запуске `awg-gen-config`:

- читает текущий `awg0.conf` из Docker-контейнера;
- сохраняет `PrivateKey`, `Address`, `ListenPort` и любые посторонние параметры `[Interface]`;
- сохраняет существующую строку `MTU = ...` без изменений и не добавляет её, если в исходном конфиге её нет;
- сохраняет все `[Peer]` секции без изменений;
- удаляет старый набор AWG-параметров из `[Interface]`;
- генерирует новый полный набор параметров обфускации;
- `I1-I5` всегда генерирует заново и хранит в серверном конфиге как комментарии `# I1 = ...` ... `# I5 = ...`;
- создаёт host-side backup исходного конфига с правами `0600`;
- при наличии `awg-quick` делает preflight нового конфига;
- записывает новый конфиг в контейнер;
- перезапускает контейнер и проверяет появление интерфейса;
- при ошибке обновления/рестарта пытается автоматически откатить исходный конфиг;
- позволяет вручную восстановить один из сохранённых backup-файлов.

Утилита всегда регенерирует **весь набор обфускации целиком**. Частичного обновления `H*`, `S*`, `J*` или `I1-I5` нет намеренно.

## Требования

- Linux;
- Python 3.9+;
- Docker CLI;
- запущенный контейнер AmneziaWG;
- права на чтение/запись Docker-контейнера и каталога backup.

Сторонние Python-пакеты не нужны — используется только стандартная библиотека.

По умолчанию ожидается:

```text
container: amnezia-awg2
config:    /opt/amnezia/awg/awg0.conf
backups:   /var/backups/awg-gen-config
```

Все пути можно переопределить аргументами командной строки.

## Установка

```bash
chmod +x awg-gen-config
sudo install -m 0755 awg-gen-config /usr/local/bin/awg-gen-config
```

Проверка:

```bash
awg-gen-config --version
awg-gen-config --self-test
```

Ожидаемый результат:

```text
awg-gen-config 0.1.6
awg-gen-config self-test: OK
```

## Обычный режим

```bash
sudo awg-gen-config
```

Откроется меню:

```text
1. Generate AWG 3.1 parameters and update config
2. Restore a backup
3. Show current managed parameters
4. Exit
```

При выборе обновления скрипт последовательно спрашивает параметры генерации и перед записью показывает итоговый AWG-блок.

### Другой контейнер или путь

```bash
sudo awg-gen-config \
  --container amnezia-awg2 \
  --config /opt/amnezia/awg/awg0.conf \
  --backup-dir /root/awg-backups
```

## Экспорт в отдельный файл: `-o`

Если нужно получить новый полный конфиг, но **вообще не менять контейнер**:

```bash
sudo awg-gen-config -o /root/awg0-new.conf
```

В этом режиме скрипт:

1. читает текущий конфиг из контейнера только как исходный шаблон;
2. интерактивно генерирует новый полный набор AWG-параметров;
3. сохраняет `PrivateKey`, адреса, порт и все `[Peer]`;
4. записывает готовый полный конфиг в указанный локальный файл;
5. **не делает backup контейнерного конфига**;
6. **не записывает ничего в контейнер**;
7. **не выполняет `docker restart`**.

Выходной файл создаётся с правами `0600`, потому что содержит приватный ключ сервера и PresharedKey пиров.

## Dry-run

```bash
sudo awg-gen-config --dry-run
```

Скрипт проходит генерацию, показывает новый блок, но не записывает конфиг и не перезапускает контейнер.

`--dry-run` и `-o` одновременно не используются: `-o` уже является отдельным безопасным режимом вывода.

## Как обрабатываются I1-I5

В серверных конфигурациях официальной Amnezia `I1-I5` могут выглядеть так:

```ini
# I1 = <...>
# I2 = <...>
# I3 = <...>
# I4 = <...>
# I5 = <...>
```

Это не мусорные комментарии. Серверный интерфейс не должен применять их как активные CPS-параметры, но Amnezia хранит их в серверном конфиге для формирования клиентских конфигураций.

Поэтому `awg-gen-config` **всегда**:

- удаляет старые `# I1-I5`;
- генерирует новые `I1-I5` вместе со всем остальным набором;
- записывает новые значения снова как комментарии.

Например:

```ini
# I1 = <b 0x...><rc 22><t><r 44>
# I2 = <rd 8><b 0x...><rc 8><r 32><t>
# I3 = ...
# I4 = ...
# I5 = ...
```

Активных строк `I1 = ...` в серверный конфиг скрипт не добавляет.

## Какие параметры обновляются

Управляемый набор включает:

```text
Jc Jmin Jmax
S1 S2 S3 S4
H1 H2 H3 H4
I1 I2 I3 I4 I5
HeaderProtectionKey
ContentPaddingAddition
RekeyAfterTime
RekeyTimeout
RejectAfterTime
KeepaliveTimeout
MaxHandshakeAttempts
RandomTrailers
DisableCookies
```

Старые активные и закомментированные значения этого набора удаляются из `[Interface]` перед вставкой нового блока.

## AWG 3.1

Генератор учитывает параметры AWG 3.x и добавления 3.1:

```ini
RandomTrailers = on|off
DisableCookies = on|off
```

`RandomTrailers` по умолчанию предлагается включить.

Если включён `RandomTrailers`, `ContentPaddingAddition` по умолчанию предлагается оставить выключенным, потому что в transport-path AWG наличие `ContentPaddingAddition` имеет приоритет над механизмом random trailer.

`DisableCookies` по умолчанию выключен. Это отдельная настройка поведения cookie reply, а не обязательная часть генерации обфускации.

## HeaderProtectionKey и S1-S4

При включённом `HeaderProtectionKey` скрипт гарантирует:

```text
S1 >= 12
S2 >= 12
S3 >= 12
S4 >= 12
```

Также исключаются коллизии конечных размеров handshake-сообщений:

```text
S2 != S1 + 56
S3 != S1 + 84
S3 != S2 + 28
```

и соблюдается ограничение:

```text
S4 <= 32
```

## MTU: path MTU и CPS generation MTU

Скрипт различает две величины и не смешивает их с MTU серверного интерфейса.

### Path MTU

Это внешний MTU маршрута, по которому реально идут UDP-пакеты AWG. Он используется для ограничения внешних UDP junk-пакетов (`Jmax`), расчёта безопасных размеров transport-пакетов и связанных предупреждений.

Например при path MTU 1500 максимальный UDP payload без внешней фрагментации примерно равен:

```text
IPv4: 1500 - 20 - 8 = 1472
IPv6: 1500 - 40 - 8 = 1452
```

Поэтому `Jmax` ограничивается path MTU. Сам path MTU никогда не записывается в серверный конфиг как `MTU = ...`.

### CPS generation MTU

Это отдельный вход генератора, который используется только при построении CPS-пакетов `I1-I5` и расчёте допустимых размеров их padding. В интерактивном режиме он отображается как `Client/CPS MTU used for generation`.

Скрипт показывает консервативную границу, рассчитанную из path MTU, `S4` и transport overhead, и предупреждает, если выбранный CPS generation MTU её превышает. Это значение не записывается в `awg0.conf` как `MTU = ...`.

### MTU серверного интерфейса

Скрипт не управляет MTU серверного интерфейса. В официальном серверном конфиге Amnezia `/opt/amnezia/awg/awg0.conf` этой строки обычно нет: MTU в Amnezia является отдельной клиентской настройкой, а веб-генератор Architect использует MTU как вход для расчёта размеров CPS-пакетов. Эти сущности не следует смешивать.

Если `MTU = ...` уже есть в исходном `awg0.conf`, скрипт сохраняет строку как есть. Если строки нет, скрипт её не добавляет — это относится и к обычному режиму, и к экспорту через `-o`.

## Mimicry profiles

Доступны:

```text
QUIC Initial
QUIC 0-RTT
TLS 1.3 ClientHello
WireGuard Noise
DTLS
HTTP/3
SIP
TLS -> QUIC
QUIC Burst
DNS Query
Random
```

Генерация CPS основана на логике актуального Any-Tech-ARCHITECT, а не на старой сокращённой версии `scripts/awg-gen.sh`.

Поддерживаются browser packet-size fingerprints для профилей, где это применимо, и интерактивное управление CPS-тегами `<c>`, `<t>`, `<r>`, `<rc>`, `<rd>`.

## Backup и rollback

Перед обычным обновлением исходный серверный конфиг сохраняется на хосте.

По умолчанию:

```text
/var/backups/awg-gen-config/<container>/
```

Имя включает интерфейс, timestamp, тип backup и короткий SHA256 исходного файла.

Backup-файлы получают права `0600`.

Если каталог недоступен по правам, скрипт пытается использовать:

```text
~/.local/share/awg-gen-config/backups/<container>/
```

При ошибке записи или рестарта выполняется попытка автоматического rollback.

## Тесты

Встроенный smoke/self-test:

```bash
./awg-gen-config --self-test
```

Полный набор unit-тестов:

```bash
python3 -m unittest discover -s tests -v
```

Тесты не требуют Docker и проверяют в том числе:

- CLI `--version`, `--help`, `--self-test`;
- сохранение `PrivateKey`, `Address`, `ListenPort`;
- побайтово-логическое сохранение всех `[Peer]` секций;
- удаление старого набора обфускации;
- сохранение существующего `MTU = ...` и отсутствие добавления MTU в конфиг без такой строки;
- запись новых `I1-I5` только как комментариев;
- ограничения `S1-S4` для Header Protection;
- права `0600` на локальный export;
- отсутствие container write/restart/backup в `-o` режиме.

В `.github/workflows/tests.yml` есть GitHub Actions matrix для Python 3.9, 3.11 и 3.13.

## Структура репозитория

```text
.
├── awg-gen-config
├── README.md
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── tests.yml
└── tests/
    ├── test_awg_gen_config.py
    └── fixtures/
        └── awg0.conf
```

## Источники алгоритмов

При реализации использовались как технические ориентиры:

- Any-Tech-ARCHITECT / AmneziaWG Architect: https://github.com/Vadim-Khristenko/Any-Tech-ARCHITECT
- amneziawg-go: https://github.com/amnezia-vpn/amneziawg-go
- amneziawg-tools: https://github.com/amnezia-vpn/amneziawg-tools
- amneziawg-linux-kernel-module: https://github.com/amnezia-vpn/amneziawg-linux-kernel-module

Подробнее — в `THIRD_PARTY_NOTICES.md`.

## Безопасность

Конфиги и backup-файлы содержат секреты. Не коммить реальные `awg0.conf` в публичный репозиторий.

`.gitignore` специально игнорирует `*.conf`, кроме обезличенного тестового fixture в `tests/fixtures/`.

Перед первым применением на рабочем сервере рекомендуется:

```bash
./awg-gen-config --self-test
sudo ./awg-gen-config --dry-run
```

а уже затем обычный запуск.

## License

MIT. См. `LICENSE`.
