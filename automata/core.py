"""
Core definitions, basic structures.
"""
import automata.utils
import automata.simplemap
import automata.stats
from random import random
import math
import numpy as np

class Vehicle:
    """
    Vehicle objects move forward the cells measuring
    travelled distance in a single step.
    Static variables:
    V_MAX - maximum speed (km/h)
    SLOW - probability of braking
    FAST - probability of accelerating
    LIMIT - probability of matching with speed limit
    """
    V_MAX = automata.utils.CONFIG.AGENT_VMAX
    DRIVEOFF = automata.utils.CONFIG.AGENT_DRIVEOFF
    SLOW = automata.utils.CONFIG.AGENT_SLOW
    FAST = automata.utils.CONFIG.AGENT_FAST
    LIMIT = automata.utils.CONFIG.AGENT_LIMIT

    def __init__(self, v):
        self.lifetime = 0
        self.is_off = False
        self.v = max(v, 1)
        self.travelled = 1
        self.cell = None

    def randomize(self):
        "Change variables randomly"
        vmax = automata.utils.speed2vcell(self.V_MAX)
        if self.v > 1 and random() < self.SLOW:
            self.v -= 1
        elif self.v < vmax and random() < self.FAST:
            self.v += 1
        elif random() < self.LIMIT:
            target = min(self.cell.speed_lim, vmax)
            # Accelerate or match speed
            self.v = min(self.v + 1, target)
        self.v = max(self.v, 1)

    def step(self):
        "Move forward"
        self.randomize()
        self.lifetime += 1
        n = self.v
        self.travelled = 0
        while n > 0:
            n -= 1
            if self.cell.is_connected() and self.cell.forward.is_free():
                self.travelled += 1
                self.cell.set_vehicle(None)
                if type(self.cell) is EndPoint and self.travelled > 0 and random() < self.DRIVEOFF:
                    # Exit road
                    self.is_off = True
                    break
                else:
                    self.cell.forward.set_vehicle(self)
            else:
                # Cannot move
                self.v = max(self.travelled, 1)
                break

class Cell:
    """
    Road cell containing information about:
    - lanes
    - speed limit
    - coordinates
    - vehicles inside
    - adjacent cells - forward
    """
    TYPE = 'Cell'

    def __init__(self, coords, lanes=1, speed_lim=140.0):
        self.destination = None
        self.id = 0
        self.lanes = lanes
        self.speed_lim = automata.utils.speed2vcell(speed_lim)
        self.coords = np.array(coords)
        self.forward = None
        self.vehicles = 0

    def __eq__(self, other):
        if other is None:
            return False
        return (self.coords == other.coords).all()

    def __repr__(self):
        return '<{0} {1} free:{2}>'.format(self.TYPE, self.coords, self.is_free())

    def is_connected(self):
        "Checks if forward cell is set"
        return self.forward is not None

    def is_free(self):
        "Checks whether cell can accept another vehicle"
        return self.vehicles < self.lanes

    def append(self, cell):
        "Set adjacent cell on first None adjacent pointer"
        if self.forward is None:
            self.forward = cell
        else:
            self.forward.append(cell)

    def set_vehicle(self, vehicle):
        "Set pointers for cell and vehicle. None reduces counter."
        if vehicle is not None:
            self.vehicles += 1
            vehicle.cell = self
        else:
            if self.vehicles > 0:
                self.vehicles -= 1

    def copy(self):
        "Create Cell deep copy."
        cell = Cell(self.coords, self.lanes, self.speed_lim)
        cell.forward = self.forward
        cell.turn = self.turn
        cell.__class__ = self.__class__
        return cell

    @staticmethod
    def from_point(point):
        point.__class__ = Cell
        return point

class EndPoint(Cell):
    """
    Cell derived class that removes all vehicles that enter it.
    """
    TYPE = 'EndPoint'

    @staticmethod
    def from_cell(cell: Cell):
        cell.__class__ = EndPoint
        return cell

