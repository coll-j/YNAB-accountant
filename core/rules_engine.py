"""
core/rules_engine.py
Maps transaction notes to YNAB category + payee based on config rules.
"""
from dataclasses import dataclass
import re
from typing import Optional


@dataclass
class CategoryMatch:
    category_id: str
    payee_id: str
    matched_keyword: str


class RulesEngine:
    def __init__(self, rules: list[dict]):
        """
        rules: list of dicts from config.yaml with keys:
               keywords, category_id, payee_id
        """
        self.rules = []
        for rule in rules:
            keywords = rule.get('keywords', [])
            category_id = rule.get('category_id')
            payee_id = rule.get('payee_id')


            if keywords and category_id:
                # Create a regex pattern: (word1|word2|word3)
                # re.escape ensures special characters in keywords don't break the regex
                pattern_str = '|'.join(re.escape(k) for k in keywords)
                
                # Use re.IGNORECASE so 'uber' matches 'Uber'
                # Use \b if you only want to match whole words (e.g., 'Car' not 'Cartoon')
                pattern = re.compile(rf"\b({pattern_str})\b", re.IGNORECASE)
                
                self.rules.append({
                    'pattern': pattern,
                    'category_id': category_id,
                    'payee_id': payee_id
                })


    def match(self, notes: str) -> Optional[CategoryMatch]:
        """
        Returns a CategoryMatch if any keyword found in notes,
        or None if notes is empty or no rule matches.
        """
        if not notes:
            return None
            
        for rule in self.rules:
            print(f"Checking rule: keywords={rule['pattern'].pattern}, category_id={rule['category_id']}, payee_id={rule['payee_id']}")
            if rule['pattern'].search(notes):
                print(f"Matched rule: {rule['pattern'].pattern} in notes: {notes}")
                return CategoryMatch(
                    category_id=rule["category_id"],
                    payee_id=rule["payee_id"],
                    matched_keyword=rule["pattern"],
                )
            
        print(f"No rules matched for notes: {notes}")
        return None
