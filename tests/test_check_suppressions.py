import pytest

from scripts.check_suppressions import find_violations


@pytest.mark.parametrize(
    "source",
    [
        "x = 1  # noqa: S101\n",
        "x = 1  # noqa\n",
        "x: int = 'a'  # type: ignore[assignment]\n",
        "x = 1  # pyright: ignore\n",
    ],
)
def test_unjustified_suppression_is_reported(source: str) -> None:
    assert len(find_violations("f.py", source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "x = 1  # noqa: S101 -- assert de test\n",
        "x = 1  # noqa: S101, S102 - assert de test\n",
        "x = 1  # noqa: S101  # assert de test\n",
        "x: int = 'a'  # type: ignore[assignment] -- stub incomplet\n",
        "text = '# noqa'\n",
        "x = 1  # commentaire ordinaire\n",
    ],
)
def test_justified_or_unrelated_is_accepted(source: str) -> None:
    assert find_violations("f.py", source) == []


def test_unparseable_file_is_reported() -> None:
    assert find_violations("f.py", "x = (\n") == ["f.py: fichier non analysable"]
