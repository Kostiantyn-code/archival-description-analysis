"""Перевіряє індексований пошук за допомогою збереженого прямого пошуку."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from text_matching import (
    MATCH_LANGUAGE, contains_item, item_matcher, mask_item, stem_tokens,
)


class MatchingTests(unittest.TestCase):
    def test_index_matches_direct_search(self):
        randomizer = random.Random(230)
        words = ['суд', 'судно', 'військово-морський', 'военно-морской',
                 'морський', 'морской', 'навчальний', 'округ', 'школа',
                 'карантин', 'лікарня', 'больница', 'ремонт', '1850', '__masked__']
        for language in ('uk', 'ru'):
            token = MATCH_LANGUAGE.set(language)
            try:
                for _ in range(120):
                    tokens = stem_tokens(' '.join(randomizer.choices(words, k=randomizer.randrange(20))))
                    matches = item_matcher(tokens)
                    items = ['', '!!!', *words] + [
                        ' '.join(randomizer.choices(words, k=randomizer.randrange(2, 5)))
                        for _ in range(15)
                    ]
                    for item in items:
                        with self.subTest(language=language, tokens=tokens, item=item):
                            expected = contains_item(tokens, item)
                            self.assertEqual(matches(item), expected)
                            self.assertEqual(matches(item), expected)  # repeated lookup
            finally:
                MATCH_LANGUAGE.reset(token)

    def test_category_masks_have_separate_indexes(self):
        tokens = stem_tokens('метрична книга і ремонт лікарні')
        unmasked = item_matcher(tokens)
        masked = item_matcher(mask_item(tokens, 'метрична книга'))
        self.assertTrue(unmasked('книга'))
        self.assertFalse(masked('книга'))
        self.assertTrue(masked('ремонт лікарні'))
        self.assertTrue(unmasked('книга'))

    def test_language_is_captured_for_each_index(self):
        matchers = []
        for language in ('uk', 'ru'):
            token = MATCH_LANGUAGE.set(language)
            try:
                matchers.append(item_matcher(stem_tokens('карантинного режима')))
            finally:
                MATCH_LANGUAGE.reset(token)
        for _ in range(2):
            for language, matches in zip(('uk', 'ru'), matchers):
                token = MATCH_LANGUAGE.set(language)
                try:
                    expected = contains_item(stem_tokens('карантинного режима'), 'режим')
                finally:
                    MATCH_LANGUAGE.reset(token)
                self.assertEqual(matches('режим'), expected)


if __name__ == '__main__':
    unittest.main()
