# -*- coding: utf-8 -*-
#  ECS ComposeX <https://github.com/lambda-my-aws/ecs_composex>
#  Copyright (C) 2020-2021  John Mille <john@lambda-my-aws.io>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Main module generating the ECS Cluster template.

The root stack is to build the IAM Instance profile for the hosts that can be used for ASG or SpotFleet.
That way it is easy for anyone to deploy an instance in standalone if you wanted that.
"""

from troposphere import Ref, If, GetAtt

from ecs_composex.common import build_template
from ecs_composex.common import cfn_conditions
from ecs_composex.common.cfn_params import (
    ROOT_STACK_NAME,
    ROOT_STACK_NAME_T,
    USE_FLEET,
    USE_ONDEMAND,
)
from ecs_composex.common.config import ComputeConfig
from ecs_composex.common.stacks import ComposeXStack
from ecs_composex.compute import compute_params, compute_conditions
from ecs_composex.compute.hosts_template import add_hosts_resources
from ecs_composex.compute.spot_fleet import generate_spot_fleet_template
from ecs_composex.ecs.ecs_params import CLUSTER_NAME
from ecs_composex.vpc import vpc_params


def add_spotfleet_stack(template, settings, launch_template):
    """
    Function to build the spotfleet stack and add it to the Cluster parent template

    :param launch_template: the launch template
    :param troposphere.Template template: parent cluster template
    :param ComposeXSettings settings: The settings for execution

    """
    compute_config = ComputeConfig(settings)
    parameters = {
        ROOT_STACK_NAME_T: If(
            cfn_conditions.USE_STACK_NAME_CON_T,
            Ref("AWS::StackName"),
            Ref(ROOT_STACK_NAME),
        ),
        compute_params.LAUNCH_TEMPLATE_ID_T: Ref(launch_template),
        compute_params.LAUNCH_TEMPLATE_VersionNumber_T: GetAtt(
            launch_template, "LatestVersionNumber"
        ),
        compute_params.MAX_CAPACITY_T: Ref(compute_params.MAX_CAPACITY),
        compute_params.MIN_CAPACITY_T: Ref(compute_params.MIN_CAPACITY),
        compute_params.TARGET_CAPACITY_T: Ref(compute_params.TARGET_CAPACITY),
    }
    fleet_template = generate_spot_fleet_template(settings, compute_config.spot_config)
    template.add_resource(
        ComposeXStack(
            "SpotFleet",
            stack_template=fleet_template,
            Condition=cfn_conditions.USE_SPOT_CON_T,
            Parameters=parameters,
        )
    )


def generate_compute_template(settings):
    """
    Function that generates the Compute resources to run ECS services on top of EC2

    :param ComposeXSettings settings: The settings for executio
    :return: ECS Cluster Template
    :rtype: troposphere.Template
    """
    template = build_template(
        "Cluster template generated by ECS Compose X",
        [
            USE_FLEET,
            USE_ONDEMAND,
            compute_params.ECS_AMI_ID,
            compute_params.TARGET_CAPACITY,
            compute_params.MIN_CAPACITY,
            compute_params.MAX_CAPACITY,
            vpc_params.APP_SUBNETS,
            vpc_params.VPC_ID,
            CLUSTER_NAME,
        ],
    )
    template.add_condition(
        compute_conditions.MAX_IS_MIN_T, compute_conditions.MAX_IS_MIN
    )
    template.add_condition(cfn_conditions.USE_SPOT_CON_T, cfn_conditions.USE_SPOT_CON)
    launch_template = add_hosts_resources(template)
    add_spotfleet_stack(template, settings, launch_template)
    return template
