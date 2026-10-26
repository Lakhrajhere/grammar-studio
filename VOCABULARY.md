# Add your own vocabulary

The spelling dictionary lives in the Cloudflare D1 database `grammar-ai`.
Its four spelling tables have been created and verified. They are empty and
ready for your first word list; the existing grammar records are preserved.

## What to send

You can send a vocabulary file or a public word-list link in this conversation.
The assistant can extract the intended entries, run the importer, and verify the
uploaded counts using the existing Cloudflare login. This is an on-request
workflow, not a background service watching for new links or uploads.

Direct imports accept UTF-8 TXT, CSV, TSV, JSON, JSONL, and HTML word lists.
For PDFs, Word documents, scanned images, or ordinary prose pages, extract and
check the intended vocabulary first, then pass a structured list to the importer.
The importer does not treat every word in an arbitrary document as correct.

The simplest file is one accepted spelling per line:

```text
grammar
student
spelling
```

To also teach known mistakes, use the header-only `templates/vocabulary.csv`:

```csv
word,misspellings
grammar,grammer;gramar
student,studnet
spelling,speling
```

The `word` column contains the accepted spelling. Optional mistakes go in
`misspellings`, separated by semicolons. JSON accepts objects such as:

```json
{"word":"grammar","misspellings":["grammer","gramar"]}
```

Words can include internal apostrophes and hyphens. Add inflected forms such as
`student` and `students` separately. Multiword phrases, numbers, and sentences
are skipped rather than silently split into dictionary entries. Supply only
spellings you want accepted; adding a misspelled word to the correct-word column
would make the checker accept it.

## Storage

- `spelling_words`: accepted spellings, normalized lookup keys, language, variety,
  and active/candidate/rejected status.
- `spelling_mistakes`: known incorrect-to-correct mappings, with source references.
- `spelling_sources`: source filename or URL and a content hash for each import.
- `spelling_word_sources`: links a word to every source that supplied it.

Imports normalize Unicode and case for duplicate lookup, preserve a display
spelling, and skip existing entries. They add provenance without overwriting
existing words or review decisions. The earlier `grammar_vocabulary` table holds
the five richer sample entries and remains separate from this spelling lexicon.

## Run the importer

Preview a file without uploading:

```sh
python3 scripts/import_vocabulary.py --file /path/to/words.csv
```

Upload the validated entries and verify their source links:

```sh
python3 scripts/import_vocabulary.py --file /path/to/words.csv --upload
```

Use `--url` instead of `--file` for a public link. Public HTML imports look for
an explicit word column in a table or one-word list items; navigation and prose
are not harvested. Use `--format` when a download URL hides its file format.
Inaccessible or authenticated links need another extraction route.

Use `--candidate` for uncertain entries; they are stored but excluded from
spelling checks. Correct-word imports are active by default. Repeating an import
does not create duplicate words. Imported SQL is temporary and removed after use;
the dictionary is stored in D1 rather than a local database. Node.js and the
existing Wrangler login are required only for cloud operations. Parsing and
previewing use the Python standard library.

## Check spelling after importing vocabulary

```sh
python3 scripts/check_spelling.py --text "This has a speling mistake."
```

The checker returns unknown words, positions, and suggestions. Known mistake
mappings take priority over edit-distance suggestions. Accepted words stay
unchanged. A word missing from an incomplete dictionary is not necessarily
misspelled. This first checker ignores capitalization differences and cannot
detect a correctly spelled word used in the wrong context, such as `their`
instead of `there`.

These components implement dictionary-based checking with your data. They do
not train a neural network or make the stored grammar lessons executable.

## Schema

`schema/vocabulary.sql` adds the spelling tables without changing existing
grammar data. It is safe to run again. New spelling imports expect these tables
to exist before uploading.
