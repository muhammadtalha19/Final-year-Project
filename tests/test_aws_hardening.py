import yaml
import pytest

from config_schema import validate_config
from providers.aws_provider import AWSProvider, _service_endpoints


class FakeEC2:
    def __init__(self, supported_azs):
        self.supported_azs = set(supported_azs)
        self.subnets = {
            "subnet-configured": {"SubnetId": "subnet-configured", "AvailabilityZone": "us-east-1a"},
            "subnet-fallback": {"SubnetId": "subnet-fallback", "AvailabilityZone": "us-east-1b"},
        }

    def describe_subnets(self, SubnetIds=None, Filters=None):
        if SubnetIds:
            return {"Subnets": [self.subnets[SubnetIds[0]]]}
        return {"Subnets": [self.subnets["subnet-fallback"]]}

    def describe_vpcs(self, Filters=None):
        return {"Vpcs": [{"VpcId": "vpc-default"}]}

    def describe_instance_type_offerings(self, LocationType, Filters):
        az = next(item["Values"][0] for item in Filters if item["Name"] == "location")
        return {"InstanceTypeOfferings": [{"Location": az}]} if az in self.supported_azs else {"InstanceTypeOfferings": []}


def _config(port=8000):
    return validate_config(
        yaml.safe_load(
            f"""
            app:
              name: aws-hardening
              environment: production
            selection:
              mode: manual
              provider: AWS
            deployment:
              type: container
              image: dockertalha19/fyp-ml-api:latest
              port: {port}
            requirements:
              max_monthly_cost_usd: 30
              min_uptime_percent: 99.9
              preferred_region: asia
              public_access: true
            """
        )
    )


def test_supported_configured_subnet_is_selected(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SUBNET_ID", "subnet-configured")
    provider = AWSProvider()

    assert provider._select_supported_subnet(FakeEC2({"us-east-1a"})) == "subnet-configured"


def test_unsupported_configured_subnet_falls_back_to_default_vpc(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SUBNET_ID", "subnet-configured")
    provider = AWSProvider()

    assert provider._select_supported_subnet(FakeEC2({"us-east-1b"})) == "subnet-fallback"


def test_no_supported_subnet_has_clear_error(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SUBNET_ID", "subnet-configured")
    provider = AWSProvider()

    with pytest.raises(RuntimeError) as exc_info:
        provider._select_supported_subnet(FakeEC2(set()))

    assert "No subnet" in str(exc_info.value)
    assert "AWS_INSTANCE_TYPE" in str(exc_info.value)


def test_aws_plan_maps_public_host_port_80_to_container_port(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    provider = AWSProvider()

    plan = provider.generate_plan(_config(port=8000))
    user_data = provider._build_user_data(_config(port=8000)["services"])

    assert "-p 80:8000" in plan["generated_commands"][0]["command_string"]
    assert "-p 80:8000" in user_data
    assert plan["port"] == 8000


def test_aws_public_endpoint_uses_root_http_url():
    endpoints = _service_endpoints("203.0.113.10", _config(port=8000)["services"])

    assert endpoints == [
        {
            "name": "web",
            "url": "http://203.0.113.10",
            "port": 80,
            "container_port": 8000,
        }
    ]
