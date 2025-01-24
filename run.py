import pickle
import sys
import pygame
from pygame.locals import *
import neat
import os

import visualize
from constants import *
from pacman import Pacman
from nodes import NodeGroup
from pellets import PelletGroup
from ghosts import GhostGroup
from fruit import Fruit
from pauser import Pause
from text import TextGroup
from sprites import LifeSprites
from sprites import MazeSprites
from mazedata import MazeData


class GameController(object):
    def __init__(self, train_mode=False, net=None, config=None):
        """
        :param train_mode: se True, la partita viene gestita in modalità training (senza input utente).
        :param net: rete neurale di NEAT (solo in modalità training).
        :param config: configurazione NEAT (opzionale, in caso serva).
        """
        pygame.init()
        self.screen = pygame.display.set_mode(SCREENSIZE, 0, 32)
        self.background = None
        self.background_norm = None
        self.background_flash = None
        self.clock = pygame.time.Clock()
        self.fruit = None
        self.pause = Pause(not train_mode)
        self.level = 0
        self.lives = 0
        self.score = 0
        self.textgroup = TextGroup()
        self.lifesprites = LifeSprites(self.lives)
        self.flashBG = False
        self.flashTime = 0.2
        self.flashTimer = 0
        self.fruitCaptured = []
        self.fruitNode = None
        self.mazedata = MazeData()

        # Variabili utili in modalità training
        self.train_mode = train_mode
        self.net = net
        self.neat_config = config
        self.game_over = False  # Per sapere se la partita è terminata in modalità training

    def setBackground(self):
        self.background_norm = pygame.surface.Surface(SCREENSIZE).convert()
        self.background_norm.fill(BLACK)
        self.background_flash = pygame.surface.Surface(SCREENSIZE).convert()
        self.background_flash.fill(BLACK)
        self.background_norm = self.mazesprites.constructBackground(self.background_norm, self.level % 5)
        self.background_flash = self.mazesprites.constructBackground(self.background_flash, 5)
        self.flashBG = False
        self.background = self.background_norm

    def startGame(self):
        self.mazedata.loadMaze(self.level)
        self.mazesprites = MazeSprites(self.mazedata.obj.name + ".txt", self.mazedata.obj.name + "_rotation.txt")
        self.setBackground()
        self.nodes = NodeGroup(self.mazedata.obj.name + ".txt")
        self.mazedata.obj.setPortalPairs(self.nodes)
        self.mazedata.obj.connectHomeNodes(self.nodes)

        # Creiamo l'istanza di Pacman
        # In modalità training, useremo la logica AI interna (override del getValidKey).
        self.pacman = Pacman(self.nodes.getNodeFromTiles(*self.mazedata.obj.pacmanStart),
                             train_mode=self.train_mode,
                             net=self.net,
                             config=self.neat_config)

        self.pellets = PelletGroup(self.mazedata.obj.name + ".txt")
        self.ghosts = GhostGroup(self.nodes.getStartTempNode(), self.pacman)

        self.ghosts.pinky.setStartNode(self.nodes.getNodeFromTiles(*self.mazedata.obj.addOffset(2, 3)))
        self.ghosts.inky.setStartNode(self.nodes.getNodeFromTiles(*self.mazedata.obj.addOffset(0, 3)))
        self.ghosts.clyde.setStartNode(self.nodes.getNodeFromTiles(*self.mazedata.obj.addOffset(4, 3)))
        self.ghosts.setSpawnNode(self.nodes.getNodeFromTiles(*self.mazedata.obj.addOffset(2, 3)))
        self.ghosts.blinky.setStartNode(self.nodes.getNodeFromTiles(*self.mazedata.obj.addOffset(2, 0)))

        self.nodes.denyHomeAccess(self.pacman)
        self.nodes.denyHomeAccessList(self.ghosts)
        self.ghosts.inky.startNode.denyAccess(RIGHT, self.ghosts.inky)
        self.ghosts.clyde.startNode.denyAccess(LEFT, self.ghosts.clyde)
        self.mazedata.obj.denyGhostsAccess(self.ghosts, self.nodes)

        if self.train_mode:
            self.pause.paused = False
            self.textgroup.hideText()

    def update(self):
        dt = self.clock.tick(60) / 1000.0
        self.textgroup.update(dt)
        self.pellets.update(dt)

        # Se il gioco è in pausa, fermiamo certe logiche
        if not self.pause.paused:
            self.ghosts.update(dt)
            if self.fruit is not None:
                self.fruit.update(dt)

            self.checkPelletEvents()
            self.checkGhostEvents()
            self.checkFruitEvents()

        if self.pacman.alive:
            if not self.pause.paused:
                self.pacman.update(dt)
        else:
            # Pacman morto
            self.pacman.update(dt)

        if self.flashBG:
            self.flashTimer += dt
            if self.flashTimer >= self.flashTime:
                self.flashTimer = 0
                if self.background == self.background_norm:
                    self.background = self.background_flash
                else:
                    self.background = self.background_norm

        afterPauseMethod = self.pause.update(dt)
        if afterPauseMethod is not None:
            afterPauseMethod()


        self.checkEvents()

        # Verifichiamo se dobbiamo terminare la partita in training
        if self.train_mode:
            # Ad esempio, consideriamo partita finita se Pacman non è vivo o se ha finito le vite
            if not self.pacman.alive or self.lives < 0:
                self.game_over = True

        self.render()

    def checkEvents(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == KEYDOWN:
                if not self.train_mode:  # Solo in modalità non-AI gestisci KEYDOWN (EVITA IL BUG DI CRASH WINDOW).
                    if event.key == K_SPACE:
                        if self.pacman.alive:
                            self.pause.setPause(playerPaused=True)
                            if not self.pause.paused:
                                self.textgroup.hideText()
                                self.showEntities()
                            else:
                                self.textgroup.showText(PAUSETXT)

    def checkPelletEvents(self):
        pellet = self.pacman.eatPellets(self.pellets.pelletList)
        if pellet:
            self.pellets.numEaten += 1
            self.updateScore(pellet.points)
            if self.pellets.numEaten == 30:
                self.ghosts.inky.startNode.allowAccess(RIGHT, self.ghosts.inky)
            if self.pellets.numEaten == 70:
                self.ghosts.clyde.startNode.allowAccess(LEFT, self.ghosts.clyde)
            self.pellets.pelletList.remove(pellet)
            if pellet.name == POWERPELLET:
                self.ghosts.startFreight()
            if self.pellets.isEmpty():
                # Fine livello (vittoria). Per semplicità, chiudiamo il gioco.
                if self.train_mode:
                    self.game_over = True
                else:
                    pygame.quit()
                    sys.exit()

    def checkGhostEvents(self):
        for ghost in self.ghosts:
            if self.pacman.collideGhost(ghost):
                if ghost.mode.current is FREIGHT:
                    self.pacman.visible = False
                    ghost.visible = False
                    self.updateScore(ghost.points)
                    self.textgroup.addText(str(ghost.points), WHITE, ghost.position.x, ghost.position.y, 8, time=1)
                    self.ghosts.updatePoints()
                    self.pause.setPause(pauseTime=1, func=self.showEntities)
                    ghost.startSpawn()
                    self.nodes.allowHomeAccess(ghost)
                elif ghost.mode.current is not SPAWN:
                    if self.pacman.alive:
                        self.lives -= 1
                        self.lifesprites.removeImage()
                        self.pacman.die()
                        self.ghosts.hide()
                        if self.lives <= 0:
                            self.textgroup.showText(GAMEOVERTXT)
                            if self.train_mode:
                                self.game_over = True
                            else:
                                self.pause.setPause(pauseTime=3, func=self.restartGame)
                        else:
                            self.pause.setPause(pauseTime=3, func=self.resetLevel)

    def checkFruitEvents(self):
        if self.pellets.numEaten == 50 or self.pellets.numEaten == 140:
            if self.fruit is None:
                self.fruit = Fruit(self.nodes.getNodeFromTiles(9, 20), self.level)
        if self.fruit is not None:
            if self.pacman.collideCheck(self.fruit):
                self.updateScore(self.fruit.points)
                self.textgroup.addText(str(self.fruit.points), WHITE, self.fruit.position.x, self.fruit.position.y, 8, time=1)
                fruitCaptured = False
                for fruit in self.fruitCaptured:
                    if fruit.get_offset() == self.fruit.image.get_offset():
                        fruitCaptured = True
                        break
                if not fruitCaptured:
                    self.fruitCaptured.append(self.fruit.image)
                self.fruit = None
            elif self.fruit.destroy:
                self.fruit = None

    def showEntities(self):
        self.pacman.visible = True
        self.ghosts.show()

    def hideEntities(self):
        self.pacman.visible = False
        self.ghosts.hide()

    def nextLevel(self):
        self.showEntities()
        self.level += 1
        self.pause.paused = True
        self.startGame()
        self.textgroup.updateLevel(self.level)

    def restartGame(self):
        self.lives = 0
        self.level = 0
        self.pause.paused = True
        self.fruit = None
        self.startGame()
        self.score = 0
        self.textgroup.updateScore(self.score)
        self.textgroup.updateLevel(self.level)
        self.textgroup.showText(READYTXT)
        self.lifesprites.resetLives(self.lives)
        self.fruitCaptured = []

    def resetLevel(self):
        self.pause.paused = True
        self.pacman.reset()
        self.ghosts.reset()
        self.fruit = None
        self.textgroup.showText(READYTXT)

    def updateScore(self, points):
        self.score += points
        self.textgroup.updateScore(self.score)

    def render(self):
        self.screen.blit(self.background, (0, 0))
        self.pellets.render(self.screen)
        if self.fruit is not None:
            self.fruit.render(self.screen)
        self.pacman.render(self.screen)
        self.ghosts.render(self.screen)
        self.textgroup.render(self.screen)

        for i in range(len(self.lifesprites.images)):
            x = self.lifesprites.images[i].get_width() * i
            y = SCREENHEIGHT - self.lifesprites.images[i].get_height()
            self.screen.blit(self.lifesprites.images[i], (x, y))

        for i in range(len(self.fruitCaptured)):
            x = SCREENWIDTH - self.fruitCaptured[i].get_width() * (i + 1)
            y = SCREENHEIGHT - self.fruitCaptured[i].get_height()
            self.screen.blit(self.fruitCaptured[i], (x, y))

        pygame.display.update()


###############################################################################
#                        FUNZIONI DI TRAINING NEAT                             #
###############################################################################

def eval_genomes(genomes, config):
    """
    Funzione richiamata da NEAT per valutare i genomi.
    Per ogni genome, creiamo un GameController in modalità training.
    In questo esempio, la fitness sarà data semplicemente dallo score.
    """
    for genome_id, genome in genomes:
        # Creiamo la rete neurale corrispondente a questo genome
        net = neat.nn.FeedForwardNetwork.create(genome, config)

        # Avviamo il gioco in modalità training
        game = GameController(train_mode=True, net=net, config=config)
        game.startGame()

        # Eseguiamo un ciclo finché il gioco non termina o raggiungiamo un limite step
        steps = 0
        max_steps = 2000  # Limite di step arbitrario per evitare loop infiniti
        while not game.game_over and steps < max_steps:
            game.update()
            steps += 1

        # Assegniamo al genome la fitness basata sul punteggio accumulato
        genome.fitness = game.score


def run_neat(config_file):
    """
    runs the NEAT algorithm to train a neural network to play snakes.
    :param config_file: location of config file
    :return: None
    """
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_file)

    # Create the population, which is the top-level object for a NEAT run.
    p = neat.Population(config)

    # Add a stdout reporter to show progress in the terminal.
    p.add_reporter(neat.StdOutReporter(True))
    stats = neat.StatisticsReporter()
    p.add_reporter(stats)

    # Run for up to 100 generations.
    winner = p.run(eval_genomes, 100)
    with open("winner.pkl", "wb") as f:
        pickle.dump(winner, f)
        f.close()

    # Display the winning genome
    print('\nBest genome:\n{!s}'.format(winner))

    # Draw stats and NN structure
    visualize.plot_stats(stats, ylog=False, view=True)
    visualize.draw_net(config, winner, True)

