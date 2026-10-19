import os

import pytest
from playwright.sync_api import Page


@pytest.mark.browser
def test_foundation_home_and_health(page: Page):
    base_url = os.getenv("PLAYWRIGHT_BASE_URL", "http://127.0.0.1:8000")

    page.goto(base_url)
    assert page.get_by_role("heading", name="GlideCRM").is_visible()

    response = page.goto(f"{base_url}/health/")
    assert response is not None
    assert response.status == 200
    assert '"status": "ok"' in page.locator("body").inner_text()
