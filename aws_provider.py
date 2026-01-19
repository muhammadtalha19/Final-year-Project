import boto3

# ------------------------
# AWS CONFIG
# ------------------------
REGION = "eu-north-1"
AMI_ID = "ami-0b46816ffa1234887"   # Amazon Linux 2023
INSTANCE_TYPE = "t3.micro"
KEY_NAME = "fyp-key-ec2"
SECURITY_GROUP_ID = "sg-0ea92d6a77e8c5f38"
SUBNET_ID = "subnet-0a6ba11302930d5a1"

ec2 = boto3.client("ec2", region_name=REGION)


def deploy_to_aws(container_image, container_port):
    """
    Launch EC2 and deploy a Docker container passed by orchestrator
    """

    print(">>> Launching EC2 on AWS")
    print(f">>> Container image: {container_image}")
    print(f">>> Container port: {container_port}")

    user_data = f"""#!/bin/bash
dnf update -y

# Install Docker
dnf install docker -y
systemctl start docker
systemctl enable docker

# Wait for Docker daemon
sleep 20

# Pull application image
docker pull {container_image}

# Run application container
docker run -d \\
  --name app_container \\
  -p 80:{container_port} \\
  --restart always \\
  {container_image}
"""

    response = ec2.run_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        SecurityGroupIds=[SECURITY_GROUP_ID],
        SubnetId=SUBNET_ID,
        UserData=user_data,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": "fyp-orchestrated-app"}
                ]
            }
        ]
    )

    instance_id = response["Instances"][0]["InstanceId"]
    print(f">>> EC2 instance launched: {instance_id}")

    print(">>> Waiting for instance to enter running state...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])

    desc = ec2.describe_instances(InstanceIds=[instance_id])
    public_ip = desc["Reservations"][0]["Instances"][0]["PublicIpAddress"]

    print(f">>> Application available at http://{public_ip}")
    return public_ip