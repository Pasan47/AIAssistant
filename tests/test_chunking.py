from app.retrieval.chunking import chunk_text, count_tokens


def test_chunks_respect_max_tokens_and_cover_text():
    text = "# Title\n\n" + "\n\n".join(f"Paragraph {i}. " + "word " * 120 for i in range(12))
    chunks = chunk_text(text, 500, 800, 80)
    assert len(chunks) > 1
    assert all(count_tokens(c) <= 800 + 200 for c in chunks)   # overlap may add a little
    assert "Paragraph 11" in chunks[-1] and "Paragraph 0" in chunks[0]


def test_short_document_is_single_chunk():
    assert len(chunk_text("# T\n\nshort doc")) == 1
