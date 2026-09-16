"""WebGraph: the inferred knowledge graph over a crawled site.

`graph/` is the *observed* layer -- pages, heading-scoped sections, links with their anchor
text, the structured data a page published. It is free and deterministic. This package is
the *inferred* layer: a language model reads each section and states what it says -- the
entities, their typed attributes, the relationships between them -- and every statement is
kept only if the model quoted the section verbatim and the quote is found in one of the
section's blocks. The knowledge graph therefore cites the observed layer, `url#xpath` plus a
character span, for everything in it.

The product rule carried over from extraction: **never a false output.** An assertion with
no verified source block is rejected and counted; an answer sentence with no valid citation
is flagged, never silently kept.

Behind `WEBGRAPH_KG=1` until `benchmark/kg` shows it beats the BM25 context on typed and
two-hop questions on at least three sites.
"""

from webgraph.kg.model import (
    Attribute,
    Entity,
    Evidence,
    Hop,
    Mention,
    QueryPath,
    Relation,
)

__all__ = [
    "Attribute",
    "Entity",
    "Evidence",
    "Hop",
    "Mention",
    "QueryPath",
    "Relation",
]
