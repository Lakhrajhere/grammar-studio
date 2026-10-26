"""Read explicit word lists, validate spellings, and optionally import into D1.

Default operation previews in memory. --upload uses the existing Cloudflare login.
General prose is not split into allegedly correct dictionary words.
"""

import argparse
import csv
import hashlib
import io
import json
import re
import tempfile
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

from cloudflare_d1 import execute, query


ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 50 * 1024 * 1024
WORD_FIELDS = ('word', 'correct_spelling', 'correct', 'spelling', 'headword')
TYPO_FIELDS = ('misspellings', 'misspelling', 'incorrect', 'wrong', 'typo')


def canonical_word(value):
    if not isinstance(value, str):
        raise ValueError('A spelling must be text.')
    word = unicodedata.normalize('NFKC', value).strip()
    word = word.translate(str.maketrans({'’': "'", '‘': "'", '‐': '-', '‑': '-'}))
    if not word or len(word) > 100 or not word[0].isalpha() or not word[-1].isalpha():
        raise ValueError('Expected one word, optionally containing internal apostrophes or hyphens.')
    if any(not (character.isalpha() or unicodedata.category(character).startswith('M') or character in "'-") for character in word):
        raise ValueError('Expected one word, not a sentence, number, or instruction.')
    if re.search(r"['-]{2}", word):
        raise ValueError('Invalid punctuation inside a word.')
    return word, word.casefold()


def field_name(value):
    return re.sub(r'\s+', '_', str(value).strip().casefold())


def read_record(record):
    if isinstance(record, str):
        return record, []
    if not isinstance(record, dict):
        raise ValueError('Expected a word or a vocabulary object.')
    record = {field_name(key): value for key, value in record.items() if key is not None}
    word = next((record[key] for key in WORD_FIELDS if record.get(key)), None)
    if word is None:
        raise ValueError('Missing word or correct_spelling field.')
    mistakes = []
    for field in TYPO_FIELDS:
        value = record.get(field)
        if not value:
            continue
        if isinstance(value, str):
            mistakes.extend(part.strip() for part in value.split(';') if part.strip())
        elif isinstance(value, list):
            mistakes.extend(value)
        else:
            raise ValueError('Misspellings must be text separated by semicolons or a JSON list.')
    return word, mistakes


