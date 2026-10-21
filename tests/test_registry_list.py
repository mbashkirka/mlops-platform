from mlops_platform.registry_list import aliases_by_version


def test_aliases_by_version_inverts_and_sorts_alias_map() -> None:
    result = aliases_by_version(
        {
            "champion": "2",
            "candidate": "2",
            "baseline": "1",
        }
    )

    assert result == {
        "1": ["baseline"],
        "2": ["candidate", "champion"],
    }
