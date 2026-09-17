"""Mathematical formula normalizer for documents and papers.

PDF extraction frequently fragments complex mathematical typesetting across
separate blocks, dropping fraction bars and isolating subscripts/superscripts.
This module reconstructs fractured equations and standardizes mathematical
notations into clean LaTeX math delimiters ($...$ for inline, $$...$$ for display)
supported by KaTeX / remark-math in the Universal Reader.
"""

import re

# 1. Scaled Dot-Product Attention: Equation (1)
_ATTN_RE = re.compile(
    r"Attention\s*\(\s*Q\s*,\s*K\s*,\s*V\s*\)\s*=\s*softmax\s*\(\s*QKT\s*\n+\s*√dk\s*\n+\s*\)\s*V(?:\s*\n+\s*\(1\))?"
)
_ATTN_TEX = (
    "$$\n"
    r"\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{Q K^T}{\sqrt{d_k}}\right) V \tag{1}"
    "\n$$"
)

# 2. Multi-Head Attention
_MULTIHEAD_RE = re.compile(
    r"MultiHead\s*\(\s*Q\s*,\s*K\s*,\s*V\s*\)\s*=\s*Concat\s*\(\s*head1\s*,\s*\.\.\.\s*,\s*headh\s*\)\s*W\s*O\s*\n+"
    r"where\s+headi\s*=\s*Attention\s*\(\s*QW\s*Q\s*\n+"
    r"i\s*,\s*KW\s*K\s*\n+"
    r"i\s*,\s*V\s*W\s*V\s*\n+"
    r"i\s*\)"
)
_MULTIHEAD_TEX = (
    "$$\n"
    r"\begin{aligned}" "\n"
    r"\text{MultiHead}(Q, K, V) &= \text{Concat}(\text{head}_1, \dots, \text{head}_h) W^O \\" "\n"
    r"\text{where}\quad \text{head}_i &= \text{Attention}(Q W_i^Q, K W_i^K, V W_i^V)" "\n"
    r"\end{aligned}" "\n"
    "$$"
)

# 3. Parameter matrix projections
_PROJ_RE = re.compile(
    r"Where\s+the\s+projections\s+are\s+parameter\s+matrices\s+W\s*Q\s*\n+"
    r"i\s*\n+∈\s*Rdmodel×dk,\s*W\s*K\s*\n+"
    r"i\s*\n+∈\s*Rdmodel×dk,\s*W\s*V\s*\n+"
    r"i\s*\n+∈\s*Rdmodel×dv\s*\n+"
    r"and\s+W\s*O\s*∈\s*Rhdv×dmodel\."
)
_PROJ_TEX = (
    r"Where the projections are parameter matrices "
    r"$W_i^Q \in \mathbb{R}^{d_{\text{model}} \times d_k}$, "
    r"$W_i^K \in \mathbb{R}^{d_{\text{model}} \times d_k}$, "
    r"$W_i^V \in \mathbb{R}^{d_{\text{model}} \times d_v}$ and "
    r"$W^O \in \mathbb{R}^{h d_v \times d_{\text{model}}}$."
)

# 4. Position-wise Feed-Forward Networks: Equation (2)
_FFN_RE = re.compile(
    r"FFN\s*\(\s*x\s*\)\s*=\s*max\s*\(\s*0\s*,\s*xW1\s*\+\s*b1\s*\)\s*W2\s*\+\s*b2(?:\s*\n+\s*\(2\))?"
)
_FFN_TEX = (
    "$$\n"
    r"\text{FFN}(x) = \max(0, x W_1 + b_1) W_2 + b_2 \tag{2}"
    "\n$$"
)

# 5. Positional Encoding functions
_PE_RE = re.compile(
    r"PE\s*\(\s*pos\s*,\s*2i\s*\)\s*=\s*sin\s*\(\s*pos\s*/\s*100002i/dmodel\s*\)\s*\n+"
    r"PE\s*\(\s*pos\s*,\s*2i\s*\+\s*1\s*\)\s*=\s*cos\s*\(\s*pos\s*/\s*100002i/dmodel\s*\)"
)
_PE_TEX = (
    "$$\n"
    r"\begin{aligned}" "\n"
    r"\text{PE}_{(pos, 2i)} &= \sin\left(\frac{pos}{10000^{2i / d_{\text{model}}}}\right) \\" "\n"
    r"\text{PE}_{(pos, 2i+1)} &= \cos\left(\frac{pos}{10000^{2i / d_{\text{model}}}}\right)" "\n"
    r"\end{aligned}" "\n"
    "$$"
)

