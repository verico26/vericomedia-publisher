# VericoMedia Publisher

Автономная цепочка новостного дайджеста на Python: research → draft → отдельная
редактура → фактчек → HTML шаблона `/template-stati-v2` → Chromium QA → MCP Tilda.
**Реальная автоматическая публикация выключена.**

- Проект Tilda: `14191605`, vericomedia.ru. Шаблон: страница `326050509`.
- Плановые даты: **1 и 8 ноября 2026, 03:00 UTC / 10:00 Новосибирск**.
- Один workflow цепочки: `.github/workflows/publication-plan.yml`; schedule пока dry-run.
- В публичный GitHub загружается только зашифрованный редакционный архив.
- Голос взят из существующего дайджеста, дизайн — из v2, не из нового макета.

[Архитектура и ограничения](docs/digest-architecture.md) ·
[Секреты, расходы и запуск](docs/digest-setup.md) ·
[Подтверждённый ранний MCP-тест](docs/tilda-mcp-publication-test.md)

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-digest.txt
.venv/bin/python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m vericomedia_publisher.digest.pipeline --mode fixture --output /tmp/verico-fixture
```

Синтетический прогон проверяет передачу файлов и вёрстку, **не** реальные новости
или работу LLM API. Для реального dry-run нужен отдельный оплаченный API key;
для автономного MCP нужен секрет в GitHub, а не только сетевой секрет Codex.
Без проверки GitHub runner, настоящего текста и badge система не считается готовой.

Ранняя offline-команда `vericomedia_publisher` и browser-прототип сохранены для
регрессий; они не публикуют. Исторические документы аудита описывают этапы
исследования и не заменяют текущий статус внедрения.
