#  -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# Copyright 2020-2021 John Mille <john@compose-x.io>

"""
Main module to create x-alarms defined at the top level.
"""

import re
import warnings

from compose_x_common.compose_x_common import keyisset
from troposphere import AWS_REGION, AWS_STACK_ID, Join, Ref, Select, Split, Sub
from troposphere.cloudwatch import Alarm as CWAlarm
from troposphere.cloudwatch import CompositeAlarm

from ecs_composex.alarms.alarms_elbv2 import (
    handle_elbv2_dimension_mapping,
    handle_elbv2_target_group_dimensions,
)
from ecs_composex.alarms.alarms_params import RES_KEY
from ecs_composex.common import build_template, setup_logging
from ecs_composex.common.compose_resources import (
    XResource,
    set_lookup_resources,
    set_new_resources,
    set_resources,
    set_use_resources,
)
from ecs_composex.common.stacks import ComposeXStack
from ecs_composex.resources_import import import_record_properties

LOG = setup_logging()


def map_expression_to_alarms(expression, alarms):
    """
    Function to map the alarms in expression to  CFN alarms

    :param str expression:
    :param list alarms:
    :return: The composite alarm properties
    :rtype: dict
    """
    alarms_re = re.compile(r"ALARM([\S]+)|OK([\S]+)|INSUFFICIENT_DATA([\S]+)")
    alarms_declared = alarms_re.findall(expression)
    alarms_filtered = []
    for alarm in alarms_declared:
        for name in alarm:
            if name is not None and len(name):
                alarms_filtered.append(name.strip().replace("(", "").replace(")", ""))
    defined_alarms = [alarm for alarm in alarms if alarm.cfn_resource]
    alarms_mapping = {}
    for alarm_name in alarms_filtered:
        if keyisset(alarm_name, alarms_mapping):
            continue
        for alarm in defined_alarms:
            if alarm.name == alarm_name:
                alarms_mapping[alarm_name] = alarm.cfn_resource
                alarm.in_composite = True
    return alarms_mapping


def create_composite_alarm_expression(mapping, expression, alarms):
    """
    Function to create the composite alarms

    :param dict mapping:
    :param str expression:
    :param list alarms:
    :return:
    """
    rendered_bits = []
    func_re = re.compile(
        r"((?:\({1,})?(?:ALARM|OK|INSUFFICIENT_DATA))(?:\()([\S][^\(\)]+)(?:\))(\){1,})?"
    )
    for split in expression.split(" "):
        if func_re.match(split):
            groups = func_re.match(split).groups()
            func = groups[0]
            name = groups[1]
            closing = "" if not groups[2] else groups[2]
            if not keyisset(name, mapping):
                raise KeyError("There was no alarm identified to match name", name)
            alarm = mapping[name]
            rendered_bits.append(Sub(f"{func}(${{{alarm.title}}}){closing}"))
        else:
            rendered_bits.append(split.upper())
    rendered_expression = Join(" ", rendered_bits)
    return rendered_expression


def create_composite_alarm(alarm, alarms):
    """
    Function to create the composite alarms

    :param Alarm alarm:
    :param list alarms:
    :return:
    """
    if alarm.properties and keyisset("AlarmRule", alarm.properties):
        eval_expression = alarm.properties["AlarmRule"]
    elif alarm.parameters and keyisset("CompositeExpression", alarm.parameters):
        eval_expression = alarm.parameters["CompositeExpression"]
    else:
        raise KeyError(
            "Either Properties.AlarmRule or MacroParameters.CompositeExpression must be set",
            alarm.properties,
            alarm.parameters,
        )
    mapping = map_expression_to_alarms(eval_expression, alarms)
    composite_expression = create_composite_alarm_expression(
        mapping, eval_expression, alarms
    )
    stack_id = Select(4, Split("-", Select(2, Split("/", Ref(AWS_STACK_ID)))))
    alarm_name = f"${{{AWS_REGION}}}-${{StackId}}-CompositeAlarmFor" + "".join(
        [a.title for a in mapping.values()]
    )
    alarm_name = (
        alarm_name[: (254 - 12)] if len(alarm_name) > (254 - 12) else alarm_name
    )
    if alarm.properties:
        props = import_record_properties(alarm.properties, CompositeAlarm)
        props.update(
            {
                "AlarmRule": composite_expression,
                "AlarmName": Sub(alarm_name, StackId=stack_id),
            }
        )
    else:
        props = {
            "AlarmRule": composite_expression,
            "AlarmName": Sub(alarm_name, StackId=stack_id),
            "ActionsEnabled": True,
        }
    alarm.properties = props
    alarm.cfn_resource = CompositeAlarm(
        alarm.logical_name,
        DependsOn=[a.title for a in mapping.values()],
        **props,
    )


