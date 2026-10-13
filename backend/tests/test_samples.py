from datasentinel.samples import generator


def test_sample_files_are_reproducible():
    """The committed sample files must be exactly what the seeded generator produces."""
    files = generator.build_files()
    for name, content in files.items():
        committed = (generator.DATA_DIR / name).read_text(encoding="utf-8")
        assert generator.digest(committed) == generator.digest(content), name


def test_generator_is_deterministic():
    assert generator.build_files() == generator.build_files()
