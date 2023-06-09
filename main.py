import os
import sys
import logging
import pathlib
import json
import boto3
import typer
import commands

from configs import VpcConfig, SubnetConfig
from typer import Typer

app = Typer()
local_dir = pathlib.Path("./params").resolve()
local_dir.mkdir(exist_ok=True, parents=True)
formatter = logging.Formatter(
    fmt="%(asctime)s (%(funcName)s) : %(msg)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(stream_handler)
logger.setLevel(logging.INFO)


@app.command(
    name="configure-vpc",
    help="create a VPC in the configured region"
)
def configure_vpc(
        profile_name: str = typer.Option(..., help="name of AWS administrator profile"),
        region: str = typer.Option(..., help="name of AWS region to create VPC"),
        vpc_cidr: str = typer.Option(..., help="range of IP host addresses to define within VPC"),
        vpc_name: str = typer.Option(..., help="name of VPC"),
        sg_name: str = typer.Option(..., help="name of security group to attach to VPC"),
        igw_name: str = typer.Option(..., help="name of internet gateway to associate with VPC"),
):
    vpc_config = VpcConfig(
        region=region,
        vpc_cidr=vpc_cidr,
        vpc_name=vpc_name,
        sg_name=sg_name,
        igw_name=igw_name,
    )
    session = boto3.Session(profile_name=profile_name, region_name=vpc_config.region)
    ec2_client = session.client("ec2")

    logger.info(f"Create VPC '{vpc_name}'")
    vpc_id = commands.create_vpc(ec2_client, vpc_config)
    vpc_config.vpc_id = vpc_id

    logger.info(f"Create security group '{sg_name}' and open configured ports")
    sg_id = commands.create_vpc_security_group(ec2_client, vpc_config)
    vpc_config.sg_id = sg_id

    logger.info(f"Create internet gateway '{igw_name}' and attach it to VPC")
    igw_id = commands.create_internet_gateway(ec2_client, vpc_config)
    vpc_config.igw_id = igw_id

    vpc_config_file_name = _parse_config_file_name(vpc_name, "vpc")
    vpc_config_path = local_dir.joinpath(vpc_config_file_name)
    logger.info(f"Save VPC configuration file as {vpc_config_path}")
    with open(vpc_config_path, "w") as file:
        json.dump(vpc_config.__dict__, file)


@app.command(
    name="remove-vpc",
    help="remove predefined VPC"
)
def remove_vpc(
        profile_name: str = typer.Option(..., help="name of AWS administrator profile"),
        vpc_name: str = typer.Option(..., help="name of VPC to create subnet"),
):
    vpc_config_file_name = _parse_config_file_name(vpc_name, "vpc")
    vpc_config = _load_config(vpc_config_file_name)
    session = boto3.Session(profile_name=profile_name, region_name=vpc_config.region)
    ec2_client = session.client("ec2")

    logger.info(f"Detach internet gateway '{vpc_config.igw_name}' from VPC and delete it")
    commands.delete_internet_gateway(ec2_client, vpc_config)

    logger.info(f"Delete corresponding security group '{vpc_config.sg_name}'")
    commands.delete_security_group(ec2_client, vpc_config)

    logger.info(f"Delete VPC '{vpc_name}'")
    commands.delete_vpc(ec2_client, vpc_config)

    logger.info("Delete VPC configuration file")
    os.remove(local_dir.joinpath(vpc_config_file_name))


@app.command(
    name="configure-subnet",
    help="create a subnet within predefined VPC"
)
def configure_subnet(
        profile_name: str = typer.Option(..., help="name of AWS administrator profile"),
        vpc_name: str = typer.Option(..., help="name of VPC to create subnet"),
        subnet_name: str = typer.Option(..., help="name of subnet to create within VPC"),
        cidr_substitute: str = typer.Option(..., help="value to use as third octet(integer between 5 and 254)"),
        availability_zone_postfix: str = typer.Option(..., help="postfix to attach to region name"),
        route_table_name: str = typer.Option(..., help="name of route table to associate with subnet"),
        is_public: bool = typer.Option(..., help="whether created subnet is routed to internet gateway"),
):
    vpc_config_file_name = _parse_config_file_name(vpc_name, "vpc")
    vpc_config = _load_config(vpc_config_file_name)
    session = boto3.Session(profile_name=profile_name, region_name=vpc_config.region)
    ec2_client = session.client("ec2")
    subnet_config = SubnetConfig(
        vpc_config=vpc_config,
        subnet_name=subnet_name,
        cidr_substitute=cidr_substitute,
        az_postfix=availability_zone_postfix,
        rt_name=route_table_name,
    )

    logger.info(f"Create subnet '{subnet_name}'")
    subnet_id = commands.create_subnet(ec2_client, subnet_config)
    subnet_config.subnet_id = subnet_id

    logger.info(f"Create subnet route table '{route_table_name}'")
    rt_id = commands.create_route_table(ec2_client, subnet_config, is_public)
    subnet_config.rt_id = rt_id

    logger.info(f"Create association between '{subnet_name}' and '{route_table_name}'")
    association_id = commands.create_subnet_route_table_association(ec2_client, subnet_config)
    subnet_config.subnet_rt_association_id = association_id

    subnet_config_file_name = _parse_config_file_name(subnet_name, "subnet")
    subnet_config_path = local_dir.joinpath(subnet_config_file_name)
    logger.info(f"Save VPC configuration file as {subnet_config_path}")
    with open(subnet_config_path, "w") as file:
        json.dump(subnet_config.__dict__, file)


@app.command(
    name="remove-subnet",
    help="remove a subnet from a VPC"
)
def remove_subnet(
        profile_name: str = typer.Option(..., help="name of AWS administrator profile"),
        subnet_name: str = typer.Option(..., help="name of subnet to delete"),
):
    subnet_config_file_name = _parse_config_file_name(subnet_name, "subnet")
    subnet_config = _load_config(subnet_config_file_name)
    session = boto3.Session(profile_name=profile_name, region_name=subnet_config.region)
    ec2_client = session.client("ec2")

    logger.info(f"Delete association between '{subnet_name}' and '{subnet_config.rt_name}'")
    commands.delete_subnet_route_table_association(ec2_client, subnet_config)

    logger.info(f"Delete detached route table '{subnet_config.rt_name}'")
    commands.delete_route_table(ec2_client, subnet_config)

    logger.info(f"Delete subnet '{subnet_name}'")
    commands.delete_subnet(ec2_client, subnet_config)

    logger.info("Delete subnet configuration file")
    os.remove(local_dir.joinpath(subnet_config_file_name))


def _parse_config_file_name(resource_name: str, resource_type: str):
    return f"{resource_type.lower()}_{resource_name.replace('-', '_')}_config.json"


def _load_config(config_file_name: str):
    config_path = local_dir.joinpath(config_file_name)
    with open(config_path, "r") as file:
        config = json.load(file)
        if config_file_name.startswith("vpc"):
            return VpcConfig.from_config(config)
        elif config_file_name.startswith("subnet"):
            return SubnetConfig.from_config(config)


if __name__ == "__main__":
    app()
