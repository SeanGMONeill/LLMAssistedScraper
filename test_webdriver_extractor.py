import unittest
from unittest.mock import Mock, patch, MagicMock
from webdriver_extractor import WebdriverExtractor
from hashabledict import hashabledict


class TestWebdriverExtractor(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.mock_driver = Mock()
        self.field_names = ["title", "author", "isbn"]
        self.extractor = WebdriverExtractor(self.field_names, driver=self.mock_driver)

    def test_text_matches_expected_value_exact_match(self):
        """Test exact text matching"""
        result = self.extractor._text_matches_expected_value("Terry Pratchett", "Terry Pratchett")
        self.assertTrue(result)

    def test_text_matches_expected_value_case_insensitive(self):
        """Test case insensitive matching"""
        result = self.extractor._text_matches_expected_value("TERRY PRATCHETT", "terry pratchett")
        self.assertTrue(result)

    def test_text_matches_expected_value_partial_within_limit(self):
        """Test partial matching within length limit"""
        # Text is 1.5x longer than expected value - should match
        result = self.extractor._text_matches_expected_value("Terry Pratchett Author", "Terry Pratchett")
        self.assertTrue(result)

    def test_text_matches_expected_value_partial_exceeds_limit(self):
        """Test partial matching that exceeds length limit"""
        # Text is more than 2x longer - should not match
        result = self.extractor._text_matches_expected_value(
            "Terry Pratchett is a famous British author known for fantasy", 
            "Terry Pratchett"
        )
        self.assertFalse(result)

    def test_text_matches_expected_value_no_match(self):
        """Test non-matching text"""
        result = self.extractor._text_matches_expected_value("Stephen King", "Terry Pratchett")
        self.assertFalse(result)

    def test_should_include_text_no_expected_value(self):
        """Test text inclusion when no expected value is provided"""
        result = self.extractor._should_include_text("Any text", None)
        self.assertTrue(result)

    def test_should_include_text_with_expected_value_match(self):
        """Test text inclusion with matching expected value"""
        result = self.extractor._should_include_text("Terry Pratchett", "Terry Pratchett")
        self.assertTrue(result)

    def test_should_include_text_with_expected_value_no_match(self):
        """Test text inclusion with non-matching expected value"""
        result = self.extractor._should_include_text("Stephen King", "Terry Pratchett")
        self.assertFalse(result)

    def test_find_matching_elements(self):
        """Test finding elements that match expected value"""
        # Create mock elements
        mock_element1 = Mock()
        mock_element1.text = "Terry Pratchett"
        mock_element2 = Mock()
        mock_element2.text = "Stephen King"
        mock_element3 = Mock()
        mock_element3.text = "Terry Pratchett Author"

        elements = [mock_element1, mock_element2, mock_element3]
        
        with patch('builtins.print'):  # Suppress print output during tests
            matching = self.extractor._find_matching_elements(elements, "Terry Pratchett")
        
        # Should find element1 (exact match) and element3 (partial match within limit)
        self.assertEqual(len(matching), 2)
        self.assertEqual(matching[0][1], "Terry Pratchett")
        self.assertEqual(matching[1][1], "Terry Pratchett Author")

    def test_get_elements_to_try(self):
        """Test getting elements to try for selector generation"""
        mock_match = Mock()
        mock_container = Mock()
        
        with patch.object(self.extractor, 'find_common_container', return_value=mock_container):
            elements = self.extractor._get_elements_to_try(mock_match)
        
        # Should return the match element and its container
        self.assertEqual(len(elements), 2)
        self.assertEqual(elements[0], mock_match)
        self.assertEqual(elements[1], mock_container)

    def test_get_elements_to_try_no_container(self):
        """Test getting elements when no container is found"""
        mock_match = Mock()
        
        with patch.object(self.extractor, 'find_common_container', return_value=None):
            elements = self.extractor._get_elements_to_try(mock_match)
        
        # Should return only the match element
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0], mock_match)

    @patch('builtins.print')
    def test_extract_individual_field_with_filtering(self, mock_print):
        """Test extracting individual field with expected value filtering"""
        # Setup mock elements
        mock_element1 = Mock()
        mock_element1.text = "9780552167635"  # Should match
        mock_element2 = Mock()
        mock_element2.text = "Transworld Publishers Ltd"  # Should not match
        
        self.mock_driver.find_elements.return_value = [mock_element1, mock_element2]
        
        rule = {
            "selector": "test-selector",
            "field": "isbn",
            "method": "individual_field",
            "expected_value": "9780552167635"
        }
        
        results = self.extractor.extract_individual_field(rule)
        
        # Should only return the matching element
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["isbn"], "9780552167635")

    @patch('builtins.print')
    def test_extract_individual_field_no_filtering(self, mock_print):
        """Test extracting individual field without expected value filtering"""
        # Setup mock elements
        mock_element1 = Mock()
        mock_element1.text = "Some text"
        mock_element2 = Mock()
        mock_element2.text = "Other text"
        
        self.mock_driver.find_elements.return_value = [mock_element1, mock_element2]
        
        rule = {
            "selector": "test-selector",
            "field": "title",
            "method": "individual_field"
            # No expected_value - should accept all non-empty text
        }
        
        results = self.extractor.extract_individual_field(rule)
        
        # Should return both elements
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Some text")
        self.assertEqual(results[1]["title"], "Other text")

    @patch('builtins.print')
    def test_is_valid_selector_for_field_success(self, mock_print):
        """Test selector validation when matching elements are found"""
        # Setup mock elements
        mock_element1 = Mock()
        mock_element1.text = "Terry Pratchett"
        mock_element2 = Mock()
        mock_element2.text = "Other text"
        
        self.mock_driver.find_elements.return_value = [mock_element1, mock_element2]
        
        result = self.extractor._is_valid_selector_for_field(
            "test-selector", "author", "Terry Pratchett"
        )
        
        self.assertTrue(result)

    @patch('builtins.print')
    def test_is_valid_selector_for_field_no_matches(self, mock_print):
        """Test selector validation when no matching elements are found"""
        # Setup mock elements that don't match
        mock_element1 = Mock()
        mock_element1.text = "Stephen King"
        mock_element2 = Mock()
        mock_element2.text = "Other text"
        
        self.mock_driver.find_elements.return_value = [mock_element1, mock_element2]
        
        result = self.extractor._is_valid_selector_for_field(
            "test-selector", "author", "Terry Pratchett"
        )
        
        self.assertFalse(result)

    @patch('builtins.print')
    def test_is_valid_selector_for_field_exception(self, mock_print):
        """Test selector validation when an exception occurs"""
        # Make find_elements raise an exception
        self.mock_driver.find_elements.side_effect = Exception("Selector error")
        
        result = self.extractor._is_valid_selector_for_field(
            "invalid-selector", "author", "Terry Pratchett"
        )
        
        self.assertFalse(result)

    @patch('builtins.print')
    def test_try_selectors_for_value_success(self, mock_print):
        """Test trying selectors for a value when one is found"""
        mock_candidate = Mock()
        mock_element = Mock()
        
        with patch.object(self.extractor, 'find_elements_containing_text', return_value=[mock_candidate]), \
             patch.object(self.extractor, '_get_elements_to_try', return_value=[mock_element]), \
             patch.object(self.extractor, 'generate_css_selector', return_value="test-selector"), \
             patch.object(self.extractor, '_is_valid_selector_for_field', return_value=True):
            
            result = self.extractor._try_selectors_for_value("author", "Terry Pratchett")
        
        expected_rule = {
            "selector": "test-selector",
            "field": "author",
            "method": "individual_field",
            "expected_value": "Terry Pratchett"
        }
        
        self.assertEqual(result, expected_rule)

    @patch('builtins.print')
    def test_try_selectors_for_value_no_valid_selector(self, mock_print):
        """Test trying selectors when no valid selector is found"""
        mock_candidate = Mock()
        mock_element = Mock()
        
        with patch.object(self.extractor, 'find_elements_containing_text', return_value=[mock_candidate]), \
             patch.object(self.extractor, '_get_elements_to_try', return_value=[mock_element]), \
             patch.object(self.extractor, 'generate_css_selector', return_value="test-selector"), \
             patch.object(self.extractor, '_is_valid_selector_for_field', return_value=False):
            
            result = self.extractor._try_selectors_for_value("author", "Terry Pratchett")
        
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()