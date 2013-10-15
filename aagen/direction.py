#!/usr/bin/env python
# Direction - a simple class representing a vector

import math
import logging

log = logging.getLogger(__name__)

class Direction:
    """Model class representing a compass direction (orthogonal or diagonal)
    in the dungeon."""

    N = "north"
    NW = "northwest"
    W = "west"
    SW = "southwest"
    S = "south"
    SE = "southeast"
    E = "east"
    NE = "northeast"

    diag_len = math.sqrt(2) / 2

    name_to_vector = {
        N: (0, 1),
        NW: (-diag_len, diag_len),
        W: (-1, 0),
        SW: (-diag_len, -diag_len),
        S: (0, -1),
        SE: (diag_len, -diag_len),
        E: (1, 0),
        NE: (diag_len, diag_len)
    }

    @classmethod
    def CARDINAL(cls):
        return [Direction(cls.N), Direction(cls.W),
                Direction(cls.S), Direction(cls.E)]


    def __init__(self, name=None, vector=None, baseline=None, degrees=None):
        """Construct a Direction from one of the following:
        - a name such as "north"
        - a direction vector such as (0, 1) (north)
        - a baseline to construct a direction normal to
        - an angle in degrees (with 0 being East)
        """
        if name is not None:
            self.name = name
            self.vector = self.name_to_vector[name]
            self.degrees = math.degrees(math.atan2(self.vector[1],
                                                   self.vector[0]))
        elif vector is not None:
            (x, y) = vector
            factor = math.sqrt(x ** 2 + y ** 2)
            degrees = math.degrees(math.atan2(y / factor, x / factor))
            return self.__init__(degrees=degrees)
        elif baseline is not None:
            if hasattr(baseline, 'coords'):
                baseline = baseline.coords
            (x0, y0) = baseline[0]
            (x1, y1) = baseline[-1]
            return self.__init__(vector=(y1 - y0, x0 - x1))
        elif degrees is not None:
            # Snap to grid
            self.degrees = round(degrees/45, 0) * 45
            radians = math.radians(self.degrees)
            (x, y) = (math.cos(radians), math.sin(radians))
            if math.fabs(x) < 0.0001:
                x = 0
            if math.fabs(y) < 0.0001:
                y = 0
            self.vector = (x, y)
            name = ""
            if y > 0:
                name += "north"
            elif y < 0:
                name += "south"
            if x > 0:
                name += "east"
            elif x < 0:
                name += "west"
            self.name = name
        else:
            raise RuntimeError("Must specify a value!")

        log.debug("Constructed {0}".format(self))


    def __getitem__(self, index):
        return self.vector[index]


    def __repr__(self):
        return("<Direction: {name}>" #({angle}, {vector})>"
               .format(name=self.name, angle=self.degrees, vector=self.vector))


    def rotate(self, degrees):
        """Construct a new Direction relative to this one"""
        return Direction(degrees=(self.degrees + degrees))


    def angle_from(self, other):
        """Magnitute of the angle between two Directions"""
        angle = math.fabs(self.degrees - other.degrees)
        if angle > 180:
            angle = 360 - angle
        log.debug("Angle from {0} to {1} is {2}".format(self, other, angle))
        return angle


    def is_cardinal(self):
        return (self.vector[0] == 0 or self.vector[1] == 0)