class SpawnPoint(Cell):
    """
    Cell derived class that populates itself with vehicles.
    Loads config SPAWN_RATE as default RATE.
    RATE - probability of spawning
    """
    TYPE = 'SpawnPoint'
    RATE = automata.utils.CONFIG.SPAWN_RATE

    def spawn(self):
        "Spawn a vehicle with a random chance. Returns spawned object."
        if self.is_free() and random() < self.RATE:
            vh = Vehicle(self.speed_lim)
            self.set_vehicle(vh)
            return vh
        return None

    @staticmethod
    def from_cell(cell: Cell):
        cell.__class__ = SpawnPoint
        return cell

class Cellular:
    """
    Simulation runner class.
    List of cells, list of agents and list of spawns.
    Loads config: RADIUS.
    """

    def __init__(self):
        self.iteration = 0
        self.agents = []
        self.array = []
        self.spawns = []
        self.ends = []

    def step(self, stats=None):
        """
        Perform simulation step. Call spawners and agents.
        stats - list of Stat objects
        """
        self.iteration += 1
        # Clear agents that do not exist on map
        self.agents = [x for x in self.agents if not x.is_off]
        # Simulate car movement
        for x in self.agents:
            x.step()
        # Traffic enters road
        for x in self.spawns:
            v = x.spawn()
            if v is not None:
                self.agents.append(v)
        # Log
        if stats is not None:
            for s in stats:
                s.append(self)

    def offset_lane(self, line, n):
        "Cells coordinates moved perpendicularly to create a new lane"
        # Estimate heading between first and last cell
        vec = line[-1] - line[0]
        heading = math.atan2(vec[1], vec[0]) + math.pi / 2
        # Offset vector
        vec = np.array([math.cos(heading), math.sin(heading)]) * automata.utils.CONFIG.RADIUS * n
        coords = line + np.ones(line.shape) * vec
        return coords
    
    def cells_fill(self, line, lanes=1, maxspd=140):
        "Evenly distribute cells along line coordinates"
        reg = []
        dec = 1
        for i in range(1,len(line)):
            vec = np.array(line[i]) - np.array(line[i-dec])
            n = int(round(np.linalg.norm(vec) / automata.utils.CONFIG.RADIUS))
            if n <= 0:
                # Cells are too close - try extending range
                dec += 1
            else:
                intercells = np.linspace(line[i-dec], line[i], num=n, endpoint=False)
                reg += [Cell(coords, lanes, maxspd) for coords in intercells]
                dec = 1
        for i in range(1,len(reg)):
            reg[i-1].append(reg[i])
        return reg

    def reindex(self):
        "Reindex array elements with id"
        for i in range(0,len(self.array)):
            self.array[i].id = i

    def resolve_destination(self, cells_dict):
        "Connect cells that match start with destination"
        directions = list(cells_dict.keys())
        for k in directions:
            # Save to destination
            for c in cells_dict[k]:
                c.destination = k
            # Link End to next Spawn
            match = None
            for x in directions:
                if x[0] == k[1]:
                    match = x
                    break
            if match is not None:
                cells_dict[k][-1].append(cells_dict[match][0])
        return cells_dict

    def build(self, data:automata.simplemap.SM):
        "Construct cellular grid from SM object"
        clockwise = {}
        anticlock = {}
        for road in data.roads:
            # Clockwise road
            r = road.clockwise()
            cw = self.cells_fill(r.points, lanes=r.lanes, maxspd=r.maxspeed)
            cw[0] = SpawnPoint.from_cell(cw[0])
            cw[-1] = EndPoint.from_cell(cw[-1])
            clockwise.update({r.destination: cw})
            # Anticlockwise road
            r = road.anticlockwise()
            offset = self.offset_lane(r.points, -5)
            acw = self.cells_fill(offset, lanes=r.lanes, maxspd=r.maxspeed)
            acw[0] = SpawnPoint.from_cell(acw[0])
            acw[-1] = EndPoint.from_cell(acw[-1])
            anticlock.update({r.destination: acw})
        # Connect roads basing on destination
        clockwise = self.resolve_destination(clockwise)
        anticlock = self.resolve_destination(anticlock)
        # To array
        self.array = []
        for k in clockwise:
            self.array += clockwise[k]
        for k in anticlock:
            self.array += anticlock[k]
        # Hurray, retrieve points and reindex array
        self.spawns = [x for x in self.array if type(x) is SpawnPoint]
        self.ends = [x for x in self.array if type(x) is EndPoint]
        self.reindex()
        