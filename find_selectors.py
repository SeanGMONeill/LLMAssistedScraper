import html2text
import json
import itertools

from hashabledict import hashabledict
from webdriver_extractor import WebdriverExtractor
from llm_client import LLMClient
from schema import Schema
from sites import Sites

def normalize(item):
    return {k: v.lower() if isinstance(v, str) else v for k, v in item.items()}

def has_record(iterable, record):
    for x in iterable:
        if all(normalize(x).get(k) == normalize(record).get(k) for k in record):
            return True
    return False

def count_matching_records(iterable, ground_truth):
    return sum(1 for r in ground_truth if has_record(iterable, r))

def has_all_matching_records(iterable, ground_truth):
    return count_matching_records(iterable, ground_truth) == len(ground_truth)

def minimal_rule_combo_for_total_cover(rules_with_matches, known_pairs):
    rule_sets = [(r, e) for r, e in rules_with_matches]
    print(f'Found {len(rule_sets)} rule sets')
    
    # Check if we have individual field rules
    has_individual_rules = any(r.get("method") == "individual_field" for r, e in rule_sets)
    
    if has_individual_rules:
        # For individual field rules, we need all fields to be covered
        field_names = set()
        for pair in known_pairs:
            field_names.update(pair.keys())
        
        # Group rules by field
        field_rules = {}
        combined_rules = []
        
        for rule, matches in rule_sets:
            if rule.get("method") == "individual_field":
                field_name = rule["field"]
                if field_name not in field_rules:
                    field_rules[field_name] = []
                field_rules[field_name].append((rule, matches))
            else:
                combined_rules.append((rule, matches))
        
        # If we have individual field rules for all required fields, use them
        if set(field_rules.keys()) >= field_names:
            selected_rules = []
            for field_name in field_names:
                # Just take the first rule for each field
                if field_name in field_rules:
                    selected_rules.append(field_rules[field_name][0][0])
            return selected_rules
        
        # Otherwise fall back to combined rules if available
        if combined_rules:
            rule_sets = combined_rules
    
    # Original logic for combined rules
    for r in range(1, len(rule_sets) + 1):
        for combo in itertools.combinations(rule_sets, r):
            rule_set = [x[0] for x in combo]
            all_matches = set(hashabledict(x) for pair in combo for x in pair[1])
            if has_all_matching_records(all_matches, known_pairs):
                print('Rule set has all')
                return rule_set
            print(f'Finds {count_matching_records(all_matches, known_pairs)} items')
    print('NO PERFECT COMBO?!')
    return [x[0] for x in rule_sets]

def determine_rules(extractor, schema):
    markdown_text = html2text.html2text(extractor.get_body_html())
    with open('example_markdown.md', 'w') as file:
        file.write(markdown_text)
    llm_summary = llm_client.extract_details(markdown_text, schema)
    print(llm_summary)
    print('Got LLM response')
    rules_with_matches = []
    rules = extractor.infer_rules(llm_summary['extracted_data'])
    print('Testing rules')
    for rule in rules:
        matches = extractor.extract_using_rule(rule)
        rules_with_matches.append((rule, matches))
    print('Finding minimal combo')
    rules = minimal_rule_combo_for_total_cover(rules_with_matches, llm_summary['extracted_data'])
    return rules

if __name__ == '__main__':
    with open('openai_key.txt', 'r') as file:
        openai_key = file.read().strip()
    llm_client = LLMClient(api_key=openai_key)
    sites = Sites.from_file('sites/books.json')
    field_names = sites.schema.attributes
    extractor = WebdriverExtractor(field_names)

    for site in sites.sites:
        print(f'Processing {site['name']}')
        extractor.navigate(site['url'])
        rules_file = f'rules/{sites.id}_{site['id']}.json'
        try:
            with open(rules_file, 'r') as file:
                rules = json.load(file)
        except:
            print('Determining rules')
            rules = determine_rules(extractor, sites.schema)
            print('Determined rules')
            with open(rules_file, 'w') as f: 
                json.dump(rules, f)

        extraction = extractor.extract_using_rules(rules)
        with open(f'results/{sites.id}_{site['id']}.json', 'w') as f: 
            json.dump(extraction, f, indent=4)
