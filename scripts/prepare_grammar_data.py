"""Prepare reviewable, cloud-importable data from the user's grammar guide.

Uses PDF text already extracted with macOS PDFKit. No model or training is used.
"""

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


SOURCE_ID = "english_handbook_96_rules"
SOURCE_FILENAME = "English_Grammar_200_Page_Complete_Guide.pdf"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# These textbook revisions need context, express a preference, add information,
# or reject an accepted grammatical alternative. They are excluded from the
# proposed training/evaluation splits until a person resolves the concern.
CONCERNS = {
    (1, 1): "The repair invents the missing action (opened).",
    (1, 2): "The happy can refer to a group of people; adding children invents information.",
    (2, 1): "The original is a grammatical example of locative inversion.",
    (2, 2): "The repair invents an activity (laughing) to complete a fragment.",
    (3, 2): "Imperatives with an explicit you can be acceptable in context.",
    (4, 2): "Adverb placement is a usage preference here rather than a universal ban.",
    (5, 1): "The intended noun/adjective meaning needs context.",
    (5, 2): "The original word order can occur in marked or literary usage.",
    (6, 2): "The repair supplies stood, although the missing action is unspecified.",
    (7, 1): "The repair invents a main clause about hearing traffic.",
    (7, 2): "The repair changes the causal relation because to the temporal relation after.",
    (8, 1): "Adding so asserts a causal relation not guaranteed by the original.",
    (8, 2): "The repair invents finding a letter.",
    (14, 1): "The choice of an indefinite or definite article depends on intended reference.",
    (14, 2): "The repair also changes a preposition with regional variation.",
    (15, 1): "Article use depends on whether happiness is generic or a specific experience.",
    (15, 2): "Article use depends on whether music is generic or previously identified.",
    (16, 1): "The intended number of possessors is unspecified.",
    (19, 2): "The intended referent needs checking before replacing a nonstandard reflexive.",
    (20, 2): "The repair changes plural reference to singular; plural repairs are also possible.",
    (24, 2): "Agreement with neither/nor involves variation and formal-style preferences.",
    (39, 1): "The original present-simple sentence can express a scheduled future event.",
    (45, 2): "Both constructions are grammatical but express different meanings.",
    (46, 2): "Could can express past ability; the repair assumes an actual accomplishment.",
    (47, 1): "The repair changes prohibition into absence of obligation.",
    (49, 1): "Adjective ordering can vary with emphasis and interpretation.",
    (51, 2): "Hard and hardly are both grammatical but express different meanings.",
    (52, 1): "Always is can be acceptable, especially with contrastive emphasis.",
    (53, 2): "The repair concerns emphasis and usage; validate the intended register.",
    (55, 1): "In can express movement into a place in accepted usage.",
    (55, 2): "The repair assumes the bridge was crossed and removes the expressed purpose.",
    (60, 2): "Same-polarity question tags can be grammatical with a different pragmatic meaning.",
    (61, 2): "Negative concord is grammatical in some varieties; scope the target variety.",
    (62, 2): "The original double negative can have an intended logical meaning.",
    (66, 2): "The repair invents a main clause (we left).",
    (67, 1): "Called yesterday can be a grammatical reduced passive relative clause.",
    (67, 2): "The repair imposes a defining reading that needs discourse context.",
    (68, 2): "The original defining which-clause is grammatical; commas alter its function.",
    (70, 2): "A comma after a short introductory clause can be optional.",
    (71, 1): "The repair invents an observer and a perception event.",
    (72, 2): "The comparison can involve metonymy; confirm the desired editing policy.",
    (73, 1): "Will in an if-clause can have a willingness reading in some contexts.",
    (75, 1): "The preferred formal conditional differs from accepted regional usage.",
    (76, 2): "Was is accepted in many hypothetical contexts; were is a formal preference.",
    (77, 2): "The repair depends on the target variety and register.",
    (78, 1): "Removing the negative reverses the expressed condition.",
    (80, 1): "Mandative indicative and subjunctive patterns vary by variety and context.",
    (80, 2): "The source explicitly acknowledges grammatical indicative alternatives.",
    (84, 1): "Quotation punctuation conventions differ between English styles.",
    (86, 2): "The repair invents the recipient me.",
    (87, 2): "The repair removes the recipient us instead of preserving it.",
    (88, 1): "When and that can both occur in time-focused constructions.",
    (90, 1): "The introductory-clause comma is partly a style choice for short clauses.",
    (94, 2): "Little students can mean physically small students and is grammatical.",
    (95, 2): "The original is grammatical; the repair chooses an unknown pronoun referent.",
}


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def canonical(text):
    return clean(text).casefold()


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                field: json.dumps(row[field], ensure_ascii=False)
                if isinstance(row[field], (list, dict)) else row[field]
                for field in fields
            })


