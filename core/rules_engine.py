"""
core/rules_engine.py
Maps transaction notes to YNAB category + payee based on config rules.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class CategoryMatch:
    category: str
    payee: str
    matched_keyword: str


class RulesEngine:
    def __init__(self, rules: list[dict]):
        """
        rules: list of dicts from config.yaml with keys:
               keyword, category, payee
        """
        self.rules = rules

    def match(self, notes: str) -> Optional[CategoryMatch]:
        """
        Returns a CategoryMatch if any keyword found in notes,
        or None if notes is empty or no rule matches.
        """
        if not notes or not notes.strip():
            return None

        notes_lower = notes.lower()
        for rule in self.rules:
            if rule["keyword"].lower() in notes_lower:
                return CategoryMatch(
                    category=rule["category"],
                    payee=rule["payee"],
                    matched_keyword=rule["keyword"],
                )
        return None
