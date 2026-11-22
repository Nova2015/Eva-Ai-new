def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: hits the real public Piston API (network-gated, skipped by default)"
    )
