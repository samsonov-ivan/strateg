"""Регрессии продолжения S3, чтения архивов и ссылок в отчёте."""
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path

from strateg import hooks
from strateg.lib import paths
from tests.conftest import FIX, QUOTE, advance


def test_resume_s3_distinguishes_templates_review_and_g4(cli, sample_source, root, project):
    advance(cli, 'S3')
    assert cli('claim', 'add', '--type', 'fact', '--text', 'Удержание', '--source', sample_source, '--quote', QUOTE)[0] == 0
    assert cli('claim', 'add', '--type', 'forecast', '--text', 'Прогноз удержания', '--depends', 'C-001')[0] == 0
    assert cli('impact', '--changed', 'C-001', '--apply')[0] == 0
    required = paths.load_config('required_sections')['docs']
    docs = root / 'projects' / project / 'docs'
    assert 'onepager.md' in cli('project', 'status')[1]['data']['next_step']
    for name, spec in required.items():
        body = '\n'.join(f'## {h}\nДанные [C-001].' for h in spec['headings'])
        if name == 'strategy_comms.md':
            body = body.replace('## Обещания и подтверждения\nДанные [C-001].',
                                '## Обещания и подтверждения\n| Обещание | Свойство продукта | Подтверждение |\n'
                                '|---|---|---|\n| Тест | Функция | [C-001] |')
        dest = docs.parent if name == 'brief.md' else docs
        (dest / name).write_text(body, encoding='utf-8')
    file = docs / 'onepager.md'
    complete = file.read_text(encoding='utf-8')
    file.write_text(complete.replace('## Риски\nДанные [C-001].', '## Риски\n<!-- ещё не заполнено -->'), encoding='utf-8')
    step = cli('project', 'status')[1]['data']['next_step']
    assert 'onepager.md' in step and 'strategy_product.md' not in step
    file.write_text(complete, encoding='utf-8')
    blocked = cli('project', 'status')[1]['data']['next_step']
    assert 'V06' in blocked and 'Представить готовые' not in blocked
    for kind in ('status_quo', 'close', 'change'):
        code, option = cli('option', 'add', '--title', kind, '--kind', kind, '--summary', kind)
        assert code == 0
        assert cli('objection', 'add', '--option', option['data']['id'], '--text', 'Риск', '--strength', 'strong',
                   '--by', 'red_team')[0] == 0
    assert cli('validate', '--stage', 'S3')[0] == 0
    step = cli('project', 'status')[1]['data']['next_step']
    assert 'G4' in step and 'Прогнозов к пересмотру: 1' in step and 'Написать' not in step
    assert step in hooks.session_start({'source': 'resume', 'session_id': 'resume-test'})[1]
    cli('project', 'gate', 'G4', '--status', 'changes', '--note', 'Уточнить лимит')
    assert 'Уточнить лимит' in cli('project', 'status')[1]['data']['next_step']
    cli('project', 'gate', 'G4', '--status', 'approved', '--note', 'Принято')
    assert 'S4' in cli('project', 'status')[1]['data']['next_step']
    cli('claim', 'add', '--type', 'fact', '--text', 'Без подтверждения', '--source', sample_source,
        '--quote', 'В источнике нет этого фрагмента')
    blocked = cli('project', 'status')[1]['data']['next_step']
    assert 'V03' in blocked and 'C-003' in blocked and 'Перейти к S4' not in blocked


def test_archive_secret_check_scans_local_sources_without_git(cli, tmp_path, monkeypatch):
    archive = tmp_path / 'unpacked' / 'strateg'
    shutil.copytree(paths.code_dir() / 'config', archive / 'config')
    shutil.copy(FIX / 'secrets' / 'leak.txt', archive / '.env')
    for ignored in ('.venv/lib', 'tests/fixtures/keys', 'nested/__pycache__'):
        target = archive / ignored
        target.mkdir(parents=True)
        shutil.copy(FIX / 'secrets' / 'leak.txt', target / 'example.txt')
    monkeypatch.setattr(paths, 'code_dir', lambda: archive)
    code, response = cli('guard', 'secrets')
    assert code == 1 and {f['file'] for f in response['data']['findings']} == {'.env'}
    assert response['data']['scope'] == 'archive' and response['data']['files_scanned'] > 0
    assert (archive / '.env').read_text().strip() not in json.dumps(response)
    (archive / '.env').unlink()
    assert cli('guard', 'secrets')[0] == 0
    assert cli('guard', 'secrets', '--history')[0] != 0


def test_doctor_flags_incomplete_scan(cli, monkeypatch):
    from strateg.cmd import guard
    from strateg.lib.out import CliError

    def unavailable(*args):
        raise CliError('IO_ERROR', 'Недоступен файл')

    monkeypatch.setattr(guard, 'cli_secrets', unavailable)
    result = cli('doctor')[1]['data']['checks']
    check = next(row for row in result if 'секрет' in row['check'].lower())
    assert check['status'] != 'ok' and 'не проверено' in check['message']


def test_report_resolves_references_to_commitments(cli, root, project):
    assert cli('option', 'add', '--title', 'Тест', '--kind', 'change', '--summary', 'Тест')[0] == 0
    assert cli('decision', 'add', '--option', 'O-001', '--rationale', 'Проверка', '--owner', 'РП', '--by', 'РП',
               '--metric', 'M1|0.5|0.6|2026-12-31', '--trigger', 'date:2026-12-01')[0] == 0
    assert cli('commitment', 'add', '--decision', 'D-001', '--what', 'Сверить данные', '--owner', 'РП', '--due', '2026-12-01')[0] == 0
    (root / 'projects' / project / 'docs' / 'onepager.md').write_text('## Что дальше\nСверить [K-001].', encoding='utf-8')
    code, response = cli('report')
    assert code == 0
    anchors, hrefs = set(), set()

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attr = dict(attrs)
            if 'id' in attr:
                anchors.add(attr['id'])
            if attr.get('href', '').startswith('#'):
                hrefs.add(attr['href'][1:])

    Links().feed(Path(response['data']['path']).read_text(encoding='utf-8'))
    assert 'K-001' in hrefs and hrefs <= anchors


def test_report_shows_review_alongside_recorded_option_and_decision(cli, sample_source):
    assert cli('claim', 'add', '--type', 'fact', '--text', 'Удержание', '--source', sample_source, '--quote', QUOTE)[0] == 0
    assert cli('option', 'add', '--title', 'Сравнение', '--summary', 'Исходный вариант', '--kind', 'change',
               '--based-on', 'C-001')[0] == 0
    assert cli('decision', 'add', '--option', 'O-001', '--rationale', 'Исходное основание', '--owner', 'РП',
               '--by', 'РП', '--metric', 'M1|0.5|0.6|2026-12-31', '--trigger', 'date:2026-12-01')[0] == 0
    path = Path(cli('report')[1]['data']['path'])
    assert 'требуется пересмотр' not in path.read_text(encoding='utf-8')
    assert cli('impact', '--changed', 'C-001', '--apply', '--reason', 'Уточнён KPI')[0] == 0
    assert cli('report')[0] == 0
    rendered = path.read_text(encoding='utf-8')
    for rid, status, historical in (('O-001', 'выбран', 'Исходный вариант'), ('D-001', 'active', 'Исходное основание')):
        block = rendered.split(f"<details id='{rid}'", 1)[1].split('</details>', 1)[0]
        summary = block.split('</summary>')[0]
        assert status in summary and 'требуется пересмотр' in summary
        assert 'Уточнён KPI' in block and historical in block