def prepare(pages):
    rules, records = [], []
    for page in pages:
        text = page["text"]
        if "CONCEPTS & WORKED EXAMPLES" not in text:
            continue
        number = int(re.search(r"RULE (\d+) OF 96", text).group(1))
        rule_id = f"handbook-r{number:03d}"
        title = text.split("CONCEPTS & WORKED EXAMPLES\n", 1)[1].split("\n", 1)[0]
        description = text.split("THE RULE IN PLAIN ENGLISH\n", 1)[1].split("THREE ESSENTIALS", 1)[0]
        essentials = text.split("THREE ESSENTIALS\n", 1)[1].split("STUDY THE EXAMPLES", 1)[0]
        essentials = [clean(part) for part in re.split(r"(?m)^\d\.\s", essentials) if clean(part)]
        assert len(essentials) == 3, (number, essentials)
        rules.append({
            "id": rule_id, "source_id": SOURCE_ID, "lesson_number": number,
            "title": title, "rule_text": clean(description), "essentials": essentials,
            "language_code": "en", "target_register": "standard_written",
            "source_page": page["page"], "review_status": "needs_review",
        })

        clinic = text.split("ERROR CLINIC: INCORRECT -> CORRECTED\n", 1)[1].split("RECALL BEFORE TURNING THE PAGE", 1)[0]
        pairs = list(re.finditer(r"NOT:\s*(.*?)\nUSE:\s*(.*?)\n(.*?)(?=\nNOT:|\Z)", clinic, re.S))
        assert len(pairs) == 2, number
        for index, match in enumerate(pairs, 1):
            concern = CONCERNS.get((number, index))
            records.append({
                "id": f"{rule_id}-repair-{index}", "rule_id": rule_id,
                "source_id": SOURCE_ID, "source_page": page["page"],
                "source_refs": [{"page": page["page"], "lesson": number, "section": "error_clinic", "item": index}],
                "input_text": clean(match[1]), "target_text": clean(match[2]),
                "explanation": clean(match[3]), "example_type": "correction",
                "language_code": "en", "review_status": "needs_review",
                "review_notes": [concern] if concern else [],
            })

        worked = text.split("STUDY THE EXAMPLES\n", 1)[1].split("ERROR CLINIC:", 1)[0]
        models = list(re.finditer(r"(?m)^0([123]) (.+)$", worked))
        assert len(models) == 3, number
        for match in models:
            sentence = clean(match[2])
            assert re.search(r'[.!?][”"]?$', sentence), (number, sentence)
            records.append({
                "id": f"{rule_id}-unchanged-{match[1]}", "rule_id": rule_id,
                "source_id": SOURCE_ID, "source_page": page["page"],
                "source_refs": [{"page": page["page"], "lesson": number, "section": "worked_examples", "item": int(match[1])}],
                "input_text": sentence, "target_text": sentence,
                "explanation": "The guide presents this as a correct worked example; preserve it unchanged.",
                "example_type": "unchanged", "language_code": "en",
                "review_status": "needs_review", "review_notes": [],
            })

    assert {rule["lesson_number"] for rule in rules} == set(range(1, 97))
    deduplicated = {}
    for record in records:
        key = (record["input_text"], record["target_text"])
        if key in deduplicated:
            deduplicated[key]["source_refs"].extend(record["source_refs"])
            deduplicated[key]["review_notes"].extend(record["review_notes"])
        else:
            deduplicated[key] = record
    records = list(deduplicated.values())

    # Connected input/target groups stay together, including unchanged examples.
    parent = {}
    def find(item):
        parent.setdefault(item, item)
        if parent[item] != item:
            parent[item] = find(parent[item])
        return parent[item]
    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[max(left, right)] = min(left, right)
    for record in records:
        union(canonical(record["input_text"]), canonical(record["target_text"]))
    groups = defaultdict(list)
    for record in records:
        groups[find(canonical(record["input_text"]))].append(record)
    for key, members in groups.items():
        targets = defaultdict(set)
        for record in members:
            targets[record["input_text"]].add(record["target_text"])
        conflict = any(len(values) > 1 for values in targets.values())
        needs_context = conflict or any(record["review_notes"] for record in members)
        bucket = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 100
        split = "review_only" if needs_context else "train" if bucket < 80 else "validation" if bucket < 90 else "test"
        for record in members:
            record["dataset_split"] = split
            record["group_id"] = hashlib.sha256(key.encode()).hexdigest()[:16]
            if conflict:
                record["review_notes"].append("The same input has multiple targets in this source; resolve before training.")
            if needs_context and not record["review_notes"]:
                record["review_notes"].append("Shares an exact input/target group with an example requiring review.")
    return rules, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages-json", type=Path, default=PROJECT_ROOT / "data/grammar-guide-pages.json")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "output/cloudflare-grammar-import")
    args = parser.parse_args()
    pages = json.loads(args.pages_json.read_text())
    assert len(pages) == 200
    rules, records = prepare(pages)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    sources = [{"id": SOURCE_ID, "filename": SOURCE_FILENAME, "title": "The English Grammar Handbook: 96 Major Rules in 200 Pages", "page_count": 200, "review_status": "needs_review"}]
    write_csv(out / "grammar_sources.csv", sources, list(sources[0]))
    write_csv(out / "grammar_rules.csv", rules, list(rules[0]))
    write_csv(out / "grammar_examples.csv", records, list(records[0]))
    write_jsonl(out / "grammar_rules.jsonl", rules)
    for split in ["train", "validation", "test", "review_only"]:
        filename = "review_only.jsonl" if split == "review_only" else f"{split}_candidates.jsonl"
        write_jsonl(out / filename, [record for record in records if record["dataset_split"] == split])

    vocabulary = [
        {"id": "light-noun", "word": "light", "part_of_speech": "noun", "forms": {"plural": "lights"}, "meaning": "Illumination or a source of illumination.", "example_sentence": "The light is bright."},
        {"id": "light-verb", "word": "light", "part_of_speech": "verb", "forms": {"third_person_singular": "lights", "past": ["lit", "lighted"], "past_participle": ["lit", "lighted"], "present_participle": "lighting"}, "meaning": "To illuminate something or cause it to burn.", "example_sentence": "Please light the lamp."},
        {"id": "light-adjective", "word": "light", "part_of_speech": "adjective", "forms": {"comparative": "lighter", "superlative": "lightest"}, "meaning": "Having little weight.", "example_sentence": "A light jacket is useful."},
        {"id": "student-noun", "word": "student", "part_of_speech": "noun", "forms": {"plural": "students"}, "meaning": "A person who studies.", "example_sentence": "The student reads a book."},
        {"id": "go-verb", "word": "go", "part_of_speech": "verb", "forms": {"third_person_singular": "goes", "past": "went", "past_participle": "gone", "present_participle": "going"}, "meaning": "To move or travel to a place.", "example_sentence": "They go to school."},
    ]
    for row in vocabulary:
        row.update(language_code="en", review_status="needs_review", origin="illustrative_template_entry")
    write_csv(out / "vocabulary_template.csv", vocabulary, list(vocabulary[0]))
    report = {
        "source_pages": 200, "grammar_rules": len(rules),
        "unique_examples": len(records), "duplicate_pairs_removed": 480 - len(records),
        "example_types": dict(Counter(row["example_type"] for row in records)),
        "proposed_splits": dict(Counter(row["dataset_split"] for row in records)),
        "approved_examples": 0, "status": "draft_candidates_requiring_linguistic_review",
        "spelling_typo_pairs_included": 0,
        "partition_method": "deterministic grouped input/target split; context/style concerns isolated for review",
        "external_cloud_changes": "none",
    }
    (out / "dataset_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
