"""Check against the user's active Cloudflare dictionary; suggest, do not rewrite."""

import argparse
import json
import re
from collections import defaultdict

from cloudflare_d1 import query
from import_vocabulary import canonical_word, quote


def edit_distance(left, right):
    """Damerau optimal-string-alignment distance, including adjacent swaps."""
    rows = [list(range(len(right) + 1))]
    for i, first in enumerate(left, 1):
        row = [i]
        for j, second in enumerate(right, 1):
            value = min(rows[-1][j] + 1, row[-1] + 1, rows[-1][j - 1] + (first != second))
            if i > 1 and j > 1 and first == right[j - 2] and left[i - 2] == second:
                value = min(value, rows[-2][j - 2] + 1)
            row.append(value)
        rows.append(row)
    return rows[-1][-1]


def check_text(text, words, mistakes):
    dictionary = {row['normalized_word']: row['word'] for row in words}
    if not dictionary:
        raise ValueError('The spelling dictionary is empty. Import your vocabulary first.')
    explicit = defaultdict(set)
    for row in mistakes:
        explicit[row['normalized_misspelling']].add(row['word'])
    issues = []
    for match in re.finditer(r"[^\W\d_]+(?:['’‘‐‑-][^\W\d_]+)*", text, re.UNICODE):
        word = match.group()
        try:
            _, key = canonical_word(word)
        except ValueError:
            continue
        if key in dictionary:
            continue
        suggestions = sorted(explicit.get(key, []))
        if not suggestions:
            candidates = [(edit_distance(key, candidate), display) for candidate, display in dictionary.items()
                          if abs(len(candidate) - len(key)) <= 2]
            suggestions = [display for distance, display in sorted(candidates) if distance <= 2][:5]
        issues.append({'word': word, 'start': match.start(), 'end': match.end(),
                       'status': 'unknown_word', 'suggestions': suggestions})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--text', required=True)
    parser.add_argument('--database', default='grammar-ai')
    parser.add_argument('--language', default='en')
    parser.add_argument('--variety', default='general')
    args = parser.parse_args()
    scope = f'language_code={quote(args.language)} AND variety={quote(args.variety)}'
    words = query(args.database, f"SELECT word, normalized_word FROM spelling_words WHERE status='active' AND {scope};")
    mistakes = query(args.database,
        "SELECT m.normalized_misspelling,w.word FROM spelling_mistakes m JOIN spelling_words w ON m.correct_word_id=w.id WHERE w.status='active' AND " +
        f'w.language_code={quote(args.language)} AND w.variety={quote(args.variety)};')
    print(json.dumps({'issues': check_text(args.text, words, mistakes)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
