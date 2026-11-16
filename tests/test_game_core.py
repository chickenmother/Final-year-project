"""Milestone 1 tests for the task-oriented game core."""
import json
import unittest

from game.entities import Bot, Bullet
from game.simulation import Game
from game.workload import get_profile


class GameCoreTests(unittest.TestCase):
    def test_profiles(self):
        self.assertEqual(get_profile("light").bots, 0)
        self.assertGreater(get_profile("medium").obstacles, 0)
        self.assertGreater(get_profile("heavy").bots, get_profile("medium").bots)

    def test_light_initial_state(self):
        game = Game("light", seed=7)
        self.assertEqual(len(game.bots), 0)
        self.assertEqual(len(game.obstacles), 8)
        self.assertEqual(game.player.hp, game.player.max_hp)
        self.assertFalse(game.game_over)

    def test_bullet_damages_obstacle(self):
        game = Game("light", seed=7)
        obstacle = game.obstacles[0]
        bullet = Bullet(obstacle.rect.centerx - 4, obstacle.rect.centery - 8,
                        0, 0, "player", damage=20)
        game.bullets.append(bullet)
        before = obstacle.hp
        game.step("")
        self.assertTrue(obstacle.hp < before or obstacle not in game.obstacles)

    def test_bullet_kills_bot_and_spawns_particles(self):
        game = Game("light", seed=7)
        bot = Bot(game.player.rect.x + 120, game.player.rect.y)
        game.bots.append(bot)
        bullet = Bullet(bot.rect.centerx - 4, bot.rect.centery - 8,
                        0, 0, "player", damage=bot.max_hp)
        game.bullets.append(bullet)
        game.step("")
        self.assertNotIn(bot, game.bots)
        self.assertGreaterEqual(game.score, 100)
        self.assertGreater(len(game.effects), 0)

    def test_player_collision_damages_hp(self):
        game = Game("light", seed=7)
        game.player.hp = 100
        game.player_hit_cooldown = 0.0
        obstacle = game.obstacles[0]
        game.player.rect.center = obstacle.rect.center
        game.step("")
        self.assertLess(game.player.hp, 100)

    def test_snapshot_restore_determinism(self):
        game = Game("light", seed=11)
        script = ["d", "dw", "s", " ", "a", "as", ""] * 5
        for keys in script:
            game.step(keys)
        state = json.loads(json.dumps(game.snapshot()))

        clone = Game("light", seed=999)
        clone.restore(state)
        self.assertEqual(clone.digest(), game.digest())

        for keys in script:
            game.step(keys)
            clone.step(keys)
        self.assertEqual(clone.digest(), game.digest())

    def test_game_over(self):
        game = Game("light", seed=7)
        game.player.hp = 0
        game.step("")
        self.assertTrue(game.game_over)
        self.assertEqual(game.player.hp, 0)

    def test_render_image_and_jpeg(self):
        game = Game("light", seed=7)
        image = game.render_image((480, 270), smooth=False)
        self.assertEqual(image.size, (480, 270))
        jpg = game.render((480, 270), 40, smooth=False)
        self.assertGreater(len(jpg), 100)
        self.assertEqual(jpg[:2], b"\xff\xd8")


if __name__ == "__main__":
    unittest.main()
