def test_package_importable():
    import agent_toolcall_sft  # noqa: F401


def test_contracts_module_exists():
    from agent_toolcall_sft import contracts  # noqa: F401
