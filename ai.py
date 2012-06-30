#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Std lib import
import time
import re
import sys
import curses
import codecs
import random

# unused import
import fcntl
import os
import termios

# pip import
import pexpect

# local import
from lib import TermEmulator

FORCE_REFRESH = 10
BUFF_SIZE = 9999
SLEEP_BETWEEN_ACTIONS = 0.05
SLEEP_BETWEEN_REFRESH = 0

DEBUG = True

ennemy_symbols = 'abcdeghijklmnopqrstuvwxyz@ABCDEFGHIJKLMNOQRSTUVWXYZ5'
# f = fungus
# P = plant

UNWALKABLE = ['#', # Wall
              ' ', # Unknown terrain
              u'\u2663', # Undestructible Plant (evident, no?)
              'P', # Plant  Technically destructable but long...
              ]

class Character(object):
    health = -1
    maxhealth = -1
    magic = -1
    maxmagic = -1

class NotFoundOurselves(Exception):
    pass


def init_ssh_spawn(username, password, species="n", class_="h"):
    spawn = pexpect.spawn("ssh -p 22 joshua@crawl.akrasiac.org")
    spawn.expect("joshua@crawl.akrasiac.org's password:")
    spawn.sendline("joshua")
    spawn.expect("=>")
    spawn.send("l")
    spawn.expect("=>")
    spawn.sendline(username)
    spawn.expect("=>")
    spawn.sendline(password)
    spawn.expect("=>")
    spawn.send("1")
    spawn.expect("=>")
    spawn.send("P")
    try:
        spawn.expect("species", timeout=1)
    except pexpect.TIMEOUT:
        # Character already exists, skip the creation part
        return spawn

    spawn.send(species)
    spawn.expect("background")
    spawn.send(class_)
    return spawn

def init_local_spawn(name="", species="n", class_="h", path=""):
    """Spawn a local game of crawl for the player *name*, with
    a character *species* of class *class_*. The variable *path*
    should points to the crawl binary.
    """
    try:
        spawn = pexpect.spawn(path + "crawl")
    except pexpect.ExceptionPexpect:
        print "Wrong path to crawl."
        exit()

    spawn.expect("Enter your name:")
    spawn.send(name)
    spawn.sendline("\r")
    spawn.send(species)
    spawn.send(class_)
    return spawn

