from routing.hash_encoder import HashingEncoder


def test_hash_encoder_produces_normalized_vectors():
    encoder = HashingEncoder(dimensions=64)
    vectors = encoder(["hello world", "goodbye world"])

    assert len(vectors) == 2
    for vec in vectors:
        assert len(vec) == 64
        # Normalized: norm ≈ 1.0
        norm = sum(v * v for v in vec)
        assert abs(norm - 1.0) < 1e-9 if any(v != 0 for v in vec) else norm == 0


def test_hash_encoder_handles_empty_input():
    encoder = HashingEncoder()
    vectors = encoder([""])
    assert len(vectors) == 1
    assert all(v == 0.0 for v in vectors[0])


def test_hash_encoder_is_deterministic():
    encoder = HashingEncoder(dimensions=128)
    v1 = encoder(["transformers are attention-based models"])
    v2 = encoder(["transformers are attention-based models"])
    assert v1 == v2


def test_hash_encoder_different_inputs_produce_different_vectors():
    encoder = HashingEncoder(dimensions=128)
    v1 = encoder(["machine learning is powerful"])[0]
    v2 = encoder(["deep learning revolutionizes AI"])[0]
    # Extremely unlikely to be identical
    assert v1 != v2
