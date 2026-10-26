-- Cloudflare D1 / SQLite schema for a new empty database.
-- JSON objects and arrays are stored as TEXT with type checks.
-- Dataset rows remain unreviewed; this import does not train a model.

create table grammar_sources (
    id text primary key not null,
    filename text not null,
    title text not null,
    page_count integer not null check (page_count > 0),
    review_status text not null default 'needs_review'
        check (review_status in ('needs_review', 'approved', 'rejected'))
);

create table grammar_rules (
    id text primary key not null,
    source_id text not null references grammar_sources(id),
    lesson_number integer not null check (lesson_number > 0),
    title text not null,
    rule_text text not null,
    essentials text not null default '[]'
        check (json_type(essentials) = 'array'),
    language_code text not null default 'en',
    target_register text not null default 'standard_written',
    source_page integer not null check (source_page > 0),
    review_status text not null default 'needs_review'
        check (review_status in ('needs_review', 'approved', 'rejected')),
    unique (id, source_id),
    unique (source_id, lesson_number)
);

create table grammar_examples (
    id text primary key not null,
    rule_id text not null,
    source_id text not null references grammar_sources(id),
    source_page integer not null check (source_page > 0),
    source_refs text not null check (json_type(source_refs) = 'array'),
    input_text text not null check (length(input_text) > 0),
    target_text text not null check (length(target_text) > 0),
    explanation text not null,
    example_type text not null check (example_type in ('correction', 'unchanged')),
    language_code text not null default 'en',
    review_status text not null default 'needs_review'
        check (review_status in ('needs_review', 'approved', 'rejected')),
    review_notes text not null default '[]'
        check (json_type(review_notes) = 'array'),
    dataset_split text not null
        check (dataset_split in ('train', 'validation', 'test', 'review_only')),
    group_id text not null,
    foreign key (rule_id, source_id)
        references grammar_rules(id, source_id),
    check (
        (example_type = 'unchanged' and input_text = target_text) or
        (example_type = 'correction' and input_text <> target_text)
    ),
    unique (input_text, target_text)
);

create table grammar_vocabulary (
    id text primary key not null,
    word text not null check (length(word) > 0),
    part_of_speech text not null,
    forms text not null default '{}'
        check (json_type(forms) = 'object'),
    meaning text not null,
    example_sentence text not null,
    language_code text not null default 'en',
    review_status text not null default 'needs_review'
        check (review_status in ('needs_review', 'approved', 'rejected')),
    origin text not null
);

create index grammar_examples_release_idx
    on grammar_examples (review_status, dataset_split);
create index grammar_vocabulary_lookup_idx
    on grammar_vocabulary (language_code, lower(word));

