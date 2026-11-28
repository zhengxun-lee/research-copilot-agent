from tools.summarizer import SummarizerTool


def test_summarizer_keeps_best_sentences_in_original_order():
    text = "RAG uses retrieval. Cats sleep. Retrieval helps language models answer with evidence."

    output = SummarizerTool().run(text=text, max_sentences=2)

    assert "RAG uses retrieval." in output
    assert "Retrieval helps" in output


def test_summarizer_rejects_empty_text():
    assert "Error" in SummarizerTool().run(text="")


def test_summarizer_rejects_non_integer_max_sentences():
    assert "Error" in SummarizerTool().run(text="hello world.", max_sentences="3")
    # bool is a subclass of int — explicitly reject True
    assert "Error" in SummarizerTool().run(text="hello world.", max_sentences=True)


def test_summarizer_rejects_zero_max_sentences():
    assert "Error" in SummarizerTool().run(text="hello.", max_sentences=0)
    assert "Error" in SummarizerTool().run(text="hello.", max_sentences=-1)


def test_summarizer_caps_max_sentences():
    tool = SummarizerTool()
    text = ". ".join(f"sentence number {i}" for i in range(50))
    output = tool.run(text=text, max_sentences=999)
    # Should not exceed the configured cap (MAX_SENTENCES = 20)
    assert output.count("sentence number") <= tool.MAX_SENTENCES


def test_summarizer_returns_input_when_shorter_than_max():
    text = "Just one short sentence."
    output = SummarizerTool().run(text=text, max_sentences=5)
    assert "Just one short sentence." in output


def test_summarizer_handles_only_stopwords():
    text = "the a an of in"
    output = SummarizerTool().run(text=text, max_sentences=3)
    # No crash; result is the original text (or error fallback)
    assert isinstance(output, str)
