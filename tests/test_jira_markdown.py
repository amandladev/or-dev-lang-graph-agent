"""Tests for JiraTool markdown_to_wiki conversion."""

import pytest

from autopilot.infrastructure.tools.jira_tool import markdown_to_wiki


class TestMarkdownToWiki:
    """Tests for markdown to Jira wiki markup conversion."""

    def test_headings(self):
        assert markdown_to_wiki("# Title") == "h1. Title"
        assert markdown_to_wiki("## Subtitle") == "h2. Subtitle"
        assert markdown_to_wiki("### Section") == "h3. Section"

    def test_bold(self):
        assert markdown_to_wiki("**bold**") == "*bold*"

    def test_inline_code(self):
        assert markdown_to_wiki("`code`") == "{{code}}"

    def test_links(self):
        assert markdown_to_wiki("[text](https://example.com)") == "[text|https://example.com]"

    def test_code_fences(self):
        md = "```python\nprint('hello')\n```"
        result = markdown_to_wiki(md)
        assert "{code:python}" in result
        assert "{code}" in result
        assert "print('hello')" in result

    def test_unordered_list(self):
        md = "- item1\n- item2"
        result = markdown_to_wiki(md)
        assert "* item1" in result
        assert "* item2" in result

    def test_ordered_list(self):
        md = "1. first\n2. second"
        result = markdown_to_wiki(md)
        assert "# first" in result
        assert "# second" in result

    def test_horizontal_rule(self):
        assert markdown_to_wiki("---") == "----"

    def test_table_header_promotion(self):
        md = "| Name | Value |\n|------|-------|\n| foo | bar |"
        result = markdown_to_wiki(md)
        assert "||Name||Value||" in result

    def test_empty_input(self):
        assert markdown_to_wiki("") == ""

    def test_passthrough_accountid_mentions(self):
        md = "[~accountid:12345]"
        assert markdown_to_wiki(md) == "[~accountid:12345]"