class WordListHTML(HTMLParser):
    """Extract explicit word-column tables or list items outside navigation."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.suppressed = []
        self.rows, self.items = [], []
        self.table_id = 0
        self.row = None
        self.cell = None
        self.item = None

    def handle_starttag(self, tag, attributes):
        if tag in {'script', 'style', 'nav', 'header', 'footer', 'aside'}:
            self.suppressed.append(tag)
        if self.suppressed:
            return
        if tag == 'table':
            self.table_id += 1
        elif tag == 'tr':
            self.row = []
        elif tag in {'td', 'th'} and self.row is not None:
            self.cell = []
        elif tag == 'li':
            self.item = []

    def handle_data(self, data):
        if self.suppressed:
            return
        if self.cell is not None:
            self.cell.append(data)
        if self.item is not None:
            self.item.append(data)

    def handle_endtag(self, tag):
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
            return
        if tag in {'td', 'th'} and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append((self.table_id, self.row))
            self.row = None
        elif tag == 'li' and self.item is not None:
            self.items.append(''.join(self.item).strip())
            self.item = None

    def records(self):
        headers = None
        records = []
        previous_table = None
        for table_id, row in self.rows:
            if table_id != previous_table:
                headers = None
                previous_table = table_id
            names = [field_name(cell) for cell in row]
            if any(name in WORD_FIELDS for name in names):
                headers = names
                continue
            if headers:
                records.append(dict(zip(headers, row)))
        return records if records else self.items


def parse_content(content, input_format):
    if input_format not in {'csv', 'tsv', 'json', 'jsonl', 'html', 'txt'}:
        raise ValueError('Supported direct imports: TXT, CSV, TSV, JSON, JSONL, and HTML word lists. Extract PDF/Word documents first.')
    text = content.decode('utf-8-sig')
    if input_format in {'csv', 'tsv'}:
        reader = csv.DictReader(io.StringIO(text), delimiter='\t' if input_format == 'tsv' else ',')
        if not reader.fieldnames or not any(field_name(name) in WORD_FIELDS for name in reader.fieldnames):
            raise ValueError('CSV/TSV must have a word or correct_spelling column.')
        return list(reader)
    if input_format == 'json':
        value = json.loads(text)
        if isinstance(value, dict):
            value = next((value[key] for key in ('words', 'vocabulary', 'entries') if key in value), value)
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            raise ValueError('JSON must contain a list of words or vocabulary objects.')
        return value
    if input_format == 'jsonl':
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if input_format == 'html':
        parser = WordListHTML()
        parser.feed(text)
        return parser.records()
    if input_format == 'txt':
        return [re.sub(r'^\s*(?:[-*•]\s+|\d+[.)]\s+)', '', line).strip()
                for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def load_source(*, file=None, url=None, input_format=None):
    if file is not None:
        path = Path(file).expanduser().resolve()
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('The input exceeds the 50 MiB limit.')
        content, locator, source_type = path.read_bytes(), path.name, 'file'
        detected = path.suffix.lstrip('.').lower()
    else:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in {'http', 'https'} or not parts.netloc or parts.username or parts.password:
            raise ValueError('Use a public HTTP/HTTPS word-list link without embedded credentials.')
        request = urllib.request.Request(url, headers={'User-Agent': 'GrammarVocabularyImporter/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            if int(response.headers.get('Content-Length', '0')) > MAX_BYTES:
                raise ValueError('The linked input exceeds the 50 MiB limit.')
            content = response.read(MAX_BYTES + 1)
            mime = response.headers.get_content_type()
            detected = Path(urllib.parse.urlsplit(response.geturl()).path).suffix.lstrip('.').lower()
            if not detected:
                detected = {'application/json': 'json', 'text/csv': 'csv', 'text/plain': 'txt'}.get(mime, 'html')
        if len(content) > MAX_BYTES:
            raise ValueError('The linked input exceeds the 50 MiB limit.')
        locator, source_type = url, 'url'
    detected = {'htm': 'html', 'text': 'txt'}.get(detected, detected)
    return {'content': content, 'locator': locator, 'source_type': source_type,
            'input_format': input_format or detected}


def prepare_records(records):
    words, skipped = {}, []
    for position, record in enumerate(records, 1):
        try:
            raw, mistakes = read_record(record)
            word, key = canonical_word(raw)
            checked_mistakes = {}
            for raw_mistake in mistakes:
                mistake, mistake_key = canonical_word(raw_mistake)
                if mistake_key == key:
                    raise ValueError('A misspelling is identical to the correct spelling.')
                checked_mistakes[mistake_key] = mistake
            entry = words.setdefault(key, {'word': word, 'normalized_word': key, 'misspellings': {}})
            entry['misspellings'].update(checked_mistakes)
        except ValueError as error:
            skipped.append({'record': position, 'reason': str(error)})
    return list(words.values()), skipped


def quote(value):
    value = str(value)
    if '\x00' in value:
        raise ValueError('NUL characters are not accepted.')
    return "'" + value.replace("'", "''") + "'"


def identifier(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def make_import(source, words, language='en', variety='general', status='active'):
    if status not in {'active', 'candidate'}:
        raise ValueError('New imports must be active or candidate.')
    content_hash = hashlib.sha256(source['content']).hexdigest()
    source_id = identifier(source['source_type'], source['locator'], content_hash, language, variety)
    source_values = [source_id, source['source_type'], source['locator'], content_hash, source['input_format'], language, variety]
    statements = ['INSERT INTO spelling_sources (id, source_type, locator, content_sha256, input_format, language_code, variety) VALUES (' + ','.join(map(quote, source_values)) + ') ON CONFLICT(id) DO NOTHING;']
    for entry in words:
        key = entry['normalized_word']
        word_id = identifier(language, variety, key)
        values = [word_id, entry['word'], key, language, variety, status]
        statements.append('INSERT INTO spelling_words (id,word,normalized_word,language_code,variety,status) VALUES (' + ','.join(map(quote, values)) + ') ON CONFLICT(language_code,variety,normalized_word) DO NOTHING;')
        lookup = f'normalized_word={quote(key)} AND language_code={quote(language)} AND variety={quote(variety)}'
        statements.append(f'INSERT INTO spelling_word_sources (word_id,source_id) SELECT id,{quote(source_id)} FROM spelling_words WHERE {lookup} ON CONFLICT(word_id,source_id) DO NOTHING;')
        for mistake_key, mistake in entry['misspellings'].items():
            mistake_id = identifier(source_id, language, variety, key, mistake_key)
            statements.append(f'INSERT INTO spelling_mistakes (id,misspelling,normalized_misspelling,correct_word_id,source_id) SELECT {quote(mistake_id)},{quote(mistake)},{quote(mistake_key)},id,{quote(source_id)} FROM spelling_words WHERE {lookup} ON CONFLICT(normalized_misspelling,correct_word_id,source_id) DO NOTHING;')
    return source_id, '\n'.join(statements) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--file', type=Path)
    inputs.add_argument('--url')
    parser.add_argument('--format', choices=['txt', 'csv', 'tsv', 'json', 'jsonl', 'html'])
    parser.add_argument('--language', default='en')
    parser.add_argument('--variety', default='general')
    parser.add_argument('--database', default='grammar-ai')
    parser.add_argument('--candidate', action='store_true', help='Store uncertain entries without using them for spelling checks.')
    parser.add_argument('--upload', action='store_true', help='Import the valid entries into the hosted D1 database.')
    args = parser.parse_args()
    source = load_source(file=args.file, url=args.url, input_format=args.format)
    words, skipped = prepare_records(parse_content(source['content'], source['input_format']))
    if not words:
        raise SystemExit('No valid vocabulary entries found. Use one word per line or a word column.')
    source_id, sql = make_import(source, words, args.language, args.variety, 'candidate' if args.candidate else 'active')
    summary = {'source': source['locator'], 'source_id': source_id,
               'unique_words_in_input': len(words),
               'misspelling_mappings_in_input': sum(len(word['misspellings']) for word in words),
               'skipped_records': skipped, 'uploaded': False,
               'sample_words': [word['word'] for word in words[:10]]}
    if args.upload:
        with tempfile.TemporaryDirectory(prefix='grammar-vocabulary-') as temporary:
            path = Path(temporary) / 'import.sql'
            path.write_text(sql, encoding='utf-8')
            execute(args.database, sql_file=path)
        verification = query(args.database,
            'SELECT (SELECT COUNT(*) FROM spelling_word_sources WHERE source_id=' + quote(source_id) +
            ') AS linked_words, (SELECT COUNT(*) FROM spelling_mistakes WHERE source_id=' + quote(source_id) + ') AS mistake_mappings;')
        expected_mistakes = sum(len(word['misspellings']) for word in words)
        if verification[0]['linked_words'] != len(words) or verification[0]['mistake_mappings'] != expected_mistakes:
            raise RuntimeError('The uploaded source word count did not match the prepared input.')
        summary.update(uploaded=True, verified_linked_words=verification[0]['linked_words'],
                       verified_mistake_mappings=verification[0]['mistake_mappings'])
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
