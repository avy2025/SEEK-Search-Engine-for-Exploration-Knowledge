---
title: FAISS Vector Search
---
# FAISS Vector Search

FAISS is a library for efficient similarity search over dense vectors. A text
embedding model converts a passage into a numeric vector, and a vector index
finds nearby passages for a query. Normalized vectors with inner-product search
can rank by cosine similarity.

Vector search complements keyword retrieval: it can match related concepts even
when the exact words differ. Persist index metadata alongside the vector file,
including document identifiers and the embedding model version, so results can
be mapped back to their source documents after a restart.
