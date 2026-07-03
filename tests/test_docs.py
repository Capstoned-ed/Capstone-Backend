from django.urls import reverse


def test_api_docs_swagger_ui_loads(client):
    url = reverse('swagger-ui')
    response = client.get(url)
    assert response.status_code == 200


def test_api_schema_loads(client):
    url = reverse('schema')
    response = client.get(url)
    assert response.status_code == 200

    