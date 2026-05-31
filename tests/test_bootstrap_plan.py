from provider_bootstrap import generate_provider_bootstrap_plan


def test_aws_bootstrap_plan_contains_supported_subnet_steps():
    plan = generate_provider_bootstrap_plan("AWS")

    assert plan["provider"] == "AWS"
    assert any("describe-instance-type-offerings" in command for command in plan["commands"])
    assert any("port 80" in command for command in plan["commands"])


def test_azure_bootstrap_plan_contains_container_apps_setup():
    plan = generate_provider_bootstrap_plan("Azure")

    assert plan["provider"] == "Azure"
    assert any("Microsoft.App" in command for command in plan["commands"])
    assert any("containerapp env create" in command for command in plan["commands"])


def test_gcp_bootstrap_plan_contains_cloud_run_setup():
    plan = generate_provider_bootstrap_plan("GCP")

    assert plan["provider"] == "GCP"
    assert any("run.googleapis.com" in command for command in plan["commands"])
