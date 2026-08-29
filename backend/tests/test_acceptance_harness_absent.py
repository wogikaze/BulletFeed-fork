from fastapi.testclient import TestClient


def test_acceptance_harness_routes_are_absent_by_default(client: TestClient) -> None:
    response = client.get("/__acceptance__/claim-exposures", params={"userId": "usr_none"})
    assert response.status_code == 404
