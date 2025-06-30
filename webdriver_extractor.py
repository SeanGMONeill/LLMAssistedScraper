import json
import re
from hashabledict import hashabledict
from selenium import webdriver
from selenium.webdriver.common.by import By

class WebdriverExtractor:
    def __init__(self, field_names, driver=None):
        self.driver = driver
        self.field_names = field_names

        if self.driver is None:
            self.driver = self.get_webdriver()

    @staticmethod
    def get_webdriver():
        options = webdriver.ChromeOptions()
        #options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36")
        return webdriver.Chrome(options=options)

    def find_elements_containing_text(self, text):
        xpath = f"//*[contains(text(), '{text}')]"
        return self.driver.find_elements(By.XPATH, xpath)

    def find_common_container(self, el, depth=4):
        current = el
        for _ in range(depth):
            parent = current.find_element(By.XPATH, "..")
            siblings = parent.find_elements(By.XPATH, "./*")
            if len(siblings) > 1:
                return parent
            current = parent
        return None

    def generate_css_selector(self, element):
        return self.driver.execute_script("""
        function getSelector(el) {
            if (el.id) return "#" + el.id;
            let path = [];
            while (el && el.nodeType === 1) {
                let selector = el.tagName.toLowerCase();
                if (el.className) {
                    selector += "." + el.className.trim().replace(/\\s+/g, '.');
                }
                path.unshift(selector);
                el = el.parentNode;
            }
            return path.join(" > ");
        }
        return getSelector(arguments[0]);
        """, element).replace('. >', ' >')

    def extract_record(self, el):
        try:
            children = el.find_elements(By.XPATH, ".//*")
            text_chunks = [c.text.strip() for c in children if c.text.strip()]
            if len(text_chunks) < len(self.field_names):
                raw = el.text.strip()
                parts = re.split(r"\s*[\u2013:|/\-]\s*", raw)
                parts = [p.strip() for p in parts if p.strip()]
                if len(parts) == len(self.field_names):
                    return hashabledict(dict(zip(self.field_names, parts)))
                return None
            return hashabledict(dict(zip(self.field_names, text_chunks)))
        except Exception:
            return None

    def infer_extraction_rule(self, known_values):
        delimiters = [" – ", " - ", ": ", " | ", " / "]
        phrases_to_try = [d.join(known_values) for d in delimiters] + known_values
        phrases_to_try = list(set(phrases_to_try))

        for phrase in phrases_to_try:
            print(f'Trying phrase {phrase}')
            candidates = self.find_elements_containing_text(phrase)
            for match in candidates:
                container = self.find_common_container(match)
                if not container:
                    continue
                selector = self.generate_css_selector(container)
                print(selector)
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                extracted = [self.extract_record(el) for el in elements]
                extracted = [e for e in extracted if e]
                for e in extracted:
                    if all(e.get(k, '').strip().lower() == v.strip().lower() for k, v in zip(self.field_names, known_values)):
                        return {
                            "selector": selector,
                            "method": "text_split" if not container.find_elements(By.TAG_NAME, "td") else "table_cells",
                            "delimiter": "–"
                        }
        return None

    def infer_individual_field_rules(self, known_pairs):
        """Find separate selectors for individual fields when combined approach fails"""
        field_rules = {}
        
        for field_name in self.field_names:
            print(f'Trying to find rule for field: {field_name}')
            rule = self._find_rule_for_field(field_name, known_pairs)
            if rule:
                field_rules[field_name] = rule
        
        return list(field_rules.values())

    def _find_rule_for_field(self, field_name, known_pairs):
        """Find a selector rule for a specific field"""
        field_values = [pair[field_name] for pair in known_pairs if field_name in pair]
        
        for value in field_values:
            print(f'Looking for elements containing: {value}')
            rule = self._try_selectors_for_value(field_name, value)
            if rule:
                return rule
        
        return None

    def _try_selectors_for_value(self, field_name, value):
        """Try different selectors to find one that works for the given value"""
        candidates = self.find_elements_containing_text(value)
        
        for match in candidates:
            elements_to_try = self._get_elements_to_try(match)
            
            for element in elements_to_try:
                selector = self.generate_css_selector(element)
                print(f'Testing selector: {selector}')
                
                if self._is_valid_selector_for_field(selector, field_name, value):
                    return {
                        "selector": selector,
                        "field": field_name,
                        "method": "individual_field",
                        "expected_value": value
                    }
        
        return None

    def _get_elements_to_try(self, match):
        """Get list of elements to try as selectors (element itself and parent containers)"""
        elements_to_try = [match]
        
        # Also try parent containers
        container = self.find_common_container(match, depth=2)
        if container:
            elements_to_try.append(container)
        
        return elements_to_try

    def _is_valid_selector_for_field(self, selector, field_name, expected_value):
        """Test if a selector reliably finds the expected field value"""
        try:
            found_elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
            print(f'Selector {selector} finds {len(found_elements)} total elements')
            
            matching_elements = self._find_matching_elements(found_elements, expected_value)
            
            if len(matching_elements) >= 1:
                print(f'Found {len(matching_elements)} matches, will filter during extraction')
                return True
            else:
                print(f'Selector finds no matching elements for {field_name}')
                return False
        except Exception as e:
            print(f'Error testing selector {selector}: {e}')
            return False

    def _find_matching_elements(self, elements, expected_value):
        """Find elements that match the expected value"""
        matching_elements = []
        for element in elements:
            element_text = element.text.strip()
            print(f'  Element text: "{element_text}"')
            
            if self._text_matches_expected_value(element_text, expected_value):
                matching_elements.append((element, element_text))
                print(f'  ✓ Matches expected value')
            else:
                print(f'  ✗ Does not match expected value "{expected_value}"')
        
        return matching_elements

    def _text_matches_expected_value(self, text, expected_value):
        """Check if element text matches the expected value"""
        return (expected_value.lower() == text.lower() or 
                (expected_value.lower() in text.lower() and len(text) <= len(expected_value) * 2))

    def extract_using_rule(self, rule):
        if rule.get("method") == "individual_field":
            return self.extract_individual_field(rule)
        else:
            elements = self.driver.find_elements(By.CSS_SELECTOR, rule["selector"])
            return [r for el in elements if (r := self.extract_record(el))]
    
    def extract_individual_field(self, rule):
        """Extract data for a single field using its specific selector"""
        elements = self.driver.find_elements(By.CSS_SELECTOR, rule["selector"])
        field_name = rule["field"]
        expected_value = rule.get("expected_value")
        results = []
        
        for element in elements:
            text = element.text.strip()
            if text and self._should_include_text(text, expected_value):
                record = hashabledict({field_name: text})
                results.append(record)
        
        return results

    def _should_include_text(self, text, expected_value):
        """Check if text should be included based on expected value"""
        if not expected_value:
            return True  # No expected value, accept any non-empty text
        
        return self._text_matches_expected_value(text, expected_value)

    def extract_using_rules(self, rules):
        # Check if we have individual field rules that need combining
        individual_rules = [r for r in rules if r.get("method") == "individual_field"]
        combined_rules = [r for r in rules if r.get("method") != "individual_field"]
        
        results = []
        
        # Process combined rules normally
        for rule in combined_rules:
            results.extend(self.extract_using_rule(rule))
        
        # Process individual field rules and combine them
        if individual_rules:
            record = {}
            for rule in individual_rules:
                field_name = rule["field"]
                field_results = self.extract_using_rule(rule)
                print(f"Field '{field_name}' found {len(field_results)} results: {field_results}")
                
                # For individual field rules, take the first result if any
                if field_results:
                    record[field_name] = field_results[0][field_name]
            
            # If we found any fields, add the combined record
            if record:
                results.append(hashabledict(record))
        
        return results

    def infer_rules(self, known_pairs):
        rules = []
        
        # First try the combined approach
        for p in known_pairs:
            values = [p[k] for k in self.field_names]
            rule = self.infer_extraction_rule(values)
            if rule:
                rules.append(rule)
        
        # If combined approach failed, try individual field rules
        if not rules:
            print("Combined approach failed, trying individual field rules...")
            individual_rules = self.infer_individual_field_rules(known_pairs)
            if individual_rules:
                rules.extend(individual_rules)
        
        if not rules:
            return None
        
        return list({json.dumps(r, sort_keys=True): r for r in rules}.values())
    
    def get_body_html(self):
        return self.driver.find_element(By.TAG_NAME, 'body').get_attribute('innerHTML')
    
    def navigate(self, url):
        return self.driver.get(url)