def add_composite_alarms(template, new_alarms):

    for alarm in new_alarms:
        if not alarm.cfn_resource and (
            (alarm.parameters and keyisset("CompositeExpression", alarm.parameters))
            or alarm.properties
        ):
            alarm.is_composite = True
            create_composite_alarm(alarm, new_alarms)
            if alarm.cfn_resource.title not in template.resources:
                template.add_resource(alarm.cfn_resource)


def create_alarms(template, settings, new_alarms):
    """
    Main function to create new alarms
    Rules out CompositeAlarms first, creates "Simple" alarms, and then link these to ComopsiteAlarms if so declared.

    """
    for alarm in new_alarms:
        if (
            alarm.properties
            and not alarm.parameters
            or (
                alarm.parameters
                and not keyisset("CompositeExpression", alarm.parameters)
            )
        ):
            try:
                import_record_properties(
                    alarm.properties,
                    CompositeAlarm,
                    ignore_missing_required=False,
                )
            except KeyError:
                props = import_record_properties(alarm.properties, CWAlarm)
                alarm.cfn_resource = CWAlarm(alarm.logical_name, **props)
                if alarm.cfn_resource.title not in template.resources:
                    template.add_resource(alarm.cfn_resource)
        elif alarm.parameters and keyisset("CompositeExpression", alarm.parameters):
            continue

    add_composite_alarms(template, new_alarms)


class Alarm(XResource):
    """
    Class to represent CW Alarms
    """

    topics_key = "Topics"

    def __init__(self, name, definition, module_name, settings, mapping_key=None):
        self.topics = []
        self.is_composite = False
        self.in_composite = False
        super().__init__(
            name, definition, module_name, settings, mapping_key=mapping_key
        )
        self.topics = (
            definition[self.topics_key]
            if keyisset(self.topics_key, self.definition)
            else []
        )


class XStack(ComposeXStack):
    """
    Class to represent the Rootstack for alarms
    """

    def __init__(self, name, settings, **kwargs):
        set_resources(settings, Alarm, RES_KEY)
        x_resources = settings.compose_content[RES_KEY].values()
        new_resources = set_new_resources(x_resources, RES_KEY, False)
        lookup_resources = set_lookup_resources(x_resources, RES_KEY)
        use_resources = set_use_resources(x_resources, RES_KEY, False)
        if new_resources:
            template = build_template("Root stack for Alarms created via Compose-X")
            super().__init__(name, stack_template=template, **kwargs)
            create_alarms(template, settings, new_resources)
            self.mark_nested_stacks()
        else:
            self.is_void = True
        if lookup_resources or use_resources:
            warnings.warn(
                f"{RES_KEY} - Lookup and Use are not supported. "
                "You can only create new resources"
            )

    def handle_dimensions(self, resource, root_stack, settings):
        """
        Handles the dimensions settings and tries to resolve

        :param Alarm resource:
        :param ecs_composex.common.stacks.ComposeXStacks root_stack:
        :param ecs_composex.common.settings.ComposeXSettings settings:
        """
        if not hasattr(resource.cfn_resource, "Dimensions"):
            print(f"{self.title} - {resource.name} - No Dimensions defined")
        dimensions = getattr(resource.cfn_resource, "Dimensions")
        namespace = resource.cfn_resource.Namespace
        if namespace == "AWS/ApplicationELB" or namespace == "AWS/NetworkELB":
            for dimension in dimensions:
                if dimension.Name == "LoadBalancer" and dimension.Value.startswith(
                    "x-elbv2::"
                ):
                    handle_elbv2_dimension_mapping(self, dimension, resource, settings)
                elif dimension.Name == "TargetGroup":
                    handle_elbv2_target_group_dimensions(
                        self, dimension, resource, settings
                    )

    def add_xdependencies(self, root_stack, settings):
        """
        Function to cross reference alarm settings with other resources

        :param ecs_composex.common.stacks.ComposeXStacks root_stack:
        :param ecs_composex.common.settings.ComposeXSettings settings:
        """
        x_resources = settings.compose_content[RES_KEY].values()
        new_resources = set_new_resources(x_resources, RES_KEY, False)
        for resource in new_resources:
            if isinstance(resource, Alarm) and isinstance(
                resource.cfn_resource, CompositeAlarm
            ):
                continue
            if not resource.cfn_resource:
                continue
            self.handle_dimensions(resource, root_stack, settings)
