import argparse
import os.path

from basePLC import BasePLC
from datetime import datetime
from decimal import Decimal
import time
import threading
import sys
import yaml
from pathlib import Path
from control import AboveControl, BelowControl, TimeControl


class Error(Exception):
    """Base class for exceptions in this module."""


class TagDoesNotExist(Error):
    """Raised when tag you are looking for does not exist"""


class InvalidControlValue(Error):
    """Raised when tag you are looking for does not exist"""


# plc1_log_path = 'plc1.log'
# todo: make intermediate yaml location not hardcoded


def generate_real_tags(sensors, dependants, actuators):
    real_tags = []

    for sensor_tag in sensors:
        if sensor_tag != "":
            real_tags.append((sensor_tag, 1, 'REAL'))
    for dependant_tag in dependants:
        if dependant_tag != "":
            real_tags.append((dependant_tag, 1, 'REAL'))
    for actuator_tag in actuators:
        if actuator_tag != "":
            real_tags.append((actuator_tag, 1, 'REAL'))

    return tuple(real_tags)


def generate_tags(taggable):
    tags = []

    if taggable:
        for tag in taggable:
            if tag and tag != "":
                tags.append((tag, 1))

    return tags


def create_controls(controls_list):
    ret = []
    for control in controls_list:
        if control["type"] == "Above":
            ret.append(AboveControl(control["actuator"], control["action"], control["dependant"], control["value"]))
        if control["type"] == "Below":
            ret.append(BelowControl(control["actuator"], control["action"], control["dependant"], control["value"]))
        if control["type"] == "Time":
            ret.append(TimeControl(control["actuator"], control["action"], control["value"]))

    return ret


class GenericPLC(BasePLC):

    def __init__(self, intermediate_yaml_path, yaml_index):
        self.yaml_index = yaml_index
        self.local_time = 0

        with intermediate_yaml_path.open() as yaml_file:
            self.intermediate_yaml = yaml.load(yaml_file, Loader=yaml.FullLoader)

        self.intermediate_plc = self.intermediate_yaml["plcs"][self.yaml_index]

        self.intermediate_controls = self.intermediate_plc['controls']

        self.controls = create_controls(self.intermediate_controls)

        # Create state from db values
        state = {
            'name': self.intermediate_yaml['db_name'],
            'path': self.intermediate_yaml['db_path']
        }

        # Create list of dependant sensors
        dependant_sensors = []
        for control in self.intermediate_controls:
            if control["type"] != "Time":
                dependant_sensors.append(control["dependant"])

        # Create list of PLC sensors
        plc_sensors = self.intermediate_plc['sensors']

        # Create server, real tags are generated
        plc_server = {
            'address': self.intermediate_plc['ip'],
            'tags': generate_real_tags(plc_sensors,
                                       list(set(dependant_sensors) - set(plc_sensors)),
                                       self.intermediate_plc['actuators'])
        }

        # Create protocol
        plc_protocol = {
            'name': 'enip',
            'mode': 1,
            'server': plc_server
        }

        print "DEBUG INIT: " + self.intermediate_plc['name']
        print "state = " + str(state)
        print "plc_protocol = " + str(plc_protocol)

        super(GenericPLC, self).__init__(name=self.intermediate_plc['name'],
                                         state=state, protocol=plc_protocol)

    def pre_loop(self):
        print 'DEBUG: ' + self.intermediate_plc['name'] + ' enters pre_loop'

        reader = True

        sensors = generate_tags(self.intermediate_plc['sensors'])
        actuators = generate_tags(self.intermediate_plc['actuators'])

        values = []
        for tag in sensors:
            values.append(Decimal(self.get(tag)))
        for tag in actuators:
            values.append(int(self.get(tag)))

        lock = threading.Lock()

        sensors.extend(actuators)

        BasePLC.set_parameters(self, sensors, values, reader, lock,
                               self.intermediate_plc['ip'])
        self.startup()

    def get_tag(self, tag):
        if tag in self.intermediate_plc["sensors"] or tag in self.intermediate_plc["actuators"]:
            return self.get((tag, 1))

        for i, plc_data in enumerate(self.intermediate_yaml["plcs"]):
            if i == self.index:
                continue
            if tag in plc_data[i]["sensors"] or tag in plc_data[i]["actuators"]:
                return self.receive((tag, 1), plc_data[i]["ip"])
                # return -1
        raise TagDoesNotExist(tag)

    def set_tag(self, tag, value):
        if isinstance(value, basestring) and value.lower() == "closed":
            value = 0
        elif isinstance(value, basestring) and value.lower() == "open":
            value = 1
        else:
            raise InvalidControlValue(value)

        self.set((tag, 1), value)
        pass

    # todo: get an actual master clock from the DB
    def get_master_clock(self):
        return self.local_time

    def main_loop(self):
        print('DEBUG: ' + self.intermediate_plc['name'] + ' enters main_loop')
        while True:
            try:
                self.local_time += 1

                for control in self.controls:
                    control.apply(self)

                time.sleep(0.25)

            except Exception:
                continue


def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error(arg + " does not exist")
    else:
        return arg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Start everything for a plc')
    parser.add_argument(dest="intermediate_yaml",
                        help="intermediate yaml file", metavar="FILE",
                        type=lambda x: is_valid_file(parser, x))
    parser.add_argument(dest="index", help="Index of PLC in intermediate yaml", type=int, metavar="N")

    args = parser.parse_args()

    plc = GenericPLC(
        intermediate_yaml_path=Path(args.intermediate_yaml),
        yaml_index=args.index)
