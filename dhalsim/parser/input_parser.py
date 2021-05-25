import pandas as pd
import wntr
from antlr4 import *

from dhalsim.parser.antlr.controlsLexer import controlsLexer
from dhalsim.parser.antlr.controlsParser import controlsParser


class Error(Exception):
    """Base class for exceptions in this module."""


class NoInpFileGiven(Error):
    """Raised when tag you are looking for does not exist"""


def value_to_status(actuator_value):
    """
    Translates int corresponding to actuator status.

    :param actuator_value: The value from the status.value of the actuator
    :type actuator_value: int
    """
    if actuator_value == 0:
        return "closed"
    else:
        return "open"


class InputParser:
    """
    Class handling the parsing of .inp input files.

    :param intermediate_yaml: The intermediate yaml file
    """

    def __init__(self, intermediate_yaml):
        """Constructor method"""
        self.data = intermediate_yaml

        for plc in self.data['plcs']:
            if 'sensors' not in plc:
                plc['sensors'] = list()

            if 'actuators' not in plc:
                plc['actuators'] = list()

        # Get the INP file path
        if 'inp_file' in self.data.keys():
            self.inp_file_path = self.data['inp_file']
        else:
            raise NoInpFileGiven()
        # Read the inp file with WNTR
        self.wn = wntr.network.WaterNetworkModel(self.inp_file_path)

    def write(self):
        """
        Writes all needed inp file sections into the intermediate_yaml.
        """
        # Generate PLC controls
        self.generate_controls()
        # Generate list of actuators + initial values
        self.generate_actuators_list()
        # Generate list of times
        self.generate_times()
        # Generate initial values if batch mode is true
        if self.data["batch_mode"]:
            self.generate_initial_values()
        # Add iterations if not existing
        if "iterations" not in self.data.keys():
            self.data["iterations"] = int(self.data["time"][0]["duration"]
                                          / self.data["time"][1]["hydraulic_timestep"])

        # Return the YAML object
        return self.data

    def generate_controls(self):
        """
        Generates list of controls with their types, values, actuators, and
        potentially dependant; then adds that to self.data to be written to the yaml.
        """
        input = FileStream(self.inp_file_path)
        tree = controlsParser(CommonTokenStream(controlsLexer(input))).controls()

        controls = []
        for i in range(0, tree.getChildCount()):
            child = tree.getChild(i)
            # Get all common control values from the control
            actuator = str(child.getChild(1))
            action = str(child.getChild(2))
            if child.getChildCount() == 8:
                # This is an AT NODE control
                dependant = str(child.getChild(5))
                value = float(str(child.getChild(7)))
                controls.append({
                    "type": str(child.getChild(6)).lower(),
                    "dependant": dependant,
                    "value": value,
                    "actuator": actuator,
                    "action": action.lower()
                })
            if child.getChildCount() == 6:
                # This is a TIME control
                value = float(str(child.getChild(5)))
                controls.append({
                    "type": "time",
                    "value": int(value),
                    "actuator": actuator,
                    "action": action.lower()
                })

        for plc in self.data['plcs']:
            plc['controls'] = []
            actuators = plc['actuators']
            for control in controls:
                if control['actuator'] in actuators:
                    plc['controls'].append(control)

    def generate_times(self):
        """
        Generates duration and hydraulic timestep and adds to the
        data to be written to the yaml file.
        """

        # TODO Decide on the timestep (minutes or seconds?)
        times = [
            {"duration": self.wn.options.time.duration},
            {"hydraulic_timestep": self.wn.options.time.hydraulic_timestep}
        ]
        self.data['time'] = times

    def generate_actuators_list(self):
        """
        Generates list of actuators with their initial states
        and adds to the data to be written to the yaml file.
        """

        pumps = []
        for pump in self.wn.pumps():
            pumps.append({
                "name": pump[0],
                "initial_state": value_to_status(pump[1].status.value)
            })
        valves = []
        for valve in self.wn.valves():
            valves.append({
                "name": valve[0],
                "initial_state": value_to_status(valve[1].status.value)
            })
        # Append valves to pumps
        pumps.extend(valves)
        self.data['actuators'] = pumps

    def generate_initial_values(self):
        """Generates all tanks with their initial values if running in batch mode"""

        initial_values = {}
        initial_tank_levels = pd.read_csv(self.data["initial_values_path"])
        for index in range(len(initial_tank_levels.columns)):
            print(str(initial_tank_levels.columns[index]))
            initial_values[str(initial_tank_levels.columns[index])] = \
                float(initial_tank_levels.iloc[self.data["batch_index"], index])

        self.data['initial_values'] = initial_values
