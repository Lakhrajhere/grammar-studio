# Grammar AI project

Source code: https://github.com/Lakhrajhere/grammar-studio (private).

The source data has been imported into Cloudflare D1:

- Database: `grammar-ai`
- Database ID: `e12bdeae-1269-4c70-ab68-bf1abea55e85`
- Uploaded records: 96 grammar lessons, 479 example pairs, five illustrative
  vocabulary entries, and one source-document reference.
- Examples still require linguistic review before training.

## Vocabulary and spelling

The vocabulary workflow is documented in [VOCABULARY.md](VOCABULARY.md).
`schema/vocabulary.sql` adds accepted-word, misspelling, and source tables.
Use `scripts/import_vocabulary.py` for explicit word lists and public word-list
links, and `scripts/check_spelling.py` to check text against the active dictionary.
The importer supports previewing, duplicate detection, and upload verification.
New words are supplied by you; test fixtures are never loaded into the live database.

## Project files

- `data/grammar-guide-pages.json`: extracted source text needed to reproduce the
  draft dataset. The original PDF is in your Documents folder.
- `scripts/prepare_grammar_data.py`: prepares the draft CSV and JSONL records.
- `scripts/prepare_cloudflare_import.py`: validates the retained records and
  generates Cloudflare SQL imports. Add `--zip` to create a downloadable package.
- `output/cloudflare-grammar-import/`: the retained dataset snapshot, schema,
  seed SQL, and preparation reports.

Cloudflare D1 is the live database. Local dataset files are reproducible source
snapshots; rebuilding them does not update the cloud database. The preparation
reports describe the original build checks rather than current deployment state.
Private documents, extracted data, generated exports, and credentials are excluded
from GitHub. To rebuild datasets in a fresh checkout, supply your own source text
at `data/grammar-guide-pages.json`. The database definition is retained in
`schema/grammar.sql`.

## Rebuild when needed

From this project directory:

```sh
python3 scripts/prepare_grammar_data.py
python3 scripts/prepare_cloudflare_import.py
```

The first command regenerates draft records and resets the local review labels.
Keep human-reviewed records in D1 and release versioned exports for training.
The second command validates the data in memory and rebuilds SQL files. It
creates no persistent local database and performs no cloud upload.

The existing cloud database is already populated. The initial seed is for a
fresh database; re-importing it into the populated database encounters duplicate
keys. Future edits should update the intended records.
