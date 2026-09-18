from __future__ import annotations

from tests.routes.test_api_flow import api  # noqa: F401


def test_page_image_endpoint_maps_global_index_to_source_page(api):  # noqa: F811
    client, subject, *_ = api
    response = client.get(f"/api/subjects/{subject.id}/pages/4/image")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/subjects/{subject.id}/pages/999/image").status_code == 404
    assert client.get(f"/api/subjects/{subject.id}/pages/-1/image").status_code == 404


def test_the_image_is_rendered_once_and_then_served_from_the_store(api):  # noqa: F811
    client, subject, *_ = api
    files = client.app.state.container.files
    first = client.get(f"/api/subjects/{subject.id}/pages/4/image")
    keys = files.list_keys("thumbnails/")
    assert len(keys) == 1
    again = client.get(f"/api/subjects/{subject.id}/pages/4/image")
    assert again.content == first.content
    assert files.list_keys("thumbnails/") == keys


def test_pages_of_a_subject_that_is_not_published_are_not_served(api):  # noqa: F811
    client, _subject, *_ = api
    draft = client.app.state.container.scope.subject_service.get_or_create("Draft", ["en"])
    assert client.get(f"/api/subjects/{draft.id}/pages/0/image").status_code == 403
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/subjects/{missing}/pages/0/image").status_code == 404
