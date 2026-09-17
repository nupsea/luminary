from app.services.math_normalizer import normalize_paper_math


def test_normalize_scaled_dot_product_attention():
    raw = (
        "In practice, we compute the matrix of outputs as:\n\n"
        "Attention(Q, K, V ) = softmax(QKT\n\n"
        "√dk\n\n"
        ")V\n(1)\n\n"
        "The two most commonly used attention functions..."
    )
    result = normalize_paper_math(raw)
    expected_attn = (
        r"\text{Attention}(Q, K, V) = "
        r"\text{softmax}\left(\frac{Q K^T}{\sqrt{d_k}}\right) V \tag{1}"
    )
    assert expected_attn in result
    assert "$$" in result


def test_normalize_multihead_attention():
    raw = (
        "MultiHead(Q, K, V ) = Concat(head1, ..., headh)W O\n\n"
        "where headi = Attention(QW Q\n\n"
        "i , KW K\n\n"
        "i , V W V\n\n"
        "i )\n\n"
        "Where the projections are parameter matrices W Q\n\n"
        "i\n"
        "∈ Rdmodel×dk, W K\n\n"
        "i\n"
        "∈ Rdmodel×dk, W V\n\n"
        "i\n"
        "∈ Rdmodel×dv\n"
        "and W O ∈ Rhdv×dmodel."
    )
    result = normalize_paper_math(raw)
    expected_head = (
        r"\text{MultiHead}(Q, K, V) &= "
        r"\text{Concat}(\text{head}_1, \dots, \text{head}_h) W^O"
    )
    assert expected_head in result
    assert r"W_i^Q \in \mathbb{R}^{d_{\text{model}} \times d_k}" in result


def test_normalize_ffn_and_positional_encoding():
    ffn_raw = "FFN(x) = max(0, xW1 + b1)W2 + b2\n(2)"
    ffn_res = normalize_paper_math(ffn_raw)
    assert r"\text{FFN}(x) = \max(0, x W_1 + b_1) W_2 + b_2 \tag{2}" in ffn_res

    pe_raw = (
        "PE(pos,2i) = sin(pos/100002i/dmodel)\n\n"
        "PE(pos,2i+1) = cos(pos/100002i/dmodel)"
    )
    pe_res = normalize_paper_math(pe_raw)
    expected_pe = (
        r"\text{PE}_{(pos, 2i)} &= "
        r"\sin\left(\frac{pos}{10000^{2i / d_{\text{model}}}}\right)"
    )
    assert expected_pe in pe_res


def test_normalize_inline_math():
    raw = "scale the dot products by\n1\n√dk . And multiply weights by √dmodel."
    res = normalize_paper_math(raw)
    assert r"$\frac{1}{\sqrt{d_k}}$" in res
    assert r"$\sqrt{d_{\text{model}}}$" in res


def test_normalize_math_is_idempotent():
    raw = "O(n/r) and O(n2 · d) and √dk"
    once = normalize_paper_math(raw)
    twice = normalize_paper_math(once)
    assert once == twice
    assert "$$O(n/r)$$" not in once
