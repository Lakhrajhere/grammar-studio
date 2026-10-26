import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from check_spelling import check_text, edit_distance
from cloudflare_d1 import parse_results
from import_vocabulary import canonical_word, make_import, parse_content, prepare_records


def source(content=b'fixture', locator='words.csv'):
    return {'content': content, 'locator': locator, 'source_type': 'file', 'input_format': 'csv'}


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript((ROOT / 'schema/vocabulary.sql').read_text())

    def tearDown(self):
        self.db.close()

    def import_records(self, records, **kwargs):
        entries, skipped = prepare_records(records)
        self.assertFalse(skipped)
        source_id, sql = make_import(source(**kwargs), entries)
        self.db.executescript(sql)
        return source_id, sql

    def test_unicode_and_case_normalization(self):
        self.assertEqual(canonical_word('  Ｃａｆé  '), ('Café', 'café'))
        self.assertEqual(canonical_word('Don’t'), ("Don't", "don't"))

    def test_rejects_prose_and_sql_as_words(self):
        words, skipped = prepare_records(['grammar', 'a full sentence', "word'); DROP TABLE spelling_words;--"])
        self.assertEqual([word['word'] for word in words], ['grammar'])
        self.assertEqual(len(skipped), 2)

    def test_invalid_typo_does_not_partially_add_entry(self):
        words, skipped = prepare_records([{'word': 'grammar', 'misspellings': ['bad phrase']}])
        self.assertEqual(words, [])
        self.assertEqual(len(skipped), 1)

    def test_csv_and_duplicates_merge_mistakes(self):
        content = b'word,misspellings\ngrammar,grammer;gramar\nGrammar,grammer\n'
        words, skipped = prepare_records(parse_content(content, 'csv'))
        self.assertFalse(skipped)
        self.assertEqual(len(words), 1)
        self.assertEqual(set(words[0]['misspellings']), {'grammer', 'gramar'})

    def test_json_strings_objects_and_jsonl(self):
        records = parse_content(b'{"words":["student",{"word":"grammar","misspellings":["grammer"]}]}', 'json')
        words, skipped = prepare_records(records)
        self.assertEqual(len(words), 2)
        self.assertFalse(skipped)
        self.assertEqual(parse_content(b'"student"\n{"word":"grammar"}\n', 'jsonl'), ['student', {'word': 'grammar'}])

    def test_text_lists_not_paragraphs(self):
        words, skipped = prepare_records(parse_content(b'# Vocabulary\n1. grammar\n- student\nThis is ordinary prose.\n', 'txt'))
        self.assertEqual([word['word'] for word in words], ['grammar', 'student'])
        self.assertEqual(len(skipped), 1)

    def test_binary_documents_request_extraction_before_decoding(self):
        with self.assertRaisesRegex(ValueError, 'Extract PDF/Word documents first'):
            parse_content(b'%PDF\xff\x00', 'pdf')

    def test_schema_can_be_applied_again(self):
        self.import_records(['grammar'])
        self.db.executescript((ROOT / 'schema/vocabulary.sql').read_text())
        self.assertEqual(self.db.execute('SELECT count(*) FROM spelling_words').fetchone()[0], 1)

    def test_html_table_ignores_navigation_and_unrelated_tables(self):
        html = b'<nav><li>Home</li></nav><table><tr><th>Word</th><th>Meaning</th></tr><tr><td>grammar</td><td>Rules</td></tr></table><table><tr><th>Menu</th></tr><tr><td>Contact</td></tr></table>'
        words, skipped = prepare_records(parse_content(html, 'html'))
        self.assertFalse(skipped)
        self.assertEqual([word['word'] for word in words], ['grammar'])

    def test_idempotent_import_and_foreign_keys(self):
        _, sql = self.import_records([{'word': 'grammar', 'misspellings': ['grammer']}])
        self.db.executescript(sql)
        for table in ['spelling_words', 'spelling_sources', 'spelling_word_sources', 'spelling_mistakes']:
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 1)
        self.assertEqual(list(self.db.execute('PRAGMA foreign_key_check')), [])
        self.assertEqual(self.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_two_sources_one_dictionary_word(self):
        self.import_records(['grammar'], locator='first.txt')
        self.import_records(['Grammar'], locator='second.txt')
        self.assertEqual(self.db.execute('SELECT count(*) FROM spelling_words').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM spelling_word_sources').fetchone()[0], 2)

    def test_source_label_cannot_execute_sql(self):
        self.import_records(['grammar'], locator="words'); DROP TABLE spelling_words;--.csv")
        self.assertEqual(self.db.execute('SELECT count(*) FROM spelling_words').fetchone()[0], 1)
        self.assertIn('DROP TABLE', self.db.execute('SELECT locator FROM spelling_sources').fetchone()[0])

    def test_existing_manual_id_and_review_decision_preserved(self):
        self.db.execute("INSERT INTO spelling_words (id,word,normalized_word,language_code,variety,status) VALUES ('manual','grammar','grammar','en','general','rejected')")
        self.import_records([{'word': 'grammar', 'misspellings': ['grammer']}])
        self.assertEqual(self.db.execute('SELECT id,status FROM spelling_words').fetchone(), ('manual', 'rejected'))
        self.assertEqual(self.db.execute('SELECT correct_word_id FROM spelling_mistakes').fetchone()[0], 'manual')

    def test_varieties_kept_separate(self):
        entries, _ = prepare_records(['colour'])
        for variety in ['british', 'indian']:
            _, sql = make_import(source(), entries, variety=variety)
            self.db.executescript(sql)
        self.assertEqual(self.db.execute('SELECT count(*) FROM spelling_words').fetchone()[0], 2)

    def test_mistake_not_inserted_as_correct_word(self):
        self.import_records([{'word': 'grammar', 'misspellings': ['grammer']}])
        self.assertEqual(self.db.execute('SELECT normalized_word FROM spelling_words').fetchall(), [('grammar',)])

    def test_suggestions_offsets_and_correct_words(self):
        words = [{'word': word, 'normalized_word': word} for word in ['grammar', 'student']]
        issues = check_text('GRAMMAR studnet grammer', words, [{'normalized_misspelling': 'grammer', 'word': 'grammar'}])
        self.assertEqual([issue['word'] for issue in issues], ['studnet', 'grammer'])
        self.assertEqual(issues[0]['start'], 8)
        self.assertEqual(issues[0]['suggestions'][0], 'student')
        self.assertEqual(issues[1]['suggestions'], ['grammar'])

    def test_known_word_not_flagged_by_conflicting_typo_mapping(self):
        self.assertEqual(check_text('form', [{'word': 'form', 'normalized_word': 'form'}], [{'normalized_misspelling': 'form', 'word': 'from'}]), [])

    def test_empty_dictionary_and_transpositions(self):
        with self.assertRaisesRegex(ValueError, 'dictionary is empty'):
            check_text('anything', [], [])
        self.assertEqual(edit_distance('studnet', 'student'), 1)
        self.assertEqual(edit_distance('speling', 'spelling'), 1)

    def test_wrangle_progress_and_failed_responses(self):
        result = [{'results': [{'linked_words': 1}], 'success': True}]
        self.assertEqual(parse_results('Upload complete.\n' + json.dumps(result)), result)
        with self.assertRaises(RuntimeError):
            parse_results('[{"success":false}]')


if __name__ == '__main__':
    unittest.main()
