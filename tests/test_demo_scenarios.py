import app as app_module


def _login():
    client = app_module.app.test_client()
    client.post("/register", data={"name": "Demo", "email": "demo@example.com", "password": "secret123"})
    return client


def test_demo_scenarios_requires_login():
    response = app_module.app.test_client().get("/demo-scenarios")

    assert response.status_code == 302


def test_demo_scenarios_renders_three_cards():
    response = _login().get("/demo-scenarios")

    assert response.status_code == 200
    assert b"Expense Tracker React" in response.data
    assert b"FastAPI Books API" in response.data
    assert b"FYP ML API" in response.data
    assert response.data.count(b"Use Template") == 3


def test_demo_scenario_use_template_link_prefills_deploy_form():
    client = _login()
    response = client.get("/deploy/new?template=ml-api")

    assert response.status_code == 200
    assert b"dockertalha19/fyp-ml-api:latest" in response.data