def replay_genome(config_file, genome_path="winner.pkl"):
    # Load required NEAT config
    config = neat.config.Config(neat.DefaultGenome, neat.DefaultReproduction,
                                neat.DefaultSpeciesSet, neat.DefaultStagnation,
                                config_file)

    # Unpickle saved winner
    with open(genome_path, "rb") as f:
        genome = pickle.load(f)

    # Convert loaded genome into required data structure
    genomes = [(1, genome)]

    # Draw the NN structure
    visualize.draw_net(config, genome, True)

    # Call game with only the loaded genome
    eval_genomes(genomes, config)


###############################################################################
#                           AVVIO DELLO SCRIPT                                #
###############################################################################

if __name__ == "__main__":#
    local_dir = os.path.dirname(__file__)
    config_path = os.path.join(local_dir, "neat-config.txt")

    print("************************************")
    print("     Pac-ManAI v1.0    ")
    print("************************************")

    print("Allenare una AI con NEAT (1)")
    print("Giocare manualmente (2)")
    print("Far giocare l'AI (3)")
    choice = input("Input: ")

    if choice == "1":
        # Avvia il training NEAT
        if not os.path.exists(config_path):
            print("Non trovo il file di configurazione NEAT (neat-config.txt). Creane uno o aggiorna il path.")
            sys.exit(1)
        run_neat(config_path)
    elif choice == "2":
        # Avvia il gioco manuale
        game = GameController()
        game.startGame()
        while True:
            game.update()
    elif choice == "3":
        try:
            replay_genome(config_path)
        except:
            print('There is no genome to test in the program directory or it has been renamed')
            print('If you renamed it change the name back to "winner.pkl" if you want the program to run correctly')
            close = input('Press Enter to exit...')
            sys.exit()