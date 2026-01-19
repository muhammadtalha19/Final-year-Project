import boto3
import time

REGION = "eu-north-1"   # change if needed
AMI_ID = "ami-0b46816ffa1234887"  # Amazon Linux 2023 (CHANGE IF DIFFERENT)
INSTANCE_TYPE = "t3.micro"
KEY_NAME = "fyp-key-ec2"
SECURITY_GROUP_ID = "sg-0ea92d6a77e8c5f38"   # <-- put your SG ID here
SUBNET_ID = "subnet-0a6ba11302930d5a1"       # <-- put your subnet ID here

USER_DATA = """#!/bin/bash
dnf update -y
dnf install docker -y
systemctl start docker
systemctl enable docker
sleep 10
docker run -d -p 80:80 nginx
"""

ec2 = boto3.client("ec2", region_name=REGION)

def launch_instance():
    print("Launching EC2 instance...")

    response = ec2.run_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        SecurityGroupIds=[SECURITY_GROUP_ID],
        SubnetId=SUBNET_ID,
        UserData=USER_DATA,
        MinCount=1,
        MaxCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": "fyp-orchestrated-ec2"}
                ]
            }
        ]
    )

    instance_id = response["Instances"][0]["InstanceId"]
    print(f"Instance launched: {instance_id}")

    print("Waiting for instance to be running...")
    ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])

    desc = ec2.describe_instances(InstanceIds=[instance_id])
    public_ip = desc["Reservations"][0]["Instances"][0]["PublicIpAddress"]

    print(f"Instance is live at: http://{public_ip}")
    return public_ip


if __name__ == "__main__":
    launch_instance()
