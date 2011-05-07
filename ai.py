#! /usr/bin/env python
# -*- coding: utf-8 -*-

import paramiko
import time
import re
from lib import TermEmulator
import sys

FORCE_REFRESH = 10
RECV_BUFF = 9999
SLEEP_BETWEEN_ACTIONS = 0.8
SLEEP_BETWEEN_REFRESH = 1.5

PLAYER_NAME = 'xuvaros'
PLAYER_PASSWORD = 'poussin'

DEBUG = True

class character:
    health = -1
    maxhealth = -1
    magic = -1
    maxmagic = -1

class crawlgame(object):
    def __init__(self):
        self.gamehdl = paramiko.SSHClient()
        self.gamehdl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.gamehdl.connect(hostname='crawl.akrasiac.org', port=22, username='joshua', password='joshua', timeout=5)
        self.chan = self.gamehdl.invoke_shell()
        # Initialise the character variables
        self.char = character()
        self.screen = TermEmulator.V102Terminal(24,80)
       
    def __del__(self):
        self.close()
        
    def close(self):
        self.gamehdl.close()

    def get_communication(self):
        return self.chan

    def pompe_screen(self):
        """Pompe les events graphiques, permet de ne pas fuller le buffer de SSH"""
        self.extract_vision()

    def recv_checkpoint(self, phrase):
        """Pompe les events graphique jusqu'une phrase precise soit trouvee"""
        ss_ecran = self.extract_vision()
        if phrase in ss_ecran:
            return ss_ecran
        else:
            return None
        


    def log(self):
        if self.recv_checkpoint("Not logged in.") == None:
            return -1
        self.chan.sendall('l')
        self.chan.sendall('%s\n' % PLAYER_NAME)
        self.chan.sendall('%s\n' % PLAYER_PASSWORD)
        time.sleep(SLEEP_BETWEEN_ACTIONS)
        self.pompe_screen()
        time.sleep(SLEEP_BETWEEN_REFRESH)
        self.chan.sendall('1') # play now!
        time.sleep(SLEEP_BETWEEN_ACTIONS)
        self.chan.sendall('p')
        time.sleep(SLEEP_BETWEEN_ACTIONS)

    def create_perso(self):
        time.sleep(SLEEP_BETWEEN_REFRESH)
        if self.recv_checkpoint("Please select your species.") == None:
            return -1
        self.chan.sendall('o') # Troll
        time.sleep(SLEEP_BETWEEN_REFRESH)
        self.chan.sendall('h') # Berserker
        time.sleep(SLEEP_BETWEEN_REFRESH)

    def jouer(self):
        # Delay lorsqu'on part
        time.sleep(SLEEP_BETWEEN_REFRESH)
        ticks = 0
        test_bouffe = False
        while True:
            if ticks % FORCE_REFRESH:
                # Envoyer un force refresh
                self.chan.sendall('\x12')
                test_bouffe = True
            time.sleep(SLEEP_BETWEEN_ACTIONS)
            ecran = self.extract_vision()
            if DEBUG:
                print(ecran)
            self.parse_stats()
           
            # Pomper les evenements qui arrivent pas souvent 
            if "--more--" in self.extract_vision().splitlines()[-1]:
                self.chan.sendall(' ')
                continue
            
            if "Increase (S)trength, (I)ntelligence, or (D)exterity?" in self.extract_vision().splitlines()[-2]:
                self.chan.sendall('s')
                continue
            
            # On Dying
            #if "Inventory:"

            wanted_direction = self.nearest_symbol_direction('abcdefghijklmnopqrstuvwxyz@ABCDEFGHIJKLMNOPQRSTUVWXYZ')
            if wanted_direction != 's':
            #ennemies = self.get_near_ennemies()
            #if len(ennemies) > 0:
                self.statemachine = 'attack'
            elif ("ungry" in self.extract_vision() or "tarving" in self.extract_vision()) and test_bouffe: # Pas de lettre initiale pour matcher Near starving et Starving
                self.statemachine = 'manger'
            elif "Done exploring." in self.extract_vision().splitlines()[-2]:
                self.statemachine = 'deeper'
            elif '%' in "".join(self.extract_map()) and self.nearest_symbol_direction('%') != 's':
                # Checker bouffe apres pour qu'on depose les skeleton à terre...
                self.statemachine = 'chunker_bouffe'
            else:
                self.statemachine = None
            
            # The State Machine
            if self.statemachine == 'attack':
                # On check notre vie voir si tout va bien 
                # On determine par ou il faut aller pour tuer l'ennemi le plus proche
                wanted_direction = self.nearest_symbol_direction('abcdefghijklmnopqrstuvwxyz@ABCDEFGHIJKLMNOPQRSTUVWXYZ')
                print("on veut aller chercher l'ennemi vers %s" % wanted_direction)
                self.chan.sendall(wanted_direction)
            elif self.statemachine == 'manger':
                self.chan.sendall('e')
                time.sleep(0.3)
                if "You aren't carrying any food." in self.extract_vision().splitlines()[-2]:
                    test_bouffe = False
                else:
                    self.chan.sendall(self.extract_vision().splitlines()[2].strip()[0]) # Prendre la premiere bouffe du coin
            elif self.statemachine == 'chunker_bouffe':
                # On mange + bouffe le corps!
                wanted_direction, distance = self.nearest_symbol_direction('%', distance=True)
                if distance == 1:
                    self.chan.sendall('%sce' % wanted_direction)
                    time.sleep(0.3)
                    if "(ye/n/q/i?)" in self.extract_vision().splitlines()[-2]:
                        while "(ye/n/q/i?)" in self.extract_vision().splitlines()[-2]:
                            self.chan.sendall('y')
                            time.sleep(0.3)
                    else:
                        self.chan.sendall('\x1bg') # C'est peut-être un skelette! on le prend aussi!
                else:
                    self.chan.sendall(wanted_direction)
            elif self.statemachine == 'deeper':
                # TODO: Dropper tous les skelettes...
                # TODO: if outside dungeon...
                print("We're going deeper!!!")
                self.chan.sendall("G>")
                time.sleep(1.5)
            else:
                # Default state - exploration
                if float(self.char.health)/float(self.char.maxhealth) < 0.55:
                    if DEBUG:
                        print('Healing self')
                    self.chan.sendall('5')
                    continue
                self.chan.sendall('o')
                # attendre un peu que tout ait bien...
                time.sleep(0.2)
            ticks += 1

    def extract_vision(self):
        buffer = b''
        while self.chan.recv_ready():
            time.sleep(0.5)
            buffer += self.chan.recv(RECV_BUFF)
            time.sleep(0.2)
        self.screen.ProcessInput(buffer)
        ss_ecran = "\n".join([a.tostring() for a in self.screen.GetRawScreen()])
        return ss_ecran

    def extract_map(self):
        ecran = self.extract_vision()
        return ["".join(a) for a in zip(*zip(*ecran.splitlines()[0:17])[:34])]

    def get_pathfinding(self):
        """
        retourne la map et une annotation a chaque point 2D la premiere direction (coup a jouer) pour s'y rendre.
        """
        map = self.extract_map()

        output = [[999 for b in range(len(map[0]))] for a in range(len(map))] # Laite que le *****
        output[8][16] = 0 # Par definition, c'est nous-meme...
        mapping = [['s' for b in range(len(map[0]))] for a in range(len(map))] # Laite que le ***** yet again
        # output = distances, mapping = direction du premier carre

        # Dijkstra pleurerait en voyant ca.
        old_output = ''
        while old_output != output:
            old_output = [a[:] for a in output]
            for y, outy in enumerate(output):
                for x, outx in enumerate(outy):
                    # Ensure that this point is walkable
                    if map[y][x] in ['#', ' ']:
                        continue
                    # Calculer par rapport au plus proche qu'on connait (carre de 8 proche)
                    for newy in range(y-1, y+2):
                        for newx in range(x-1, x+2):
                            if newx<0 or newx>len(outy)-1 or newy<0 or newy>len(output)-1:
                                continue
                            if y == newy and x == newx:
                                continue
                            if output[newy][newx] + 1 < output[y][x]:
                                # si c'est un carre du debut...
                                if mapping[newy][newx] == 's':
                                    mapping[y][x] = (((('y','u')[newx<x],'k')[newx==x],(('b','n')[newx<x],'j')[newx==x])[newy<y],('h','l')[newx<x])[newy==y]
                                else:
                                    mapping[y][x] = mapping[newy][newx]
                                output[y][x] = output[newy][newx] + 1
                            elif output[newy][newx] + 1 == output[y][x]:
                                # prioriser les lignes droites
                                if mapping[newy][newx] in 'hjkl':
                                    mapping[y][x] = mapping[newy][newx]

        return (map, output, mapping)


    def nearest_symbol_direction(self, symbols, distance=False):
        map, distances, directions = self.get_pathfinding()
        
        # trouver les ennemis
        direction_to_go = 's'
        ennemy_dist = 999
        for y, outy in enumerate(map):
            for x, outx in enumerate(outy):
                if map[y][x] in symbols:
                    if distances[y][x] < ennemy_dist and distances[y][x] > 0:
                        direction_to_go = directions[y][x]
                        ennemy_dist = distances[y][x]
        if distance == False:
            return direction_to_go
        else:
            return direction_to_go, ennemy_dist

        
    def parse_stats(self):
        ecran = self.extract_vision()

        # Extract health
        health_re = re.compile("Health: *(\d+)/(\d+)")
        magic_re = re.compile("Magic: *(\d+)/(\d+)")
        try:
            self.char.health = int(health_re.match(ecran[ecran.index("Health:"):].splitlines()[0]).group(1))
            self.char.maxhealth = int(health_re.match(ecran[ecran.index("Health:"):].splitlines()[0]).group(2))
            self.char.magic = int(magic_re.match(ecran[ecran.index("Magic:"):].splitlines()[0]).group(1))
            self.char.maxmagic = int(magic_re.match(ecran[ecran.index("Magic:"):].splitlines()[0]).group(2))
            print("Found: %u/%u - %u/%u" % (self.char.health, self.char.maxhealth, self.char.magic, self.char.maxmagic))
        except:
            print('Unable to parse stats : %s' % sys.exc_info()[0])

       
    def get_near_ennemies(self):
        ecran = self.extract_vision()
        lignes = ecran.splitlines()[11:16] # Ne prendre que les lignes 12 a 17, contenant des ennemis
        # Ne prendre que les colonnes 35+, contenant la liste des ennemis.
        return ["".join(a).strip() for a in zip(*zip(*lignes)[34:]) if "".join(a).strip() != '']

    def next_action(self):
        pass


if __name__ == '__main__':
    print('Connecting to server...')
    le_jeu = crawlgame()
    print('Connected')
    logging_ret = le_jeu.log()
    print('Logged.')
    perso_cree = le_jeu.create_perso()
    if perso_cree != -1:
        print('Character created!')
    print('Character generation passed')
    le_jeu.jouer()
    print('Quitting...')
    le_jeu.close()

