from retrievers.formatter import format_results


def test_formatter_supports_legacy_page_field_and_source_rel_path():
    output = format_results([
        {
            "score": 1.23,
            "item": {
                "doc_id": "d1",
                "title": "Doc",
                "page": 7,
                "source_rel_path": "paper.pdf",
                "content": "content",
            },
        }
    ])

    assert "Page: 7" in output
    assert "Source: paper.pdf" in output
