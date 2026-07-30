from chromadb_repo_indexer.chroma import batches


def test_batching_is_bounded_and_ordered() -> None:
    assert list(batches(list(range(7)), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
