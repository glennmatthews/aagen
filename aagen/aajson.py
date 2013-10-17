# JSON encoding/decoding for AAGen

from json import JSONEncoder
from .map import SortedSet, DungeonMap, Region, Connection, Decoration
from .direction import Direction
import aagen.geometry

class MapEncoder(JSONEncoder):
    def default(self, obj):
        """Convert AAGen object instances to JSON-encodable data.
        """
        if isinstance(obj, SortedSet):
            return list(obj)
        elif isinstance(obj, DungeonMap):
            return {
                '__type__': 'DungeonMap',
                'regions': obj.regions,
                'connections': obj.connections,
                'decorations': obj.decorations
            }
        elif isinstance(obj, Region):
            return {
                '__type__': 'Region',
                'kind': obj.kind,
                'polygon': obj.polygon
            }
        elif isinstance(obj, Connection):
            return {
                '__type__': 'Connection',
                'kind': obj.kind,
                'line': obj.line,
                'grow_direction': obj.grow_direction
            }
        elif isinstance(obj, Decoration):
            return {
                '__type__': 'Decoration',
                'kind': obj.kind,
                'polygon': obj.polygon,
                'orientation': obj.orientation
            }
        elif isinstance(obj, Direction):
            return obj.name
        elif hasattr(obj, 'geom_type'):
            return aagen.geometry.to_string(obj)
        # Default case:
        return JSONEncoder.default(self, obj)


def map_from_dict(obj):
    """Convert a dict (as read by JSON) into the corresponding
    AAGen object instance.
    """
    if not '__type__' in obj:
        return obj
    if obj['__type__'] == 'Region':
        return Region(obj['kind'], aagen.geometry.from_string(obj['polygon']))
    elif obj['__type__'] == 'Connection':
        return Connection(obj['kind'],
                          aagen.geometry.from_string(obj['line']),
                          grow_dir=Direction(obj['grow_direction']))
    elif obj['__type__'] == 'Decoration':
        return Decoration(obj['kind'],
                          aagen.geometry.from_string(obj['polygon']),
                          Direction(obj['orientation']))
    elif obj['__type__'] == 'DungeonMap':
        dungeon_map = DungeonMap()
        for reg in obj['regions']:
            dungeon_map.add_region(reg)
        for conn in obj['connections']:
            dungeon_map.add_connection(conn)
        for dec in obj['decorations']:
            dungeon_map.add_decoration(dec)
        return dungeon_map
    return obj
