#! usr/bin/env python
import random
from collections import OrderedDict

# Custom imports
import GlobalConstants as GC
import configuration as cf
import CustomObjects, StateMachine, Dialogue, AStar, Support, Engine
import StatusObject, UnitObject, SaveLoad, InputManager, ItemMethods

import logging
logger = logging.getLogger(__name__)

class GameStateObj(object):
    # needed for main menu
    def __init__(self):
        self.counters = {}
        self.counters['level'] = 0
        # Set up blitting surfaces
        self.generic_surf = Engine.create_surface((GC.WINWIDTH, GC.WINHEIGHT))
        # Build starting stateMachine
        self.stateMachine = StateMachine.StateMachine(['start_start'], [])
        self.input_manager = InputManager.InputManager()
        # Menu slots
        self.activeMenu = None
        self.childMenu = None
        self.background = None
        # Surface holder
        self.info_surf = None
        # playtime
        self.playtime = 0
        # mode options
        self.mode = self.default_mode()

    # Things that change between levels always
    def start(self, allreinforcements, prefabs, objective):
        logger.info("Start")
        self.allreinforcements = allreinforcements
        self.prefabs = prefabs
        self.objective = objective
        self.turncount = 0

        self.generic()

    def start_map(self, tilemap):
        self.map = tilemap

        # Set up blitting surface
        mapSurfWidth = self.map.width * GC.TILEWIDTH
        mapSurfHeight = self.map.height * GC.TILEHEIGHT
        self.mapSurf = Engine.create_surface((mapSurfWidth, mapSurfHeight))

        self.grid_manager = AStar.Grid_Manager(self.map)
        self.boundary_manager = CustomObjects.BoundaryManager(self.map)

    # Start a new game
    def build_new(self):
        logger.info("Build New")
        self.allunits = []
        self.groups = {}
        self.allreinforcements = {}
        self.prefabs = []
        self.objective = None
        self.map = None
        self.counters = {}
        self.counters['level'] = 0
        self.convoy = []
        self.counters['money'] = 0
        self.play_time = 0
        self.game_constants = []
        self.support = Support.Support_Graph('Data/support_nodes.txt', 'Data/support_edges.txt') if cf.CONSTANTS['support'] else None
        self.modify_stats = cf.read_growths_file()
        self.unlocked_lore = []
        self.statistics = []
        self.market_items = set()

        self.sweep()
        self.generic()

    def default_mode(self):
        return {'difficulty': 1,
                'death': cf.CONSTANTS['death'], # 0 is Casual, 1 is Classic
                'growths': cf.CONSTANTS['growths']} # 0 is Random, 1 is Fixed, 2 is Hybrid

    def sweep(self):
        # None of these are kept through different levels
        self.event_triggers = []
        self.metaDataObj_changes = []
        self.talk_options = []
        self.base_conversations = OrderedDict()
        self.message = []
        self.turncount = 0

    def display_all_units(self):
        for unit in self.allunits:
            print(unit.name, unit.event_id, unit.position)

    def load(self, load_info):
        logger.info("Load")
        # Rebuild gameStateObj
        self.allunits = [UnitObject.UnitObject(info) for info in load_info['allunits']]
        self.groups = load_info['groups'] if 'groups' in load_info else {}
        self.allreinforcements = load_info['allreinforcements'] 
        self.prefabs = load_info['prefabs']
        map_info = load_info['map']
        self.playtime = load_info['playtime']
        self.convoy = [ItemMethods.deserialize(item_dict) for item_dict in load_info['convoy']]
        self.convoy = [item for item in self.convoy if item]
        self.turncount = load_info['turncount']
        self.game_constants = load_info['game_constants']
        self.objective = CustomObjects.Objective.deserialize(load_info['objective']) if isinstance(load_info['objective'], tuple) else load_info['objective']
        support_dict = load_info['support']
        self.event_triggers = load_info['event_triggers']
        self.metaDataObj_changes = load_info.get('metaDataObj_changes', [])
        self.talk_options = load_info['talk_options']
        self.base_conversations = load_info['base_conversations']
        self.stateMachine = StateMachine.StateMachine(load_info['state_list'][0], load_info['state_list'][1])
        self.statistics = load_info['statistics']
        self.message = [Dialogue.Dialogue_Scene(scene) for scene in load_info['message']]
        self.modify_stats = load_info.get('modify_stats', cf.read_growths_file())
        self.unlocked_lore = load_info['unlocked_lore']
        self.counters = load_info['counters']
        self.market_items = load_info.get('market_items', set())
        self.mode = load_info.get('mode', self.default_mode())

        # Map
        self.map = SaveLoad.create_map('Data/Level' + str(self.counters['level']))
        if map_info:
            self.map.replay_commands(map_info['command_list'], self.counters['level'])
            self.map.command_list = map_info['command_list']
            for position, current_hp in map_info['HP']:
                self.map.tiles[position].set_hp(current_hp)

        # Statuses
        for index, info in enumerate(load_info['allunits']):
            for s_dict in info['status_effects']:
                if isinstance(s_dict, dict):
                    StatusObject.deserialize(s_dict, self.allunits[index], self)
                else:
                    self.allunits[index].status_effects.append(s_dict)

        # Support
        if cf.CONSTANTS['support']:
            self.support = Support.Support_Graph('Data/support_nodes.txt', 'Data/support_edges.txt')
            self.support.deserialize(support_dict)
        else:
            self.support = None

        # Set up blitting surface
        if self.map:
            mapSurfWidth = self.map.width * GC.TILEWIDTH
            mapSurfHeight = self.map.height * GC.TILEHEIGHT
            self.mapSurf = Engine.create_surface((mapSurfWidth, mapSurfHeight))

            self.grid_manager = AStar.Grid_Manager(self.map)
            self.boundary_manager = CustomObjects.BoundaryManager(self.map)

            for unit in self.allunits:
                if unit.position:
                    self.grid_manager.set_unit_node(unit.position, unit)

        self.generic()
        if 'phase_info' in load_info:
            self.phase.current, self.phase.previous = load_info['phase_info']

    def generic(self):
        logger.info("Generic")
        lord_units = [unit for unit in self.allunits if unit.position and 'Lord' in unit.tags and unit.team == 'player']
        lord_position = lord_units[0].position if lord_units else (0, 0)
        # Certain variables change if this is being initialized at beginning of game, and not a save state
        self.phase = CustomObjects.Phase(self)
        self.statedict = {'previous_cursor_position': lord_position,
                          'levelIsComplete': False, # Whether the level is complete
                          'outroScriptDone': False} # Whether the outro script has been played
        # For hiding menus
        self.hidden_active = None
        self.hidden_child = None
        self.main_menu = None
        # Combat slots
        self.combatInstance = None
        self.levelUpScreen = []
        # Banner slots
        self.banners = []
        # Status slots
        self.status = None
        # AI slots
        self.ai_current_unit = None
        self.ai_unit_list = None
        self.ai_build_flag = True
        # Movement manager
        self.moving_units = set()

        # Handle cursor
        if any(unit.team == 'player' and unit.position for unit in self.allunits):
            # cursor_position = [unit.position for unit in self.allunits if unit.team == 'player' and unit.position][0]
            cursor_position = lord_position
        else:
            cursor_position = (0, 0)
        self.cursor = CustomObjects.Cursor('Cursor', cursor_position)
        self.fake_cursors = []
        self.tutorial_mode = False

        # Handle cameraOffset
        # Track how much camera has moved in pixels:
        self.cameraOffset = CustomObjects.CameraOffset(self.cursor.position[0], self.cursor.position[1])
        self.cursor.autocursor(self, force=True)
        # Other slots
        self.highlight_manager = CustomObjects.HighlightController()
        self.allarrows = []
        self.allanimations = []

        # Reset the units updates on load
        # And have the units arrive on map
        for unit in self.allunits:
            unit.resetUpdates()
            if unit.position:
                unit.place_on_map(self)
                unit.arrive(self, serializing=False)

        self.info_menu_struct = {'current_state': 0,
                                 'scroll_units': [],
                                 'one_unit_only': False,
                                 'chosen_unit': None}

    def get_total_party_members(self):
        num_members = sum([1 for unit in self.allunits if unit.team == 'player' and not unit.dead and not unit.generic_flag])
        return num_members

    def check_dead(self, name):
        return any(unit.name == name and unit.dead for unit in self.allunits)

    def check_alive(self, name):
        return any(unit.name == name and not unit.dead for unit in self.allunits)

    def get_unit_from_id(self, u_id):
        if isinstance(u_id, set):
            return {unit for unit in self.allunits if unit.id in u_id}
        else:
            for unit in self.allunits:
                if unit.id == u_id:
                    return unit

    def get_unit_from_pos(self, pos):
        if isinstance(pos, set):
            return {unit for unit in self.allunits if unit.position in pos}
        else:
            for unit in self.allunits:
                if unit.position == pos:
                    return unit

    def get_unit_from_name(self, name):
        if isinstance(name, set):
            return {unit for unit in self.allunits if unit.name in name}
        else:
            for unit in self.allunits:
                if unit.name == name:
                    return unit

    def get_unit(self, any_id):
        if isinstance(any_id, set):
            return {unit for unit in self.allunits if unit.name in any_id or unit.id in any_id or unit.event_id in any_id}
        else:
            for unit in self.allunits:
                if any_id in [unit.name, unit.id, unit.event_id]:
                    return unit

    def check_formation_spots(self):
        # Returns None if no spot available
        # Returns a spot if a spot is available
        list_of_spots = [position for position, value in self.map.tile_info_dict.iteritems() if 'Formation' in value]
        list_of_unit_positions = [unit.position for unit in self.allunits if unit.team == 'player']
        for position in list_of_spots:
            if position not in list_of_unit_positions:
                return position
        return None

    def set_camera_limits(self):
        # Set limits on cameraOffset
        if self.cameraOffset.x < 0:
            self.cameraOffset.set_x(0)
        if self.cameraOffset.y < 0:
            self.cameraOffset.set_y(0)
        if self.cameraOffset.x > (self.map.width - GC.WINWIDTH/GC.TILEWIDTH): # Need this minus to account for size of screen
            self.cameraOffset.set_x(self.map.width - GC.WINWIDTH/GC.TILEWIDTH)
        if self.cameraOffset.y > (self.map.height - GC.WINHEIGHT/GC.TILEHEIGHT):
            self.cameraOffset.set_y(self.map.height - GC.WINHEIGHT/GC.TILEHEIGHT)

    def remove_fake_cursors(self):
        self.fake_cursors = []

    def tutorial_mode_off(self):
        self.remove_fake_cursors()
        self.tutorial_mode = False

    def removeSprites(self):
        # Decouple sprites
        for unit in self.allunits:
            unit.sweep()
            for item in unit.items:
                item.removeSprites()
            for status in unit.status_effects:
                status.removeSprites()
        # if self.map:
        #    self.map.removeSprites() I don't think this is actually necessary..., since we save a serialized version of the map now
        if self.objective:
            self.objective.removeSprites()
        for item in self.convoy:
            item.removeSprites()

    def save(self):
        # Reset all position dependant voodoo -- Done by gameStateObj at once instead of one at a time...
        for unit in self.allunits:
            unit.leave(self, serializing=True)
        ser_units = [unit.serialize(self) for unit in self.allunits if not (unit.dead and unit.generic_flag)]
        for unit in self.allunits:
            unit.arrive(self, serializing=True)
        to_save = {'allunits': ser_units,
                   'groups': self.groups,
                   'allreinforcements': self.allreinforcements,
                   'prefabs': self.prefabs,
                   'map': self.map.serialize() if self.map else None,
                   'playtime': self.playtime,
                   'turncount': self.turncount,
                   'convoy': [item.serialize() for item in self.convoy],
                   'objective': self.objective.serialize() if self.objective else None,
                   'support': self.support.serialize() if self.support else None,
                   'game_constants': self.game_constants,
                   'metaDataObj_changes': self.metaDataObj_changes,
                   'event_triggers': self.event_triggers,
                   'unlocked_lore': self.unlocked_lore,
                   'counters': self.counters,
                   'talk_options': self.talk_options,
                   'base_conversations': self.base_conversations,
                   'state_list': self.stateMachine.serialize(),
                   'statistics': self.statistics,
                   'modify_stats': self.modify_stats,
                   'market_items': self.market_items,
                   'mode': self.mode,
                   'message': [message.serialize() for message in self.message],
                   'phase_info': (self.phase.current, self.phase.previous)}
        import time
        to_save_meta = {'playtime': self.playtime,
                        'realtime': time.time()}
        return to_save, to_save_meta

    def loadSprites(self):
        # Reload sprites
        for unit in self.allunits:
            unit.resetUpdates()
            unit.loadSprites()
            for item in unit.items:
                item.loadSprites()
            for status in unit.status_effects:
                status.loadSprites()
        if self.map:
            self.map.loadSprites()
        for item in self.convoy:
            item.loadSprites()

    def clean_up(self):
        # Units should leave (first, because clean_up removes position)
        for unit in self.allunits:
            unit.leave(self)
            unit.remove_from_map(self)
        for unit in self.allunits:
            unit.clean_up(self)

        # Remove non player team units
        for unit in reversed(self.allunits):
            if unit.team != 'player' or unit.generic_flag:
                self.allunits.remove(unit)

        # Handle player death
        for unit in reversed(self.allunits):
            if unit.dead:
                if not self.mode['death']: # Casual
                    unit.dead = False
                else:
                    for item in unit.items:
                        unit.remove_item(item)
                        if not item.locked:
                            item.owner = 0
                            self.convoy.append(item)

        # Remove unnecessary information between levels
        self.sweep()
        self.map = None
        self.groups = {}
        self.allreinforcements = {}
        self.prefabs = []
        self.objective = None

    def compare_teams(self, team1, team2):
        # Returns True if allies, False if enemies
        if team1 == team2:
            return True
        elif (team1 == 'player' and team2 == 'other') or (team2 == 'player' and team1 == 'other'):
            return True
        return False

    # Should only be called when moving to next level
    def update_statistics(self, metaDataObj):
        self.statistics.append(CustomObjects.LevelStatistic(self, metaDataObj))
        for unit in self.allunits:
            unit.records = unit.default_records()

    def restock_convoy(self):
        items_with_uses = sorted((item for item in self.convoy if item.uses), key=lambda item: item.id)
        # Actually restock
        current_item = items_with_uses[0]
        for item in items_with_uses[1:]:
            if item.id == current_item.id:
                diff_needed = current_item.uses.total_uses - current_item.uses.uses
                if diff_needed > 0:
                    if item.uses.uses >= diff_needed:
                        item.uses.uses -= diff_needed
                        current_item.uses.uses += diff_needed
                        # Get a new current_item
                        current_item = item
                    else:
                        current_item.uses.uses += item.uses.uses
                        item.uses.uses = 0
                        # Do not get a new current_item
                else:
                    current_item = item
            else:
                current_item = item
        # remove all items with <= 0 uses
        self.convoy = [item for item in self.convoy if not item.uses or item.uses.uses > 0]

    def quick_sort_inventories(self, units):
        logger.debug("Quicksorting Inventories")
        my_units = [unit for unit in units if unit.team == 'player' and not unit.dead]
        random.shuffle(my_units)
        # print([my_unit.name for my_unit in my_units])
        # First, give all
        for unit in my_units:
            for item in reversed(unit.items):
                unit.remove_item(item)
                self.convoy.append(item)
        # Now restock convoy
        self.restock_convoy()
        # For item in convoy
        # Distribute Weapons
        weapons = sorted([item for item in self.convoy if item.weapon], key=lambda i: (i.weapon.LVL, 100 - i.uses.uses if i.uses else 0))
        # weapons = sorted(weapons, key=lambda i: i.uses.uses if i.uses else 100, reverse=True) # Now sort by uses, so we use weapons with more uses first
        # print(weapons)
        for weapon in weapons:
            units_that_can_wield = [unit for unit in my_units if len(unit.items) < cf.CONSTANTS['max_items'] - 1 and
                                    unit.canWield(weapon) and weapon.id not in [item.id for item in unit.items]]
            units_that_can_wield = sorted(units_that_can_wield, key=lambda u: len(u.items), reverse=True)
            # print([unit.name for unit in units_that_can_wield])
            if units_that_can_wield:
                # Give randomly
                unit = units_that_can_wield.pop()
                unit.add_item(weapon)
                self.convoy.remove(weapon)
                # print(unit.name, weapon)
        # Distribute spells
        spells = sorted([item for item in self.convoy if item.spell], key=lambda i: (i.spell.LVL, 100 - i.uses.uses if i.uses else 0))
        # print(spells)
        for spell in spells:
            units_that_can_wield = [u for u in my_units if len(u.items) < cf.CONSTANTS['max_items'] - 1 and
                                    u.canWield(spell) and spell.id not in [item.id for item in u.items]]
            units_that_can_wield = sorted(units_that_can_wield, key=lambda u: len(u.items), reverse=True)
            # print([unit.name for unit in units_that_can_wield])
            if units_that_can_wield:
                # Give randomly
                unit = units_that_can_wield.pop()
                unit.add_item(spell)
                self.convoy.remove(spell)
                # print(unit.name, spell)
        # Distribute healing items
        healing_items = sorted([item for item in self.convoy if item.usable and item.heal], key=lambda i: (i.heal, i.uses.uses if i.uses else 100))
        # print(healing_items)
        # Sort by max hp
        units_that_can_wield = [u for u in my_units if len(unit.items) < cf.CONSTANTS['max_items'] and not any(item.heal for item in u.items)]
        units_that_can_wield = sorted(units_that_can_wield, key=lambda u: u.stats['HP'])
        for healing_item in reversed(healing_items):
            if units_that_can_wield:
                unit = units_that_can_wield.pop()
                unit.add_item(healing_item)
                self.convoy.remove(healing_item)
        # Done

    def output_progress(self):
        with open('Saves/progress_log.txt', 'a') as p_log:
            p_log.write('\n')
            p_log.write('\n=== Level ' + str(self.counters['level']) + ' === Money: ' + str(self.counters['money']))
            for unit in self.allunits:
                p_log.write('\n*** ' + unit.name + ': ' + ','.join([skill.name for skill in unit.status_effects]))
                p_log.write('\nLvl ' + str(unit.level) + ', Exp ' + str(unit.exp))
                p_log.write('\nWexp: ' + ', '.join([str(wexp_num) for wexp_num in unit.wexp]))
                p_log.write('\nItems: ' + ', '.join([item.name + ' ' + str(item.uses.uses if item.uses else '--') for item in unit.items]))
            p_log.write('\n*** Convoy:')
            p_log.write('\nItems: ' + ', '.join([item.name + ' ' + str(item.uses.uses if item.uses else '--') for item in self.convoy]))
