import os

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
