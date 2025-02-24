#  -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# Copyright 2020-2021 John Mille <john@compose-x.io>

"""
Module to add permissions etc. for services to kinesis streams
"""

from compose_x_common.compose_x_common import keyisset

from ecs_composex.common import LOG
from ecs_composex.kinesis.kinesis_params import (
    MAPPINGS_KEY,
    RES_KEY,
    STREAM_ARN,
    STREAM_ID,
    STREAM_KMS_KEY_ID,
)
from ecs_composex.resource_settings import (
    handle_lookup_resource,
    handle_resource_to_services,
)


def kinesis_to_ecs(resources, services_stack, res_root_stack, settings):
    """
    Function to apply Kinesis settings to ECS Services
    :return:
    """
    new_resources = [
        resources[res_name]
        for res_name in resources
        if resources[res_name].cfn_resource
    ]
    lookup_resources = [
        resources[res_name] for res_name in resources if resources[res_name].mappings
    ]
    if new_resources and new_resources not in services_stack.DependsOn:
        services_stack.DependsOn.append(res_root_stack.title)
        LOG.info(f"Added dependency between services and {res_root_stack.title}")
    for new_res in new_resources:
        handle_resource_to_services(
            new_res,
            services_stack,
            res_root_stack,
            settings,
            STREAM_ARN,
            [STREAM_ID],
        )
    for lookup_res in lookup_resources:
        handle_lookup_resource(
            settings.mappings[RES_KEY],
            MAPPINGS_KEY,
            lookup_res,
            STREAM_ARN,
            [STREAM_ID],
        )
