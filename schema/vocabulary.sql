-- Cloudflare D1: accepted spellings, corrections, and import provenance.
-- Additive and safe to run again. Existing grammar tables are unchanged.
CREATE TABLE IF NOT EXISTS spelling_sources (
    id TEXT PRIMARY KEY NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('file', 'url')),
    locator TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    input_format TEXT NOT NULL,
    language_code TEXT NOT NULL,
    variety TEXT NOT NULL DEFAULT 'general',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spelling_words (
    id TEXT PRIMARY KEY NOT NULL,
    word TEXT NOT NULL CHECK (length(word) > 0),
    normalized_word TEXT NOT NULL CHECK (length(normalized_word) > 0),
    language_code TEXT NOT NULL,
    variety TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'candidate', 'rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (language_code, variety, normalized_word)
);

CREATE TABLE IF NOT EXISTS spelling_word_sources (
    word_id TEXT NOT NULL REFERENCES spelling_words(id),
    source_id TEXT NOT NULL REFERENCES spelling_sources(id),
    PRIMARY KEY (word_id, source_id)
);

CREATE TABLE IF NOT EXISTS spelling_mistakes (
    id TEXT PRIMARY KEY NOT NULL,
    misspelling TEXT NOT NULL,
    normalized_misspelling TEXT NOT NULL,
    correct_word_id TEXT NOT NULL REFERENCES spelling_words(id),
    source_id TEXT NOT NULL REFERENCES spelling_sources(id),
    UNIQUE (normalized_misspelling, correct_word_id, source_id)
);

CREATE INDEX IF NOT EXISTS spelling_words_lookup_idx
    ON spelling_words (language_code, variety, status, normalized_word);
CREATE INDEX IF NOT EXISTS spelling_mistakes_lookup_idx
    ON spelling_mistakes (normalized_misspelling);