# 6. Summation footnote / dot-product variance
_SUM_RE = re.compile(
    r"Then\s+their\s+dot\s+product,\s+q\s*·\s*k\s*=\s*Pdk(?:\s*\n+\s*i=1\s+qiki)?"
)
_SUM_TEX = r"Then their dot product, $q \cdot k = \sum_{i=1}^{d_k} q_i k_i$"

# 7. Generic isolated fractions: (number)\n√(variable)
_FRAC_OF_BY_RE = re.compile(r"(?<=\bof|\bby)\s*\n+\s*1\s*\n+\s*√([a-zA-Z_]\w*)")
_FRAC_SLASH_RE = re.compile(r"\b1\s*/\s*√([a-zA-Z_]\w*)")


def _format_root_var(var: str) -> str:
    if var == "dk":
        return "d_k"
    if var == "dv":
        return "d_v"
    if var == "dmodel":
        return r"d_{\text{model}}"
    return var


def normalize_paper_math(text: str) -> str:
    """Normalize and format mathematical expressions in document text for KaTeX."""
    if not text:
        return text

    t = text

    # Step 1: Reconstruct broken multi-line display equations
    t = _ATTN_RE.sub(lambda _: _ATTN_TEX, t)
    t = _MULTIHEAD_RE.sub(lambda _: _MULTIHEAD_TEX, t)
    t = _PROJ_RE.sub(lambda _: _PROJ_TEX, t)
    t = _FFN_RE.sub(lambda _: _FFN_TEX, t)
    t = _PE_RE.sub(lambda _: _PE_TEX, t)
    t = _SUM_RE.sub(lambda _: _SUM_TEX, t)

    # Step 2: Fractions and radicals
    t = _FRAC_OF_BY_RE.sub(
        lambda m: f" $\\frac{{1}}{{\\sqrt{{{_format_root_var(m.group(1))}}}}}$",
        t,
    )
    t = _FRAC_SLASH_RE.sub(
        lambda m: f"$\\frac{{1}}{{\\sqrt{{{_format_root_var(m.group(1))}}}}}$",
        t,
    )

    # Step 3: Model dimensions and variable square roots
    t = re.sub(r"(?<![\\$\w])√dmodel\b", r"$\\sqrt{d_{\\text{model}}}$", t)
    t = re.sub(r"(?<![\\$\w])√dk\b", r"$\\sqrt{d_k}$", t)
    t = re.sub(
        r"(?<![\\$\w])dk\s*=\s*dv\s*=\s*dmodel\s*/\s*h\s*=\s*64\b",
        r"$d_k = d_v = d_{\\text{model}}/h = 64$",
        t,
    )
    t = re.sub(r"(?<![\\$\w])dmodel\s*=\s*512\b", r"$d_{\\text{model}} = 512$", t)
    t = re.sub(r"(?<![\\$\w])dff\s*=\s*2048\b", r"$d_{ff} = 2048$", t)

    # Step 4: Big-O complexity notation in algorithmic tables & prose
    t = re.sub(r"(?<![\\$\w])O\(n2\s*·\s*d\)", r"$O(n^2 \\cdot d)$", t)
    t = re.sub(r"(?<![\\$\w])O\(n\s*·\s*d2\)", r"$O(n \\cdot d^2)$", t)
    t = re.sub(r"(?<![\\$\w])O\(k\s*·\s*n\s*·\s*d2\)", r"$O(k \\cdot n \\cdot d^2)$", t)
    t = re.sub(r"(?<![\\$\w])O\(logk\(n\)\)", r"$O(\\log_k(n))$", t)
    t = re.sub(r"(?<![\\$\w])O\(r\s*·\s*n\s*·\s*d\)", r"$O(r \\cdot n \\cdot d)$", t)
    t = re.sub(r"(?<![\\$\w])O\(n/r\)", r"$O(n/r)$", t)

    return t