class CrawlGame(object):
    def __init__(self, in_scr, spawn):
        # Initialize the character variables
        self.char = Character()
        # Initialize virtual terminal emulation
        self.term = TermEmulator.V102Terminal(24, 100)
        self.stdscr = in_scr
        self.spawn = spawn
        time.sleep(SLEEP_BETWEEN_ACTIONS)

    def pompe_screen(self):
        """Pump graphic events, permet de ne pas fuller le buffer de SSH"""
        self.extract_vision()

    def recv_checkpoint(self, sequence):
        """Pump graphic events until a specific sequence is found"""
        ss_ecran = self.extract_vision()
        if sequence in ss_ecran:
            return ss_ecran
        else:
            return None

    def action(self, action, refresh=True):
        self.spawn.send(action)
        time.sleep(SLEEP_BETWEEN_ACTIONS)
        # Refresh screen before extracting
        self.spawn.send('\x12')
        time.sleep(SLEEP_BETWEEN_ACTIONS)
        self.screen = self.extract_vision()

    def menu(self, menu):
        self.spawn.send(menu)
        time.sleep(SLEEP_BETWEEN_ACTIONS)
        self.screen = self.extract_vision()

    def jouer(self):
        # Delay lorsqu'on part
        time.sleep(SLEEP_BETWEEN_REFRESH)
        ticks = 0
        test_bouffe = False

        GetCharColor = self.term.GetRendition
        self.screen = self.extract_vision()

        while True:
            # Refresh screen
            self.stdscr.refresh()
            # Check if keypress
            if self.stdscr.getch() >= 0:
                self.spawn.interact()
                return

            # Handling Debug
            if DEBUG:
                with codecs.open('log.txt', 'ab', "utf-8") as hdl:
                    hdl.write('\r\n'+u'-'*80)
                    hdl.write(self.screen)
                print('\r' + '-'*80 + '\r')
                print(self.screen+'\r')

            # Get character stats
            self.parse_stats()

            # Upon Dying
            if "You die..." in "".join(self.extract_history()):
                self.spawn.send('          qq') # Spam spacebar and then quit
                a = ('Died...\r')
                self.stdscr.refresh()
                while self.stdscr.getch() >= 0:
                    time.sleep(0.5)
                return

            # Pump rare (level up) or too much events
            if "--more--" in "".join(self.extract_history()):
                self.action(' ')
                continue

            # Handling of level ups
            if "Increase (S)trength, (I)ntelligence, or (D)exterity?" in self.screen.splitlines()[-2]:
                self.action('s')
                continue

            # The Emotional Case
            wanted_attack_dir, symb_atk, dist, pos = self.nearest_symbol_direction(ennemy_symbols)
            wanted_food_dir, symb_food, dist_food, pos_food = self.nearest_symbol_direction('%')
            print('Position de la bouffe: %s\r' % str(pos_food))
            print('Couleur de la bouffe: %s\r' % str(GetCharColor(pos_food[0], pos_food[1])))

            history = "".join(self.extract_history())

            if wanted_attack_dir != 's':
            #ennemies = self.get_near_ennemies()
            #if len(ennemies) > 0:
                self.statemachine = 'attack'
            elif ("ungry" in self.screen or "tarving" in self.screen) and test_bouffe: # Pas de lettre initiale pour matcher Near starving et Starving
                self.statemachine = 'manger'
            elif "Done exploring." in history or "Partly explored, can't reach some items" in history:
                self.statemachine = 'deeper'
            elif '%' in "".join(self.extract_map()[0]) and \
                wanted_food_dir != 's' and \
                GetCharColor(pos_food[0], pos_food[1]) != (64L, 0L, 0L):
                self.statemachine = 'chunker_bouffe'
            elif len(self.get_near_ennemies()) > 0:
                # Problem: We can't path toward an ennemy...
                self.statemachine = 'go_random'
            else:
                self.statemachine = None

            print('Etat : %s' % self.statemachine)
            self.stdscr.refresh()

            # The State Machine
            if self.statemachine == 'attack':
                # On check notre vie voir si tout va bien
                # On determine par ou il faut aller pour tuer l'ennemi le plus proche
                wanted_direction, symb, dist, pos = self.nearest_symbol_direction(ennemy_symbols)
                print("on veut aller chercher l'ennemi [%s] vers %s\r" % (symb, wanted_direction))
                self.action(wanted_direction)
            elif self.statemachine == 'manger':
                self.menu('e')
                if "You aren't carrying any food." in self.screen.splitlines()[-2]:
                    test_bouffe = False
                else:
                    # Eat the first item from our stash
                    food_index = self.screen.splitlines()[2].strip()[0]
                    self.menu(food_index)
            elif self.statemachine == 'chunker_bouffe':
                # On mange + bouffe le corps!
                wanted_direction, symb, distance, pos = self.nearest_symbol_direction('%')
                if distance == 1:
                    self.action('%sce' % wanted_direction)
                    if "(ye/n/q/i?)" in self.screen.splitlines()[-2]:
                        while "(ye/n/q/i?)" in self.screen.splitlines()[-2]:
                            self.menu('y')
                    else:
                        self.action('\x1bg') # C'est peut-être un skelette! on le prend aussi!
                else:
                    self.action(wanted_direction)
            elif self.statemachine == 'deeper':
                # TODO: Dropper tous les skelettes...
                # TODO: if outside dungeon...
                print("We're going deeper!!!\r")
                self.action("G>")
            elif self.statemachine == 'go_random':
                # TODO: Do something more logical...
                self.action(random.choice(['h', 'j', 'k', 'l', 'u', 'y', 'n', 'b']))
            else:
                # Default state - exploration
                if float(self.char.health)/float(self.char.maxhealth) < 0.55:
                    if DEBUG:
                        print('Healing self\r')
                    self.action('5')
                    continue
                self.action('o')
            ticks += 1

    def extract_vision(self):
        """Pipe stream from SSH to the terminal emulator and
        return the output (virtual screen).
        """
        #buffer_ = b''
        buffer_ = ''
        while not self.spawn.eof():
            #time.sleep(0.5)
            try:
                buffer_ += self.spawn.read_nonblocking(BUFF_SIZE, timeout=0.05)
            except pexpect.TIMEOUT:
                break
            #time.sleep(0.2)
        self.term.ProcessInput(buffer_.decode('utf-8'))
        ss_ecran = "\r\n".join([a.tounicode() for a in self.term.GetRawScreen()])
        return ss_ecran

    def extract_map(self):
        ecran = self.screen
        # Redo...
        ecran_rendition = self.term.GetRawScreenRendition()
        return ["".join(a) for a in zip(*zip(*ecran.splitlines()[0:17])[:34])], [[b & 0x0000ff00 >> 8 for b in a] for a in zip(*zip(*ecran_rendition[0:17])[:34])]

    def extract_history(self):
        ecran = self.screen.splitlines()
        if ecran == None or len(ecran) < 1:
            return []
        return ecran[-7:]

    def last_history(self):
        history = self.extract_history()
        history.reverse()
        for a in history:
            if a is not None and len(a.strip()) > 0:
                return a
        return ''

    def get_pathfinding(self):
        """
        Retourne la map et une annotation a chaque point 2D la premiere direction (coup a jouer) pour s'y rendre.
        """
        map, color = self.extract_map()

        # Get out position
        our_pos = (-1, -1)
        for y, outy in enumerate(map):
            for x, outx in enumerate(outy):
                if map[y][x] == '@' and self.term.GetRendition(y,x) == (64L, 0, 0):
                    our_pos = (y, x)
                    # No break since there can be ennemies as @
        if our_pos == (-1, -1):
            raise NotFoundOurselves
        # Set initial pathfinding graph values
        output = [[999 for b in range(len(map[0]))] for a in range(len(map))] # Laite que le *****
        output[our_pos[0]][our_pos[1]] = 0
        mapping = [['s' for b in range(len(map[0]))] for a in range(len(map))] # Laite que le ***** yet again
        # output = distances, mapping = direction du premier carre

        # Dijkstra pleurerait en voyant ca.
        old_output = ''
        while old_output != output:
            old_output = [a[:] for a in output]
            for y, outy in enumerate(output):
                for x, outx in enumerate(outy):
                    # Ensure that this point is walkable
                    if map[y][x] in UNWALKABLE:
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


    def nearest_symbol_direction(self, symbols):
        try:
            map, distances, directions = self.get_pathfinding()
        except NotFoundOurselves as e:
            print('Not found...: %s\r' % e)
            time.sleep(1)
            self.stdscr.refresh()
            return None, '', 0, (-1, -1)

        # Find ennemies
        direction_to_go = 's'
        ennemy_dist = 999
        symbol = ''
        pos = (-1, -1)
        for y, outy in enumerate(map):
            for x, outx in enumerate(outy):
                if map[y][x] in symbols:
                    if distances[y][x] < ennemy_dist and distances[y][x] > 0:
                        direction_to_go = directions[y][x]
                        ennemy_dist = distances[y][x]
                        symbol = map[y][x]
                        pos = (y, x)
        return direction_to_go, symbol, ennemy_dist, pos


    def parse_stats(self):
        ecran = self.screen

        # Extract health and magic
        health_re = re.compile("Health: *(\d+)/(\d+)")
        magic_re = re.compile("Magic: *(\d+)/(\d+)")
        try:
            self.char.health = int(health_re.match(ecran[ecran.index("Health:"):].splitlines()[0]).group(1))
            self.char.maxhealth = int(health_re.match(ecran[ecran.index("Health:"):].splitlines()[0]).group(2))
            self.char.magic = int(magic_re.match(ecran[ecran.index("Magic:"):].splitlines()[0]).group(1))
            self.char.maxmagic = int(magic_re.match(ecran[ecran.index("Magic:"):].splitlines()[0]).group(2))
            print("Found: %u/%u - %u/%u\r" % (self.char.health, self.char.maxhealth, self.char.magic, self.char.maxmagic))
        except:
            print('Unable to parse stats : %s\r' % sys.exc_info()[0])


    def get_near_ennemies(self):
        ecran = self.screen
        lignes = ecran.splitlines()[12:16] # Ne prendre que les lignes 12 a 17, contenant des ennemis
        # Ne prendre que les colonnes 35+, contenant la liste des ennemis.
        return ["".join(a).strip() for a in zip(*zip(*lignes)[34:]) if "".join(a).strip() != '']

    def next_action(self):
        pass


def main(stdscr):
    print('Connecting to server...\r')
    stdscr.nodelay(True)
    spawn = init_local_spawn("Bobby")
    le_jeu = CrawlGame(stdscr, spawn)
    print('Connected\r')
    stdscr.refresh()
    # Be sure that we're not on the stale screen
    while u'some stale' in le_jeu.extract_vision():
        time.sleep(1)
    le_jeu.jouer()
    print('Quitting...\r')
    stdscr.refresh()
    spawn.terminate()


if __name__ == '__main__':
    curses.wrapper(main)
