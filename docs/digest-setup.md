# Запуск, секреты и расходы

## Секреты GitHub

Репозиторий **публичный**. В GitHub: Settings → Environments → создать/открыть
`vericomedia-digest` → Environment secrets. Добавить:

| Имя | Что хранить |
| --- | --- |
| TILDA_MCP_TOKEN | Ключ Tilda MCP без Bearer, минимальные права к проекту 14191605 |
| VERICO_LLM_API_KEY | Отдельный ключ оплаченного OpenAI API project |
| VERICO_ARTIFACT_KEY | base64 от 32 случайных байт для AES-256-GCM |

Подписка ChatGPT/Codex не оплачивает API. Сетевой секрет Codex работает только в
Codex proxy и не переносится автоматически в Actions. Его placeholder нельзя
скопировать в GitHub вместо настоящего ключа. Вносить значение прямо в GitHub UI
или с доверенного компьютера через gh secret set, не в переписку.

Пример создания ключа шифрования и передачи без печати в терминал:

```sh
python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())' | gh secret set VERICO_ARTIFACT_KEY --env vericomedia-digest --repo verico26/vericomedia-publisher
```

Сохраните защищённую резервную копию этого ключа своим менеджером секретов, если
архивы нужно расшифровывать позже. Secret из GitHub прочитать назад нельзя.
Environment reviewers подходят для подготовки; каждый запуск с обязательным
reviewer не будет полностью автономным. Live-политику согласовать отдельно.
GitHub metadata/state использует встроенный GITHUB_TOKEN. Сейчас contents:read;
для будущего live CAS-журнала после отдельного разрешения потребуется contents:write.

## Защита артефактов

Фиксированный allowlist архивирует research.json, draft.md, edited.md, article.html,
publication-report.json, factcheck.json и QA-скриншоты. `.env`, cookies, state,
HTTP headers, сетевые credentials туда не входят. Перед upload применяется
AES-256-GCM с уникальным nonce и authenticated header. В GitHub upload попадает
**только digest.enc**, retention 14 дней. На публичном repo ciphertext может быть
скачан посторонними, но plaintext/key не публикуются.

Fixture без секрета шифрования использует одноразовый ключ, проверяет decrypt
локально и уничтожает ключ с runner. Такой архив лишь тестовый, его нельзя
расшифровать потом. Для настоящего dry-run/preflight отсутствие постоянного
VERICO_ARTIFACT_KEY останавливает workflow до приватных/платных операций.

Для расшифровки скачанного файла на доверенном компьютере установите dependencies,
передайте ключ через защищённое окружение, затем:

```sh
PYTHONPATH=src python -m vericomedia_publisher.digest.artifacts decrypt digest.enc /tmp/verico-digest.zip
```

Значение ключа не указывайте в command line или переписке. Расшифрованный архив
считайте приватным материалом и не добавляйте в git.

## Модель и стоимость

Выбрана **gpt-5.6-terra**, вызов HTTPS `POST https://api.openai.com/v1/responses`.
По прочитанной 28.10.2026 официальной документации: **$2 / 1M input tokens**,
**$12 / 1M output tokens**, Web search **$10 / 1000 вызовов** плюс input tokens
содержимого поиска. Модель/ставки заданы явно в config/digest.json.

Источники: https://developers.openai.com/api/docs/models/gpt-5.6-terra,
https://developers.openai.com/api/docs/pricing.

Пример: 50 000 input + 15 000 output + 5 search ≈ **$0.33 за выпуск**. Реальная
стоимость зависит от источников, длины статьи и search context; это не гарантия
или жёсткий денежный лимит. Ограничены четыре model-запроса, до пяти search calls
и 9000 output tokens на запрос. Тарифы могут измениться. Реальные calls пока не
выполнялись. Actual usage и расчёт оценки сохраняются в защищённом отчёте.
Настройте бюджет/лимиты в API project; отдельно возможны расходы GitHub Actions
и хранения artifacts по тарифу аккаунта. Платный внешний CMS/БД не требуется.

## Локальная проверка

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-digest.txt
.venv/bin/python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m vericomedia_publisher.digest.pipeline --mode fixture --output /tmp/verico-fixture
.venv/bin/python -m vericomedia_publisher.digest.pipeline --mode preflight --output /tmp/verico-mcp-preflight
```

Для текущей облачной машины проверен system Chromium:
`BROWSER_EXECUTABLE=/usr/bin/chromium`. Путь включать только при наличии браузера;
runner использует matching Chromium из playwright install.

Режимы: fixture — синтетика без внешних вызовов; preflight — реальное MCP-чтение;
dry-run — реальные платные research/writer/editor/factcheck + QA без записи;
publish — закрыт четырьмя deployment-gates. Директория результата должна быть
пустой/новой, чтобы не смешивать отчёты разных запусков.

## Проверка Actions

Код должен быть отправлен в GitHub. Для ветки codex/vericomedia-digest push
автоматически запускает fixture. Это не запускает реальные новости или публикацию.
После добавления workflow в default branch ручной запуск находится в Actions →
VericoMedia digest → Run workflow; выбрать fixture, затем preflight, затем dry-run.
Подтвердить, что именно GitHub runner получил проект 14191605; Codex preflight
не заменяет этот тест. Секреты вводит владелец напрямую в защищённых настройках.

До первого live нужны отдельные принятые тесты и разрешение пользователя.
Нельзя просто сменить режим, игнорируя false в config/digest.json. Новая статья
создаётся только в /news/, existing pages не редактируются. Бейджик остаётся
ручным шагом 9–10 ноября; не подставлять случайное изображение ради проверки.
