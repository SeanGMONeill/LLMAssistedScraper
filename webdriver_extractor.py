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

    def extract_using_rule(self, rule):
        elements = self.driver.find_elements(By.CSS_SELECTOR, rule["selector"])
        return [r for el in elements if (r := self.extract_record(el))]

    def extract_using_rules(self, rules):
        return [r for rule in rules for r in self.extract_using_rule(rule)]

    def infer_rules(self, known_pairs):
        rules = []
        for p in known_pairs:
            values = [p[k] for k in self.field_names]
            rule = self.infer_extraction_rule(values)
            if rule:
                rules.append(rule)
        if not rules:
            return None
        return list({json.dumps(r, sort_keys=True): r for r in rules}.values())
    
    def get_body_html(self):
        return self.driver.find_element(By.TAG_NAME, 'body').get_attribute('innerHTML')
    
    def navigate(self, url):
        return self.driver.get(url)